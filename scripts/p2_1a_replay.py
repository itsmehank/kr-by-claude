"""P2-1a verification replay — READ-ONLY.

과거 거래일에 대해 base 임계 (1.4 / -0.2) vs corrected 임계 (σ 보정) 로
market_context status 를 둘 다 계산해 CSV 출력. P2-1a 보정이 status 를
어떻게 바꾸는지 검증.

안전장치:
- read-only connection (default_transaction_read_only=on) — DB 레벨 강제.
  INSERT/UPDATE/DELETE 시도 시 ERROR. 운영 데이터 절대 안 변함.
- upsert_market_context / conn.commit() 절대 호출 안 함.
- _process_one_date 만 호출 (순수 계산 — 반환 dict only).

fwd_return_5d/10d 는 *사후 분석용* (look-ahead). status 계산 자체엔 안 들어감
(status 는 compute_korean_sigma_pct 의 WHERE date <= as_of 로 look-ahead 없음).

사용: uv run python scripts/p2_1a_replay.py > /tmp/p2_1a_replay.csv
"""
import csv
import sys
from datetime import date, timedelta

import psycopg

from kr_pipeline.common.config import Config
from kr_pipeline.common.thresholds import (
    NASDAQ_REFERENCE_SIGMA,
    FTD_PCT_BASE,
    DISTRIBUTION_PCT_BASE,
    KOREAN_SIGMA_RATIO_FLOOR,
    KOREAN_SIGMA_RATIO_CEILING,
)
from kr_pipeline.market_context.load import load_index_daily_with_sma200
from kr_pipeline.market_context.modes import _process_one_date, INDICES
from kr_pipeline.market_context.compute.volatility import (
    compute_korean_sigma_pct,
    derive_market_thresholds,
    book_default_thresholds,
)

# replay 구간 — 최근 3달 (σ 폭증 2026-03 포함). 252일 데이터 충분 (fallback 안 탐).
REPLAY_START = date(2026, 2, 21)
REPLAY_END = date(2026, 5, 21)
LOAD_START = REPLAY_START - timedelta(days=400)  # σ 252 거래일 + breadth lookback 여유

# base path override — pre-P2-1a 책 임계 (책 무보정).
BASE_OVERRIDE = {
    "ftd_pct": FTD_PCT_BASE,
    "distribution_pct": DISTRIBUTION_PCT_BASE,
    "raw_ratio": None,
    "ratio_applied": 1.0,
    "clamped": False,
    "source": "book_default",
}


def fwd_return(df, end_idx: int, n: int) -> float | None:
    """date 이후 n 거래일 지수 수익률 (%). 미래 데이터 부족 시 None.

    look-ahead — 사후 분석용. status 계산엔 안 쓰임.
    """
    if end_idx + n >= len(df):
        return None
    c0 = float(df.iloc[end_idx]["close"])
    cn = float(df.iloc[end_idx + n]["close"])
    return round((cn / c0 - 1) * 100, 2)


def main() -> int:
    cfg = Config.load()
    # READ-ONLY connection — DB 레벨 강제. 쓰기 시도 시 ERROR.
    conn = psycopg.connect(
        cfg.database_url,
        autocommit=True,
        options="-c default_transaction_read_only=on",
    )
    writer = csv.writer(sys.stdout)
    writer.writerow([
        "date", "index_code", "sigma", "raw_ratio", "ratio_applied", "clamped",
        "status_base", "status_corrected", "status_differs",
        "ftd_date_base", "ftd_date_corrected",
        "dist_count_base", "dist_count_corrected",
        "fwd_return_5d", "fwd_return_10d",
    ])
    try:
        for index_code, market in INDICES:
            df = load_index_daily_with_sma200(conn, index_code, LOAD_START, REPLAY_END)
            for i in range(len(df)):
                d = df.iloc[i]["date"]
                if hasattr(d, "date"):
                    d = d.date()
                if not (REPLAY_START <= d <= REPLAY_END):
                    continue

                res_c = _process_one_date(conn, d, index_code, market, df, thresholds_override=None)
                res_b = _process_one_date(conn, d, index_code, market, df, thresholds_override=BASE_OVERRIDE)
                if res_c is None or res_b is None:
                    continue

                # σ / ratio 정보 (corrected path 와 동일 계산 — CSV 기록용)
                sigma = compute_korean_sigma_pct(conn, index_code, as_of=d)
                if sigma is None:
                    th = book_default_thresholds(ftd_base=FTD_PCT_BASE, dist_base=DISTRIBUTION_PCT_BASE)
                else:
                    th = derive_market_thresholds(
                        sigma,
                        anchor_sigma=NASDAQ_REFERENCE_SIGMA,
                        ftd_base=FTD_PCT_BASE,
                        dist_base=DISTRIBUTION_PCT_BASE,
                        clamp_floor=KOREAN_SIGMA_RATIO_FLOOR,
                        clamp_ceiling=KOREAN_SIGMA_RATIO_CEILING,
                    )

                writer.writerow([
                    d, index_code,
                    round(sigma, 3) if sigma is not None else "",
                    round(th["raw_ratio"], 3) if th["raw_ratio"] is not None else "",
                    round(th["ratio_applied"], 3), th["clamped"],
                    res_b["current_status"], res_c["current_status"],
                    res_b["current_status"] != res_c["current_status"],
                    res_b["last_follow_through_day"], res_c["last_follow_through_day"],
                    res_b["distribution_day_count_last_25"], res_c["distribution_day_count_last_25"],
                    fwd_return(df, i, 5), fwd_return(df, i, 10),
                ])
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
