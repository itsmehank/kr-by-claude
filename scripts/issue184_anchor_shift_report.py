"""#184 배포 전/후 보고 — C3(구, 주간 1.4×50주 평균) → C3′(B)(일봉 상승 마감일 ≥1일, 1.4×50일 평균) 앵커 이동 수 (읽기 전용).

전문가 회신(2026-11-07) 요청 (ii): "현 보유·분류 종목 중 C3′(B) 적용 시 앵커가 이동하는 종목 수". 배포 후에는 같은 집계를
관측(spec 2026-11-07 §7-3: lost 셀 0 유지 여부)에 쓴다.
- 보유(positions open) = 0 건(2026-11-07 실측) → 모집단은 (a) 최근 30일 분류 종목, (b) 전 상장 종목(맥락).
- as_of = daily_indicators 최신일(기본) — 앵커는 매 실행 재계산되므로 배포 직후 첫 실행이 보는 값과 같다.
- 신 규칙 = 본체 `climax_topping.find_anchor(weekly, daily)`(C3′, #184 구현) 를 그대로 호출. 일봉 = `_fetch_daily_anchor_series`.
- 구 규칙 = 아래 `find_anchor_legacy_c3`(#184 이전 본체의 동결 사본 — **관측 전용**, 본체는 C3′).
DB 는 SELECT 만. 결과 JSON = data/verification/issue184_anchor_shift_<as_of>.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from api.services.payload_builder import _fetch_daily_anchor_series, _fetch_weekly_full
from kr_pipeline.common.thresholds import (
    ANCHOR_MIN_HISTORY_WEEKS,
    BREAKOUT_VOL_FLOOR,
    CLIMAX_ANCHOR_FLAT_BAND_PCT,
    CLIMAX_ANCHOR_STAGE1_MIN_WEEKS,
    CLIMAX_ANCHOR_TURNUP_WEEKS,
)
from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner.compute.climax_topping import _sma, find_anchor

CLASSIFIED_DAYS = 30


def find_anchor_legacy_c3(weekly: list[dict]) -> dict:
    """#184 이전 find_anchor 의 동결 사본(C3 = 주간 volume ≥ BREAKOUT_VOL_FLOOR × 직전 50주 평균, 결측 주 0). 관측 전용."""
    closes = [w["close"] for w in weekly]
    vols = [w["volume"] or 0 for w in weekly]
    n = len(weekly)
    W = ANCHOR_MIN_HISTORY_WEEKS
    if n <= W:
        return {"anchor_week": None, "left_censored": True, "no_transition": False, "weeks_since": None}
    k, s1 = CLIMAX_ANCHOR_TURNUP_WEEKS, CLIMAX_ANCHOR_STAGE1_MIN_WEEKS
    for i in range(n - 1, W - 1, -1):
        s30, s40 = _sma(closes, i, 30), _sma(closes, i, 40)
        v_avg = sum(vols[i - W:i]) / W
        if None in (s30, s40) or v_avg <= 0:
            continue
        stage1 = all((sm := _sma(closes, j, 40)) is not None and closes[j] < sm for j in range(i - s1, i))
        prev_s40, prev_s40k = _sma(closes, i - 1, 40), _sma(closes, i - 1 - k, 40)
        slope_ok = (prev_s40 and prev_s40k
                    and (prev_s40 - prev_s40k) / prev_s40k * 100 <= CLIMAX_ANCHOR_FLAT_BAND_PCT)
        if (stage1 and slope_ok and vols[i] >= BREAKOUT_VOL_FLOOR * v_avg
                and closes[i] > s30 and closes[i] > s40):
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
        old, new = find_anchor_legacy_c3(weekly), find_anchor(weekly, _fetch_daily_anchor_series(conn, t, as_of))
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
               "rule": {"old": "C3 weekly vol ≥ BREAKOUT_VOL_FLOOR × mean(prev 50 weeks) (legacy copy, pre-#184)",
                        "new": "C3′(B) ≥1 up-close day in week with adj_volume ≥ BREAKOUT_VOL_FLOOR × avg_volume_50d (NaN=unmet) — climax_topping.find_anchor"},
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
