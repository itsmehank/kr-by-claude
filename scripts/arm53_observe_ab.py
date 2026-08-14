"""(#53) Arm-53 A+B 관찰 — C 재현 판정의 '방향' 확정용 look. 준거:
independent-window prereg §4(방향 재현) · §9.2 Arm-53 · 2026-08-12 설계 §7.

비보호 구간(표본 A+B, 2021~24)에서 armA-prod(현행) vs arm53 결정론 리플레이.
여기서 관측된 개선/악화 방향(final_multiple·CAGR·MDD)이 표본 C 재현 판정의
기준 방향이 된다. 부가 산출물: 국면 분포 차이(영향 범위 3분류 근사).

  uv run python scripts/arm53_observe_ab.py > data/backtest/arm53_observe_ab_<날짜>.json
"""
from __future__ import annotations

import json
import sys

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.backtest.portfolio import (
    PortfolioConfig, load_ticker_data, run_portfolio,
)
from kr_pipeline.db.connection import connect


def main() -> int:
    tickers = list(FROZEN_SAMPLE) + list(FROZEN_SAMPLE_B)
    with connect() as conn:
        data = load_ticker_data(conn, tickers)          # 기본 2021~25/watch 21~24
    rA = run_portfolio(data, PortfolioConfig(gate_mode="prod"))
    r53 = run_portfolio(data, PortfolioConfig(gate_mode="a53"))

    # 국면 분포 차이 (시장 단위 — 종목 무관, 대표 1개 시장당 1시계열)
    seen_markets: dict[str, dict] = {}
    for td in data.values():
        if td.market not in seen_markets:
            seen_markets[td.market] = {
                "cur": td.phase_by_date, "a53": td.phase_a53_by_date}
    phase_diff = {}
    for mkt, maps in seen_markets.items():
        days = sorted(set(maps["cur"]) & set(maps["a53"]))
        diff_days = [d for d in days if maps["cur"][d] != maps["a53"][d]]
        dist_cur: dict = {}
        dist_a53: dict = {}
        for d in days:
            dist_cur[maps["cur"][d]] = dist_cur.get(maps["cur"][d], 0) + 1
            dist_a53[maps["a53"][d]] = dist_a53.get(maps["a53"][d], 0) + 1
        phase_diff[mkt] = {"days": len(days), "diff_days": len(diff_days),
                           "dist_current": dist_cur, "dist_a53": dist_a53}

    mA, m53 = rA["metrics"], r53["metrics"]
    out = {
        "label": "Arm-53 A+B 관찰(look) — C 재현 판정의 방향 기준",
        "prereg": ["docs/superpowers/specs/2026-07-21-independent-window-backtest-prereg.md §4·§9.2",
                   "docs/superpowers/specs/2026-08-12-issue53-ladder-redesign.md §7"],
        "sample": "ab",
        "armA_prod_metrics": mA,
        "arm53_metrics": m53,
        "delta": {k: round(m53[k] - mA[k], 4)
                  for k in ("final_multiple", "cagr_pct", "max_drawdown_pct")
                  if k in mA and k in m53},
        "n_entries": {"armA": rA["stats"]["n_entries"],
                      "arm53": r53["stats"]["n_entries"]},
        "phase_diff": phase_diff,
        "note": "방향 판정은 사람이 이 산출물로 해석 — 여기서 개선으로 관측된 "
                "지표의 방향이 표본 C 에서 재현돼야 채택(§4).",
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
