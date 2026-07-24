"""(#68 F-S2) A+B 관찰 — look #9. 준거(LOCKED): 2026-07-24-issue68-fs2-prereg.md §3.

승격 기준 = pass(ex-turnaround) n ≥ 25 · 승률차 ≥ +8.0%p · 판정불가 ≤ 40%.
미달 시 트랙 종결(추가 변형 재등록 금지). as-of limit 20(§5 구현 노트).

  uv run python scripts/issue68_fs2_observe.py > data/backtest/issue68_fs2_observe_20260724.json
"""
from __future__ import annotations

import json
import sys

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.db.connection import connect
from kr_pipeline.backtest.refinement import build_refined_trades
from kr_pipeline.financials.filters import evaluate_fs2
from kr_pipeline.financials.store import get_financials_asof
from scripts.issue68_stage4_explore import (
    PROMOTE_MAX_INDET_RATIO, PROMOTE_MIN_DIFF_PP, PROMOTE_MIN_PASS_N,
    _look, stats,
)

ASOF_LIMIT = 20


def main() -> int:
    tickers = list(FROZEN_SAMPLE) + list(FROZEN_SAMPLE_B)
    with connect() as conn:
        trades, _ = build_refined_trades(conn, tickers=tickers)
        for t in trades:
            rows = get_financials_asof(conn, t["ticker"], as_of=t["entry_date"],
                                       limit=ASOF_LIMIT)
            t["fs2"] = evaluate_fs2(rows)

    grp = {k: [t for t in trades if t["fs2"]["label"] == k]
           for k in ("pass", "fail", "indeterminate", "turnaround")}
    indet_ratio = len(grp["indeterminate"]) / len(trades)
    primary = _look(grp["pass"], grp["fail"])
    promoted = (primary["pass"].get("n", 0) >= PROMOTE_MIN_PASS_N
                and primary["win_diff_pp"] is not None
                and primary["win_diff_pp"] >= PROMOTE_MIN_DIFF_PP
                and indet_ratio <= PROMOTE_MAX_INDET_RATIO)
    accel_only = [t for t in grp["pass"] if "accel_branch" in t["fs2"]["tags"]]
    out = {
        "label": "F-S2 A+B 관찰 (look #9) — 승격 시에만 표본 C 판정 이관",
        "prereg": "docs/superpowers/specs/2026-07-24-issue68-fs2-prereg.md",
        "n_trades": len(trades),
        "counts": {k: len(v) for k, v in grp.items()},
        "indeterminate_ratio": round(indet_ratio, 3),
        "look_primary_pass_vs_fail": primary,
        "look_turnaround_included": _look(grp["pass"] + grp["turnaround"],
                                          grp["fail"]),
        "promotion": {"criteria": {"min_pass_n": PROMOTE_MIN_PASS_N,
                                   "min_diff_pp": PROMOTE_MIN_DIFF_PP,
                                   "max_indet_ratio": PROMOTE_MAX_INDET_RATIO},
                      "promoted": promoted},
        "descriptive": {"accel_branch_only_pass": stats(accel_only),
                        "accel_branch_pass_n": len(accel_only),
                        "indeterminate_stats": stats(grp["indeterminate"])},
        "trades": [{"ticker": t["ticker"], "entry_date": t["entry_date"],
                    "excess_net": t["excess_net"], "fs2": t["fs2"]}
                   for t in trades],
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
