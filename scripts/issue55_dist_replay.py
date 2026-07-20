"""이슈 #55 재측정 리플레이 — READ-ONLY.

과거 전 가용 구간(KOSPI 1001 + KOSDAQ 2001)의 국면 라벨을 4 시나리오로 재생·비교:

  A = classic 분배 정의 × 무효화 임계 6 (현행)
  B = classic × 5
  C = classic+stalling(#55 신설) × 6
  D = classic+stalling × 5

측정 항목 (LOOP_SPEC DC-5):
- 시나리오별 라벨 변경 일수 + 전이 내역(from→to)
- confirmed_uptrend 일수 증감, 룰3(FTD 무효화) 발동 빈도
- C vs A 에서 dist_count 가 co-anchor 경계(≥5 / >3)를 넘는 일수 변화
- 참고: classic 분배일 중 일중 상단 절반 마감 일수 (A2 광의 해석 stakes)

안전장치 (scripts/p2_1a_replay.py 패턴):
- read-only connection (default_transaction_read_only=on) — DB 레벨 강제.
- upsert / commit 절대 호출 안 함. 순수 계산 + CSV/stdout 출력만.
- σ / FTD / dist 임계는 운영 경로와 동일하게 per-date 파생 (look-ahead 없음).

사용:
    uv run python scripts/issue55_dist_replay.py \
        [--csv docs/superpowers/verification/2026-07-21-issue55-dist-replay.csv]
"""
import argparse
import csv
import logging
import sys
from collections import Counter
from datetime import date

import psycopg

from kr_pipeline.common.config import Config
from kr_pipeline.common.thresholds import (
    NASDAQ_REFERENCE_SIGMA,
    FTD_PCT_BASE,
    DISTRIBUTION_PCT_BASE,
    KOREAN_SIGMA_RATIO_FLOOR,
    KOREAN_SIGMA_RATIO_CEILING,
    STATUS_DIST_COUNT_FOR_FTD_INVALIDATION,
    MARKET_DIST_DEMOTION_COUNT_25S,
    MARKET_DIST_NORMAL_MAX_25S,
    MARKET_STALL_CLOSE_RANGE_POS_MAX,
    STATUS_CORRECTION_OFF_HIGH_PCT,
    STATUS_DOWNTREND_OFF_HIGH_PCT,
    STATUS_FTD_INVALIDATION_DAYS,
)
from kr_pipeline.market_context.load import load_index_daily_with_sma200
from kr_pipeline.market_context.compute.distribution_day import (
    count_distribution_days,
    is_distribution_day,
    is_stalling_day,
)
from kr_pipeline.market_context.compute.follow_through import detect_last_ftd
from kr_pipeline.market_context.compute.status import determine_status
from kr_pipeline.market_context.compute.volatility import (
    compute_korean_sigma_pct,
    derive_market_thresholds,
    book_default_thresholds,
)

INDICES = [("1001", "KOSPI"), ("2001", "KOSDAQ")]
SIGMA_WARMUP_SESSIONS = 252   # σ full window + SMA200 확보 후부터 리플레이
CANDIDATE_THRESHOLD = 5       # 재측정 대상 후보값 (6→5)

# 라벨 서열 (DC-6(ii)) — 낮을수록 방어적. 강등 = 서열 하향 = 방어 조기화.
LABEL_RANK = {"downtrend": 0, "correction": 1, "rally_attempt": 2, "confirmed_uptrend": 3}


def _is_nan(v) -> bool:
    import math
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


def rule12_fired(close, sma_50, sma_200, off_high) -> bool:
    """status.py 룰 1·2 (dist 무관 correction/downtrend) 발동 여부."""
    if (sma_200 is not None and sma_50 is not None
            and close < sma_200 and sma_50 < sma_200
            and off_high < STATUS_DOWNTREND_OFF_HIGH_PCT):
        return True
    if (off_high < STATUS_CORRECTION_OFF_HIGH_PCT
            and sma_50 is not None and close < sma_50):
        return True
    return False


def rule3_fired(dist_count, last_ftd, today, threshold, close, sma_50, sma_200, off_high) -> bool:
    """룰 3(FTD 무효화 correction) 발동 여부 — 룰 1·2 미발동 전제."""
    if rule12_fired(close, sma_50, sma_200, off_high):
        return False
    if last_ftd is None:
        return False
    days_since = (today - last_ftd).days
    return dist_count >= threshold and days_since > STATUS_FTD_INVALIDATION_DAYS


