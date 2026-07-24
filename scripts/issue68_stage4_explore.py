"""(#68 4단계) 실적 필터 탐색 — 관찰 라벨, 채택 판정 아님.

준거(LOCKED): docs/superpowers/specs/2026-07-22-issue68-stage3-filter-prereg.md §4.
표본 A+B 풀링 트레이드의 진입일 기준으로 F-C1/C2/C3/S1 라벨(pass/fail/
indeterminate/turnaround)을 부여하고, 승격 판정 입력은 8 look(4필터 ×
{1차 pass-ex-turnaround, 턴어라운드 합산 민감도})으로 한정한다. q4_derived
제외 민감도·판정불가 그룹 성과·채널 구성비는 기술(descriptive) 집계 전용.

  uv run python scripts/issue68_stage4_explore.py > data/backtest/issue68_stage4_explore_20260722.json
"""
from __future__ import annotations

import json
import sys

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.backtest.refinement import build_refined_trades, cluster_bootstrap_ci
from kr_pipeline.db.connection import connect
from kr_pipeline.financials.filters import FILTERS, evaluate_filters
from kr_pipeline.financials.store import get_financials_asof

EXPLORE_SEED = 20260722          # 관찰용 CI 시드(판정 아님) — 기존 탐색과 동일
ASOF_LIMIT = 16                  # 4Q 파생 체인(2개 연도 × 4행) 가시성 여유

# 승격 기준 (LOCKED §4 — 필터별 독립, 3개 전부 충족 시 표본 C 이관)
PROMOTE_MIN_PASS_N = 25
PROMOTE_MIN_DIFF_PP = 8.0
PROMOTE_MAX_INDET_RATIO = 0.40


def stats(trades: list[dict]) -> dict:
    """기존 표본 B 분석과 동일 방법(explore_entry_phase.stats 준용)."""
    vals = [t["excess_net"] for t in trades if t.get("excess_net") is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0}
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    payoff = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) \
        if wins and losses and sum(losses) != 0 else None
    lo, hi = cluster_bootstrap_ci(trades, seed=EXPLORE_SEED)
    return {"n": n, "win_rate_pct": round(len(wins) / n * 100, 1),
            "payoff": round(payoff, 2) if payoff else None,
            "mean_excess_net": round(sum(vals) / n, 3),
            "ci95": [lo, hi], "ci_contains_zero": lo <= 0.0 <= hi}


def _win_rate(trades: list[dict]) -> float | None:
    vals = [t["excess_net"] for t in trades if t.get("excess_net") is not None]
    if not vals:
        return None
    return round(sum(v > 0 for v in vals) / len(vals) * 100, 1)


def _look(pass_grp: list[dict], fail_grp: list[dict]) -> dict:
    wp, wf = _win_rate(pass_grp), _win_rate(fail_grp)
    return {"pass": stats(pass_grp), "fail": stats(fail_grp),
            "win_diff_pp": round(wp - wf, 1) if wp is not None and wf is not None else None}


def main() -> int:
    tickers = list(FROZEN_SAMPLE) + list(FROZEN_SAMPLE_B)
    with connect() as conn:
        trades, _ = build_refined_trades(conn, tickers=tickers)
        for t in trades:
            rows = get_financials_asof(conn, t["ticker"], as_of=t["entry_date"],
                                       limit=ASOF_LIMIT)
            t["filters"] = evaluate_filters(rows)

    out = {"label": "탐색/관찰 — 채택 판정 아님 (승격 시 표본 C 사전등록 이관)",
           "prereg": "docs/superpowers/specs/2026-07-22-issue68-stage3-filter-prereg.md",
           "seed": EXPLORE_SEED, "n_trades": len(trades),
           "baseline_all": stats(trades), "filters": {}}

    for f in FILTERS:
        grp = {k: [t for t in trades if t["filters"][f]["label"] == k]
               for k in ("pass", "fail", "indeterminate", "turnaround")}
        indet_ratio = len(grp["indeterminate"]) / len(trades) if trades else 1.0
        primary = _look(grp["pass"], grp["fail"])                      # look 1
        sens_turn = _look(grp["pass"] + grp["turnaround"], grp["fail"])  # look 2
        promoted = (
            primary["pass"].get("n", 0) >= PROMOTE_MIN_PASS_N
            and primary["win_diff_pp"] is not None
            and primary["win_diff_pp"] >= PROMOTE_MIN_DIFF_PP
            and indet_ratio <= PROMOTE_MAX_INDET_RATIO)
        no_q4 = [t for t in trades
                 if "q4_derived" not in t["filters"][f]["tags"]]
        out["filters"][f] = {
            "counts": {k: len(v) for k, v in grp.items()},
            "indeterminate_ratio": round(indet_ratio, 3),
            "look_primary_pass_vs_fail": primary,
            "look_turnaround_included": sens_turn,
            "promotion": {"criteria": {"min_pass_n": PROMOTE_MIN_PASS_N,
                                       "min_diff_pp": PROMOTE_MIN_DIFF_PP,
                                       "max_indet_ratio": PROMOTE_MAX_INDET_RATIO},
                          "promoted": promoted},
            # ---- 이하 기술(descriptive) 전용 — 승격 판정 미입력 (LOCKED §4) ----
            "descriptive": {
                "indeterminate_stats": stats(grp["indeterminate"]),
                "turnaround_stats": stats(grp["turnaround"]),
                "q4_excluded_sensitivity": _look(
                    [t for t in no_q4 if t["filters"][f]["label"] == "pass"],
                    [t for t in no_q4 if t["filters"][f]["label"] == "fail"]),
                "channel_mix": {
                    tag: sum(tag in t["filters"][f]["tags"] for t in trades)
                    for tag in ("published", "eps_fallback", "q4_derived",
                                "guard_data_error", "guard_corp_action",
                                "fiscal_transition")},
            },
        }

    per_trade = [{"ticker": t["ticker"], "entry_date": t["entry_date"],
                  "excess_net": t["excess_net"],
                  "filters": t["filters"]} for t in trades]
    out["trades"] = per_trade
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
