"""(#52) 표본 C 수익성 통계 — prereg §3-③ 완결분 (2026-08-14 개봉의 일부).

전체·국면별 mean excess_net(비용 차감) + 종목 클러스터 부트스트랩 95% CI
(B=10,000, seed=20260721 — refinement §2.5 동일 방법). §4 보고 규율:
CI 가 0 포함이면 "시장 초과 미입증". 확증 등급(개봉 승인 범위 내 산출).
"""
from __future__ import annotations

import json
import sys
from datetime import date

import kr_pipeline.backtest.frozen_sample_c as fc
from kr_pipeline.backtest.refinement import build_refined_trades, cluster_bootstrap_ci
from kr_pipeline.db.connection import connect

SEED = 20260721


def stats(trades):
    vals = [t["excess_net"] for t in trades if t["excess_net"] is not None]
    n = len(vals)
    if not n:
        return {"n": 0}
    lo, hi = cluster_bootstrap_ci(trades, seed=SEED)
    return {"n": n, "mean_excess_net": round(sum(vals) / n, 3),
            "ci95": [lo, hi], "ci_contains_zero": lo <= 0 <= hi,
            "win_rate": round(len([v for v in vals if v > 0]) / n, 3)}


def main() -> int:
    with connect() as conn:
        trades, promotions = build_refined_trades(
            conn, tickers=list(fc.FROZEN_SAMPLE_C),
            watch_start=date(2017, 7, 1), watch_end=date(2020, 12, 31),
            px_start=date(2017, 1, 1), px_end=date(2021, 6, 30))
    overall = stats(trades)
    by_phase = {}
    for t in trades:
        by_phase.setdefault(t["phase"], []).append(t)
    out = {
        "label": "표본 C 수익성 통계 (prereg §3-③ — 2026-08-14 개봉 완결분, 확증 등급)",
        "seed": SEED, "n_trades": len(trades), "promotions": promotions,
        "overall": overall,
        "by_phase": {p: stats(v) for p, v in sorted(by_phase.items())},
        "verdict_s4": ("시장 초과 미입증 (CI 0 포함)" if overall.get("ci_contains_zero")
                       else "CI 0 비포함 — §4 문언 기준 초과 성립"),
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
