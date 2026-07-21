"""P4 진입 프리미엄 구간 분석 — prereg 2026-07-21 §2 P4. 읽기전용·결정론.

입력 = run_portfolio 결과 stats["exits"] (premium_pct·reason·pnl_pct).
stopout 판정 reason 은 STOPOUT_REASON 상수로 잠금 (portfolio.py:158 실측 "stop8").
"""
from __future__ import annotations

STOPOUT_REASON = "stop8"
GAP_PROMOTE_PP = 20.0           # prereg P4: 격차 ≥ 20%p → 채택 후보 승격
_BINS = (("0-1", 0.0, 1.0), ("1-3", 1.0, 3.0), ("3-5", 3.0, 5.0))


def premium_bins(exits: list[dict], *, min_n_high: int = 8) -> dict:
    bins: dict[str, list[dict]] = {k: [] for k, _, _ in _BINS}
    for e in exits:
        p = e.get("premium_pct")
        if p is None:
            continue
        for key, lo, hi in _BINS:
            if lo <= p < hi or (key == "3-5" and p == hi):
                bins[key].append(e)
                break

    def _stat(rows: list[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {"n": 0, "stopout_rate": None, "mean_pnl": None}
        so = sum(1 for r in rows if r.get("reason") == STOPOUT_REASON)
        return {"n": n, "stopout_rate": round(so / n * 100, 1),
                "mean_pnl": round(sum(r["pnl_pct"] for r in rows) / n, 2)}

    out_bins = {k: _stat(v) for k, v in bins.items()}
    low_rows = bins["0-1"] + bins["1-3"]
    low, high = _stat(low_rows), out_bins["3-5"]
    if high["n"] < min_n_high:
        verdict, gap = "insufficient_n", None
    else:
        gap = round(high["stopout_rate"] - (low["stopout_rate"] or 0.0), 1)
        verdict = "promote" if gap >= GAP_PROMOTE_PP else "hold"
    return {"bins": out_bins,
            "p4": {"high_n": high["n"], "low_stopout": low["stopout_rate"],
                   "high_stopout": high["stopout_rate"], "gap_pp": gap,
                   "verdict": verdict}}
