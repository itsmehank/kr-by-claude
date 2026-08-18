"""#116 P2-1·P2-2 — 수익성 트랙 해석 보강 (저장본 분석, 백테스트 재실행 없음).

P2-1(보강·비판정): 표본 A/B/C 각각의 트레이드 분포로 MDE(최소 검출 가능 효과)
산출 — 종목 클러스터 부트스트랩 SE 기반, MDE80 = (z0.975+z0.80)×SE = 2.8016×SE,
MDE50 = 1.96×SE. 목적: 기존 "미입증" 3회가 엣지 부재인지 검정력 부족인지 구분.

P2-2(탐색): 기대값 분해 — 승률/평균이익/평균손실/Expectancy(PWT×AG−PLT×AL,
TTLC §4)/이익·손실 평균 보유기간/상위 10% 트레이드 총손익 기여. 표본별+통합.

트레이드 = build_refined_trades 결정론 재구성(기존 판정과 동일 방법·윈도).
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from datetime import date

import kr_pipeline.backtest.frozen_sample_c as fc
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.backtest.refinement import build_refined_trades
from kr_pipeline.db.connection import connect

SEED = 20260721
BOOT_B = 10_000
Z975, Z80 = 1.9600, 0.8416


def cluster_boot_stats(trades: list[dict], key: str = "excess_net") -> dict:
    """종목 클러스터 부트스트랩 — mean 분포의 SE·95% CI (관례 rng 시퀀스)."""
    by_ticker: dict[str, list[float]] = {}
    for t in trades:
        if t.get(key) is not None:
            by_ticker.setdefault(t["ticker"], []).append(t[key])
    tickers = sorted(by_ticker)
    rng = random.Random(SEED)
    means: list[float] = []
    for _ in range(BOOT_B):
        vals: list[float] = []
        for _ in range(len(tickers)):
            vals.extend(by_ticker[rng.choice(tickers)])
        means.append(sum(vals) / len(vals))
    means.sort()
    se = statistics.pstdev(means)
    return {"se": round(se, 3),
            "ci95": [round(means[int(0.025 * BOOT_B)], 3),
                     round(means[min(int(0.975 * BOOT_B), BOOT_B - 1)], 3)],
            "mde80": round((Z975 + Z80) * se, 3),
            "mde50": round(Z975 * se, 3)}


def decompose(trades: list[dict], key: str) -> dict:
    vals = [(t[key], t["hold_days"]) for t in trades if t.get(key) is not None]
    if not vals:
        return {"n": 0}
    wins = [(v, h) for v, h in vals if v > 0]
    losses = [(v, h) for v, h in vals if v < 0]
    n = len(vals)
    pwt = len(wins) / n
    ag = sum(v for v, _ in wins) / len(wins) if wins else 0.0
    al = abs(sum(v for v, _ in losses) / len(losses)) if losses else 0.0
    total = sum(v for v, _ in vals)
    top = sorted((v for v, _ in vals), reverse=True)[:max(1, round(n * 0.1))]
    return {
        "n": n, "win_rate": round(pwt, 3),
        "avg_gain": round(ag, 2), "avg_loss": round(al, 2),
        "payoff_ratio": round(ag / al, 2) if al else None,
        "expectancy": round(pwt * ag - (1 - pwt) * al, 3),
        "mean": round(total / n, 3),
        "hold_days_winners": round(sum(h for _, h in wins) / len(wins), 1) if wins else None,
        "hold_days_losers": round(sum(h for _, h in losses) / len(losses), 1) if losses else None,
        "top10_sum": round(sum(top), 2), "total_sum": round(total, 2),
        "top10_count": len(top),
    }


def main() -> int:
    with connect() as conn:
        samples = {
            "A": build_refined_trades(conn, tickers=list(FROZEN_SAMPLE))[0],
            "B": build_refined_trades(conn, tickers=list(FROZEN_SAMPLE_B))[0],
            "C": build_refined_trades(
                conn, tickers=list(fc.FROZEN_SAMPLE_C),
                watch_start=date(2017, 7, 1), watch_end=date(2020, 12, 31),
                px_start=date(2017, 1, 1), px_end=date(2021, 6, 30))[0],
        }

    mde = {"issue": 116, "part": "P2-1", "grade": "supplementary_non_judgment",
           "seed": SEED, "b": BOOT_B,
           "method": "cluster bootstrap SE; MDE80=(1.96+0.8416)*SE, MDE50=1.96*SE",
           "samples": {}}
    for name, trades in samples.items():
        vals = [t["excess_net"] for t in trades if t.get("excess_net") is not None]
        st = cluster_boot_stats(trades)
        mde["samples"][name] = {
            "n_trades": len(vals), "tickers": len({t["ticker"] for t in trades}),
            "mean_excess_net": round(sum(vals) / len(vals), 3), **st}

    dec = {"issue": 116, "part": "P2-2", "grade": "exploratory", "samples": {}}
    pooled: list[dict] = []
    for name, trades in samples.items():
        pooled.extend(trades)
        dec["samples"][name] = {"excess_net": decompose(trades, "excess_net"),
                                "pnl_net": decompose(trades, "pnl_net")}
    dec["pooled"] = {"excess_net": decompose(pooled, "excess_net"),
                     "pnl_net": decompose(pooled, "pnl_net")}

    d = f"{date.today():%Y%m%d}"
    p1 = f"data/backtest/issue116_mde_{d}.json"
    p2 = f"data/backtest/exploratory_issue116_expectancy_{d}.json"
    with open(p1, "w") as f:
        json.dump(mde, f, ensure_ascii=False, indent=2)
    with open(p2, "w") as f:
        json.dump(dec, f, ensure_ascii=False, indent=2)
    print(json.dumps(mde["samples"], ensure_ascii=False))
    print(json.dumps(dec["pooled"]["excess_net"], ensure_ascii=False))
    print("saved:", p1, p2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
