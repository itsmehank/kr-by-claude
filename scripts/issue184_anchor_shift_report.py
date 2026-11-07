"""#184 배포 전 보고 — C3(주간 1.4×50주 평균) → C3′(B)(일봉 상승 마감일 ≥1일, 1.4×50일 평균) 앵커 이동 수 (읽기 전용).

전문가 회신(2026-11-07) 요청 (ii): "현 보유·분류 종목 중 C3′(B) 적용 시 앵커가 이동하는 종목 수".
- 보유(positions open) = 0 건(2026-11-07 실측) → 모집단은 (a) 최근 30일 분류 종목, (b) 전 상장 종목(맥락).
- as_of = daily_indicators 최신일(기본) — 앵커는 매 실행 재계산되므로 배포 직후 첫 실행이 보는 값과 같다.
- C3′(B) 정의(회신 11-07): 앵커 후보 주(C1∧C2∧C5)의 거래일 중 "종가 > 전일 종가" 인 날이 ≥1일 존재하고 그 날
  adj_volume ≥ BREAKOUT_VOL_FLOOR × avg_volume_50d(현 저장 열, 당일 포함 50일, min_periods 40). NaN 날 = 불충족.
  C1·C2·C5·left_censored(n ≤ W) 규칙은 find_anchor 와 동일하게 유지(이 스크립트는 C3 자리만 바꾼 사본).
DB 는 SELECT 만. 결과 JSON = data/verification/issue184_anchor_shift_<as_of>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from api.services.payload_builder import _fetch_weekly_full
from kr_pipeline.common.price_source import price_source
from kr_pipeline.common.thresholds import (
    BREAKOUT_VOL_FLOOR,
    CLIMAX_ANCHOR_FLAT_BAND_PCT,
    CLIMAX_ANCHOR_STAGE1_MIN_WEEKS,
    CLIMAX_ANCHOR_TURNUP_WEEKS,
    CLIMAX_ANCHOR_VOL_AVG_WEEKS,
)
from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner.compute.climax_topping import _sma, find_anchor

CLASSIFIED_DAYS = 30


def _fetch_daily_ind(conn, ticker: str, as_of: date) -> list[dict]:
    """일봉 지표 전 이력(date, adj_close, volume=adj, avg_volume_50d) 오름차순. halt 일은 volume/avg NULL."""
    src = price_source(conn, ticker)
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT date, adj_close, volume, avg_volume_50d
              FROM {src.indicators}
             WHERE ticker = %s AND date <= %s
             ORDER BY date ASC
        """, (ticker, as_of))
        rows = cur.fetchall()
    return [{"date": r[0], "close": float(r[1]) if r[1] is not None else None,
             "volume": float(r[2]) if r[2] is not None else None,
             "avg50": float(r[3]) if r[3] is not None else None} for r in rows]


def c3prime_week(daily: list[dict], week_end: date) -> tuple[bool, int]:
    """(충족 여부, 그 주 거래일 수). 주 = week_end 와 같은 ISO 주(월~)."""
    y, w, _ = week_end.isocalendar()
    ok, days = False, 0
    for k, d in enumerate(daily):
        if d["date"] > week_end:
            break
        if d["date"].isocalendar()[:2] != (y, w):
            continue
        days += 1
        prev = daily[k - 1]["close"] if k > 0 else None
        if (d["close"] is None or prev is None or d["volume"] is None or d["avg50"] is None
                or d["avg50"] <= 0):
            continue                                            # NaN = 불충족(회신 11-07)
        if d["close"] > prev and d["volume"] >= BREAKOUT_VOL_FLOOR * d["avg50"]:
            ok = True
    return ok, days


def find_anchor_c3prime(weekly: list[dict], daily: list[dict]) -> dict:
    """find_anchor 사본 — C3 자리를 c3prime_week 로 교체. 나머지(C1·C2·C5·left_censored·탐색 방향) 동일."""
    closes = [w["close"] for w in weekly]
    n = len(weekly)
    W = CLIMAX_ANCHOR_VOL_AVG_WEEKS
    if n <= W:
        return {"anchor_week": None, "left_censored": True, "no_transition": False, "weeks_since": None}
    k, s1 = CLIMAX_ANCHOR_TURNUP_WEEKS, CLIMAX_ANCHOR_STAGE1_MIN_WEEKS
    for i in range(n - 1, W - 1, -1):
        s30, s40 = _sma(closes, i, 30), _sma(closes, i, 40)
        if None in (s30, s40):
            continue
        stage1 = all((sm := _sma(closes, j, 40)) is not None and closes[j] < sm for j in range(i - s1, i))
        prev_s40, prev_s40k = _sma(closes, i - 1, 40), _sma(closes, i - 1 - k, 40)
        slope_ok = (prev_s40 and prev_s40k
                    and (prev_s40 - prev_s40k) / prev_s40k * 100 <= CLIMAX_ANCHOR_FLAT_BAND_PCT)
        if not (stage1 and slope_ok and closes[i] > s30 and closes[i] > s40):
            continue
        we = date.fromisoformat(weekly[i]["week_end"])
        ok, _ = c3prime_week(daily, we)
        if ok:
            return {"anchor_week": weekly[i]["week_end"], "left_censored": False,
                    "no_transition": False, "weeks_since": n - 1 - i}
    return {"anchor_week": None, "left_censored": False, "no_transition": True, "weeks_since": None}