def replay_index(conn, index_code: str, market: str, writer) -> dict:
    df = load_index_daily_with_sma200(conn, index_code, date(2000, 1, 1), date(2100, 1, 1))
    n = len(df)
    stats = {
        "market": market, "days": 0,
        "labels": {s: Counter() for s in "ABCD"},
        "trans_AB": Counter(), "trans_AC": Counter(), "trans_AD": Counter(),
        "rule3": Counter(),                       # 시나리오별 룰3 발동 일수
        "ge5_A": 0, "ge5_C": 0, "gt3_A": 0, "gt3_C": 0,   # co-anchor 경계
        "classic_days": 0, "stall_days": 0, "classic_upper_half": 0,  # 일 단위 플래그
        "sigma_fallback": 0,
    }

    for i in range(SIGMA_WARMUP_SESSIONS, n):
        row = df.iloc[i]
        d = row["date"]
        d = d if isinstance(d, date) else d.date()

        sigma = compute_korean_sigma_pct(conn, index_code, as_of=d)
        if sigma is None:
            th = book_default_thresholds(ftd_base=FTD_PCT_BASE, dist_base=DISTRIBUTION_PCT_BASE)
            stats["sigma_fallback"] += 1
        else:
            th = derive_market_thresholds(
                sigma, anchor_sigma=NASDAQ_REFERENCE_SIGMA,
                ftd_base=FTD_PCT_BASE, dist_base=DISTRIBUTION_PCT_BASE,
                clamp_floor=KOREAN_SIGMA_RATIO_FLOOR, clamp_ceiling=KOREAN_SIGMA_RATIO_CEILING,
            )
        dist_pct = th["distribution_pct"]

        dist_classic = count_distribution_days(
            df, end_idx=i, pct_threshold=dist_pct, include_stalling=False)
        dist_stall = count_distribution_days(
            df, end_idx=i, pct_threshold=dist_pct, include_stalling=True)
        assert dist_stall >= dist_classic, f"{index_code}@{d}: stall < classic"

        last_ftd = detect_last_ftd(df, end_idx=i, pct_threshold=th["ftd_pct"])

        close = float(row["close"])
        sma_50 = None if _is_nan(row["sma_50"]) else float(row["sma_50"])
        sma_200 = None if _is_nan(row["sma_200"]) else float(row["sma_200"])
        yearly_high = float(row["yearly_high"])
        off_high = (close - yearly_high) / yearly_high * 100 if yearly_high > 0 else 0.0

        def _status(dc, thr):
            return determine_status(
                close=close, sma_50=sma_50, sma_200=sma_200,
                pct_off_yearly_high=off_high, dist_count=dc,
                last_ftd_date=last_ftd, today_date=d,
                dist_count_for_ftd_invalidation=thr,
            )

        s = {
            "A": _status(dist_classic, STATUS_DIST_COUNT_FOR_FTD_INVALIDATION),
            "B": _status(dist_classic, CANDIDATE_THRESHOLD),
            "C": _status(dist_stall, STATUS_DIST_COUNT_FOR_FTD_INVALIDATION),
            "D": _status(dist_stall, CANDIDATE_THRESHOLD),
        }

        # 일 단위 분배 플래그 (당일 봉 자체의 성격 — A2 stakes 측정)
        y = df.iloc[i - 1]
        classic_flag = is_distribution_day(
            today_close=close, today_volume=float(row["volume"]),
            yesterday_close=float(y["close"]), yesterday_volume=float(y["volume"]),
            pct_threshold=dist_pct)
        stall_flag = is_stalling_day(
            today_close=close, today_volume=float(row["volume"]),
            today_high=float(row["high"]), today_low=float(row["low"]),
            yesterday_close=float(y["close"]), yesterday_volume=float(y["volume"]),
            pct_threshold=dist_pct)
        upper_half_flag = False
        if classic_flag:
            rng = float(row["high"]) - float(row["low"])
            if rng > 0:
                pos = (close - float(row["low"])) / rng
                upper_half_flag = pos > MARKET_STALL_CLOSE_RANGE_POS_MAX

        stats["days"] += 1
        for k in "ABCD":
            stats["labels"][k][s[k]] += 1
        for pair, key in (("AB", "trans_AB"), ("AC", "trans_AC"), ("AD", "trans_AD")):
            a, b = s[pair[0]], s[pair[1]]
            if a != b:
                stats[key][f"{a}->{b}"] += 1
        for k, dc, thr in (("A", dist_classic, STATUS_DIST_COUNT_FOR_FTD_INVALIDATION),
                           ("B", dist_classic, CANDIDATE_THRESHOLD),
                           ("C", dist_stall, STATUS_DIST_COUNT_FOR_FTD_INVALIDATION),
                           ("D", dist_stall, CANDIDATE_THRESHOLD)):
            if rule3_fired(dc, last_ftd, d, thr, close, sma_50, sma_200, off_high):
                stats["rule3"][k] += 1
        stats["ge5_A"] += dist_classic >= MARKET_DIST_DEMOTION_COUNT_25S
        stats["ge5_C"] += dist_stall >= MARKET_DIST_DEMOTION_COUNT_25S
        stats["gt3_A"] += dist_classic > MARKET_DIST_NORMAL_MAX_25S
        stats["gt3_C"] += dist_stall > MARKET_DIST_NORMAL_MAX_25S
        stats["classic_days"] += classic_flag
        stats["stall_days"] += stall_flag
        stats["classic_upper_half"] += upper_half_flag

        writer.writerow([
            index_code, d.isoformat(), f"{dist_pct:.4f}", f"{th['ftd_pct']:.4f}",
            dist_classic, dist_stall,
            s["A"], s["B"], s["C"], s["D"],
            int(classic_flag), int(stall_flag), int(upper_half_flag),
            last_ftd.isoformat() if last_ftd else "",
        ])
    return stats


