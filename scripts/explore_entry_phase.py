"""탐색(관찰 라벨 — 채택 판정 아님): ① 진입 변형 ② confirmed_uptrend 한정.

표본 A·B × entry_mode 3종을 결정론 재계산하고, 각 트레이드 셋에 대해
전체/confirmed_uptrend-한정 두 슬라이스의 승률·손익비·초과수익 CI 를 출력한다.
결과는 표본 C(#52) 사전등록 가설 후보용 관찰 수치.

  uv run python scripts/explore_entry_phase.py > data/backtest/exploration_entry_phase_20260722.json
"""
from __future__ import annotations

import json

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.backtest.refinement import build_refined_trades, cluster_bootstrap_ci
from kr_pipeline.db.connection import connect

EXPLORE_SEED = 20260722          # 관찰용 CI 시드(판정 아님)
ENTRY_MODES = ("breakout", "next_day_confirm", "pullback")
SAMPLES = {"A": list(FROZEN_SAMPLE), "B": list(FROZEN_SAMPLE_B)}


def stats(trades: list[dict]) -> dict:
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


def main() -> int:
    out = {"label": "탐색/관찰 — 채택 판정 아님 (표본 C 사전등록 가설 후보용)",
           "seed": EXPLORE_SEED, "results": {}}
    cache: dict[tuple, list] = {}
    with connect() as conn:
        for sname, tickers in SAMPLES.items():
            for mode in ENTRY_MODES:
                trades, _ = build_refined_trades(conn, tickers=tickers, entry_mode=mode)
                cache[(sname, mode)] = trades
                out["results"][f"{sname}/{mode}"] = {
                    "all": stats(trades),
                    "confirmed_uptrend_only": stats(
                        [t for t in trades if t.get("phase") == "confirmed_uptrend"]),
                }
    for mode in ENTRY_MODES:                    # 풀링은 캐시 재사용(재시뮬 없음)
        pooled = cache[("A", mode)] + cache[("B", mode)]
        out["results"][f"AB/{mode}"] = {
            "all": stats(pooled),
            "confirmed_uptrend_only": stats(
                [t for t in pooled if t.get("phase") == "confirmed_uptrend"]),
        }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