def _mode(a: dict) -> str:
    return "left_censored" if a["left_censored"] else "no_transition" if a["no_transition"] else "anchored"


def classify_shift(old: dict, new: dict) -> str:
    mo, mn = _mode(old), _mode(new)
    if mo == "left_censored":
        return "left_censored"
    if mo == mn == "anchored":
        if old["anchor_week"] == new["anchor_week"]:
            return "same"
        return "moved_later" if new["anchor_week"] > old["anchor_week"] else "moved_earlier"
    if mo == "anchored" and mn == "no_transition":
        return "lost"
    if mo == "no_transition" and mn == "anchored":
        return "gained"
    return "none_both"


def run(conn, tickers: list[str], as_of: date, label: str) -> dict:
    shifts: Counter = Counter()
    delta_weeks: Counter = Counter()
    detail = []
    for t in tickers:
        weekly = _fetch_weekly_full(conn, t, as_of)
        daily = _fetch_daily_ind(conn, t, as_of)
        old, new = find_anchor(weekly), find_anchor_c3prime(weekly, daily)
        s = classify_shift(old, new)
        shifts[s] += 1
        if s in ("moved_later", "moved_earlier"):
            delta_weeks[new["weeks_since"] - old["weeks_since"]] += 1
        if s != "same":
            detail.append({"ticker": t, "shift": s, "old": old["anchor_week"], "new": new["anchor_week"],
                           "old_weeks_since": old["weeks_since"], "new_weeks_since": new["weeks_since"]})
    moved = sum(v for k, v in shifts.items() if k in ("moved_later", "moved_earlier", "gained", "lost"))
    return {"population": label, "as_of": as_of.isoformat(), "tickers": len(tickers),
            "shift": dict(shifts), "anchor_changed": moved,
            "anchor_changed_ratio": round(moved / len(tickers), 4) if tickers else None,
            "moved_delta_weeks(new-old)": {str(k): v for k, v in sorted(delta_weeks.items())},
            "detail": sorted(detail, key=lambda d: (d["shift"], d["ticker"]))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", type=date.fromisoformat, default=None)
    ap.add_argument("--skip-universe", action="store_true")
    args = ap.parse_args()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT max(date) FROM daily_indicators")
            as_of = args.as_of or cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM positions WHERE status = 'open'")
            open_positions = cur.fetchone()[0]
            cur.execute("""SELECT DISTINCT symbol FROM weekly_classification
                            WHERE analyzed_for_date >= %s - %s ORDER BY symbol""", (as_of, CLASSIFIED_DAYS))
            classified = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT ticker FROM daily_prices WHERE date = (SELECT max(date) FROM daily_prices) ORDER BY ticker")
            universe = [r[0] for r in cur.fetchall()]
        out = {"issue": 184, "generated_for": "expert report (ii), 회신 2026-11-07",
               "rule": {"old": "C3 weekly vol ≥ BREAKOUT_VOL_FLOOR × mean(prev 50 weeks)",
                        "new": "C3′(B) ≥1 up-close day in week with adj_volume ≥ BREAKOUT_VOL_FLOOR × avg_volume_50d (NaN=unmet)"},
               "open_positions": open_positions,
               "populations": [run(conn, classified, as_of, f"weekly_classification distinct symbols, last {CLASSIFIED_DAYS} days")]}
        if not args.skip_universe:
            out["populations"].append(run(conn, universe, as_of, "all live tickers at latest daily date"))
    path = Path(f"data/verification/issue184_anchor_shift_{as_of.isoformat()}.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for p in out["populations"]:
        print(f"[{p['population']}] as_of={p['as_of']} n={p['tickers']} changed={p['anchor_changed']} "
              f"({p['anchor_changed_ratio']}) shift={p['shift']} delta={p['moved_delta_weeks(new-old)']}")
    print(f"open_positions={open_positions} → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