def summarize(stats: dict) -> None:
    m, days = stats["market"], stats["days"]
    print(f"\n== {m} ({days} 거래일, σ fallback {stats['sigma_fallback']}일) ==")
    print(f"confirmed_uptrend 일수: A={stats['labels']['A']['confirmed_uptrend']} "
          f"B={stats['labels']['B']['confirmed_uptrend']} "
          f"C={stats['labels']['C']['confirmed_uptrend']} "
          f"D={stats['labels']['D']['confirmed_uptrend']}")
    print(f"룰3(FTD 무효화) 발동 일수: A={stats['rule3']['A']} B={stats['rule3']['B']} "
          f"C={stats['rule3']['C']} D={stats['rule3']['D']}")
    for pair, key in (("A→B (6→5, classic)", "trans_AB"),
                      ("A→C (churning, 6)", "trans_AC"),
                      ("A→D (churning+5)", "trans_AD")):
        total = sum(stats[key].values())
        detail = ", ".join(f"{k}:{v}" for k, v in sorted(stats[key].items())) or "-"
        promo = sum(v for k, v in stats[key].items()
                    if LABEL_RANK[k.split("->")[1]] > LABEL_RANK[k.split("->")[0]])
        print(f"{pair}: 변경 {total}일 ({total / days * 100:.2f}%) — {detail} | 승격(역방향) {promo}건")
    print(f"co-anchor 경계 (C vs A): dist≥5 일수 {stats['ge5_A']}→{stats['ge5_C']} "
          f"(+{stats['ge5_C'] - stats['ge5_A']}), dist>3 일수 {stats['gt3_A']}→{stats['gt3_C']} "
          f"(+{stats['gt3_C'] - stats['gt3_A']})")
    print(f"일 단위: classic 분배일 {stats['classic_days']}, stalling 분배일 {stats['stall_days']} "
          f"(신규 +{stats['stall_days'] / max(stats['classic_days'], 1) * 100:.1f}%), "
          f"classic 중 상단 절반 마감 {stats['classic_upper_half']}일 "
          f"(광의 해석 시 제거될 비중 {stats['classic_upper_half'] / max(stats['classic_days'], 1) * 100:.1f}%)")


def main() -> None:
    logging.basicConfig(level=logging.ERROR)   # σ 파생 info 로그 억제
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="docs/superpowers/verification/2026-07-21-issue55-dist-replay.csv")
    args = parser.parse_args()

    cfg = Config.load()
    conn = psycopg.connect(cfg.database_url, options="-c default_transaction_read_only=on")
    try:
        with open(args.csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "index_code", "date", "dist_pct", "ftd_pct",
                "dist_classic", "dist_stall",
                "status_A_classic6", "status_B_classic5", "status_C_stall6", "status_D_stall5",
                "classic_day_flag", "stall_day_flag", "classic_upper_half_flag", "last_ftd",
            ])
            for index_code, market in INDICES:
                stats = replay_index(conn, index_code, market, writer)
                summarize(stats)
    finally:
        conn.close()
    print(f"\nCSV: {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
