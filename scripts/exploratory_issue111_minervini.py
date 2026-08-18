"""#111 탐색 부속 ①~⑤ (스펙 §4) — exploratory, 채택 근거 불가. 읽기전용.

① 통과일 풀링 vs 미통과 ② 조건 개수 계단 ③ 국면 분해 ④ 모멘텀 교락(5분위)
⑤ 시간(월) 클러스터 강건성.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.backtest import phases as ph
from kr_pipeline.backtest.minervini_forward import (
    PRIMARY_H, agg_bootstrap_ci, extract_transitions, forward_excess,
    iter_ticker_rows, load_index_closes, load_markets, verdict_of,
)
from kr_pipeline.db.connection import connect


def _add(agg: dict, key, x: float) -> None:
    s, c = agg.get(key, (0.0, 0))
    agg[key] = (s + x, c + 1)


def _group_mean(agg: dict) -> dict:
    return {str(k): {"n": c, "mean": round(s / c, 3)}
            for k, (s, c) in sorted(agg.items()) if c}


def main() -> int:
    pooled: dict[bool, dict] = {True: {}, False: {}}  # label→ticker→(합, 개수)
    stair: dict[int, tuple[float, int]] = {}
    by_phase: dict[str, tuple[float, int]] = {}
    by_month: dict[str, tuple[float, int]] = {}
    mom: list[tuple[float, float]] = []               # (전환 전 20행 수익, 초과수익)

    with connect() as conn:
        idx = load_index_closes(conn)
        markets = load_markets(conn)
        pmaps = {c: ph.load_phase_map(conn, c) for c in ("1001", "2001")}
        for ticker, rows in iter_ticker_rows(conn):
            code = ph.INDEX_OF.get(markets.get(ticker), "1001")
            iclose = idx.get(code, {})
            for i in range(len(rows)):                # ①② 모든 행
                x = forward_excess(rows, i, PRIMARY_H, iclose)
                if x is None:
                    continue
                if rows[i][2] is not None:
                    _add(pooled[rows[i][2]], ticker, x)
                if rows[i][3] is not None:
                    _add(stair, rows[i][3], x)
            for i in extract_transitions(rows):       # ③④⑤ 전환 이벤트
                x = forward_excess(rows, i, PRIMARY_H, iclose)
                if x is None:
                    continue
                d = rows[i][0]
                _add(by_phase, ph.phase_at(pmaps[code], d) or "unknown", x)
                _add(by_month, d.strftime("%Y-%m"), x)
                if i >= PRIMARY_H:
                    mom.append(((rows[i][1] / rows[i - PRIMARY_H][1] - 1) * 100, x))

    out: dict = {"issue": 111, "grade": "exploratory", "h": PRIMARY_H}
    pol: dict = {}
    for label, agg in pooled.items():                 # ①
        n = sum(c for _, c in agg.values())
        lo, hi = agg_bootstrap_ci(agg)
        pol["pass" if label else "fail"] = {
            "n": n, "tickers": len(agg),
            "mean": round(sum(s for s, _ in agg.values()) / n, 3), "ci95": [lo, hi]}
    pol["mean_diff"] = round(pol["pass"]["mean"] - pol["fail"]["mean"], 3)
    out["pooled"] = pol
    out["staircase"] = _group_mean(stair)             # ②
    out["by_phase"] = _group_mean(by_phase)           # ③
    mom.sort()                                        # ④ 5분위
    k = len(mom) // 5
    out["momentum_quintiles"] = [
        {"q": q + 1, "n": len(seg),
         "prior_mean": round(sum(p for p, _ in seg) / len(seg), 2),
         "excess_mean": round(sum(x for _, x in seg) / len(seg), 3)}
        for q in range(5)
        for seg in [mom[q * k:(q + 1) * k] if q < 4 else mom[4 * k:]]]
    lo, hi = agg_bootstrap_ci(by_month)               # ⑤
    out["month_cluster"] = {"months": len(by_month), "ci95": [lo, hi],
                            "verdict_sensitivity": verdict_of(lo, hi)}

    path = f"data/backtest/exploratory_issue111_minervini_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out["pooled"], ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
