"""#117 (P3) — #111 전환 이벤트 재정의 강건성. exploratory, 채택 근거 불가. 읽기전용.

재정의 2종: ① 종목별 첫 전환만 ② 63거래일 쿨다운.
방법은 #111 스펙 §2.2~§2.5 동일 (T+1→T+21행, 시장별 지수 대비, 클러스터 CI).
배경: 원 표본 39,357건/2,311종목 = 종목당 평균 17회 — 경계 진동 종목 가중 점검.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.backtest.minervini_forward import (
    PRIMARY_H, agg_bootstrap_ci, extract_transitions, forward_excess,
    iter_ticker_rows, load_index_closes, load_markets,
)
from kr_pipeline.backtest.phases import INDEX_OF

COOLDOWN_ROWS = 63


def _cooldown_filter(transitions: list[int], min_gap: int) -> list[int]:
    out: list[int] = []
    for i in transitions:
        if not out or i - out[-1] >= min_gap:
            out.append(i)
    return out


def _stats(vals_by_ticker: dict[str, list[float]]) -> dict:
    vals = [v for vs in vals_by_ticker.values() for v in vs]
    if not vals:
        return {"n": 0}
    agg = {t: (sum(vs), len(vs)) for t, vs in vals_by_ticker.items() if vs}
    vs_sorted = sorted(vals)
    n = len(vs_sorted)
    median = (vs_sorted[n // 2] if n % 2
              else (vs_sorted[n // 2 - 1] + vs_sorted[n // 2]) / 2)
    lo, hi = agg_bootstrap_ci(agg)
    return {"n": n, "tickers": len(agg), "mean": round(sum(vals) / n, 3),
            "median": round(median, 3), "ci95": [lo, hi]}


def main() -> int:
    from kr_pipeline.db.connection import connect
    variants: dict[str, dict[str, list[float]]] = {
        "first_only": {}, "cooldown63": {}}
    with connect() as conn:
        idx = load_index_closes(conn)
        markets = load_markets(conn)
        for ticker, rows in iter_ticker_rows(conn):
            iclose = idx.get(INDEX_OF.get(markets.get(ticker, ""), "1001"), {})
            trs = extract_transitions(rows)
            for name, sel in (("first_only", trs[:1]),
                              ("cooldown63", _cooldown_filter(trs, COOLDOWN_ROWS))):
                for i in sel:
                    x = forward_excess(rows, i, PRIMARY_H, iclose)
                    if x is not None:
                        variants[name].setdefault(ticker, []).append(x)

    out = {"issue": 117, "grade": "exploratory", "h": PRIMARY_H,
           "baseline_ref": "issue111_minervini_transition_judge_20260818.json "
                           "(h20 mean -0.337, ci [-0.621, -0.057])",
           "variants": {k: _stats(v) for k, v in variants.items()}}
    path = (f"data/backtest/exploratory_issue111_transition_robustness_"
            f"{date.today():%Y%m%d}.json")
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out["variants"], ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
