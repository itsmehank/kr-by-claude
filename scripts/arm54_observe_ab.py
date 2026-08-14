"""(#54) Arm-54 A+B 관찰 — 판정 2단 구조의 1단(look). 준거(LOCKED):
2026-08-14-issue54-pilot-path.md §4 · independent-window prereg §9.2.

비보호 구간(표본 A+B, 2021~24)에서 arm53 vs arm53-pilot54 결정론 리플레이.
관찰 통과 기준(봉인): (i) 파일럿 한정 mean excess_net > 0 AND
(ii) arm53-pilot54 의 final_multiple 이 arm53 대비 악화하지 않음.
미통과 시 Arm-54 는 표본 C 개봉 없이 기각.

  uv run python scripts/arm54_observe_ab.py > data/backtest/arm54_observe_ab_<날짜>.json
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.backtest.portfolio import (
    END, START, PortfolioConfig, load_ticker_data, run_portfolio,
)
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.backtest.refinement import cost_pct
from kr_pipeline.backtest.trigger_sim import load_index_series
from kr_pipeline.db.connection import connect


def _index_pct(idx: dict, d0: date, d1: date) -> float | None:
    """진입~청산 지수 수익률 %. 정확 일자 우선, 없으면 직전 거래일 폴백."""
    def _at(d: date) -> float | None:
        if d in idx:
            return idx[d]
        prior = [k for k in idx if k <= d]
        return idx[max(prior)] if prior else None
    a, b = _at(d0), _at(d1)
    if a is None or b is None or a == 0:
        return None
    return (b / a - 1) * 100


def main() -> int:
    tickers = list(FROZEN_SAMPLE) + list(FROZEN_SAMPLE_B)
    with connect() as conn:
        data = load_ticker_data(conn, tickers)          # 기본 2021~25/watch 21~24
        idx = {m: load_index_series(conn, m, START, END)
               for m in ("KOSPI", "KOSDAQ")}
        r53 = run_portfolio(data, PortfolioConfig(gate_mode="a53"))
        r54 = run_portfolio(data, PortfolioConfig(gate_mode="a53",
                                                  pilot54_mode=True))

    pilots = [e for e in r54["stats"]["exits"] if e["entry_kind"] == "pilot"]
    pilot_rows = []
    for e in pilots:
        mkt = data[e["ticker"]].market
        ipct = _index_pct(idx[mkt], date.fromisoformat(e["t1_date"]),
                          date.fromisoformat(e["date"]))
        excess_net = (None if ipct is None else
                      round(e["pnl_pct"] - cost_pct(date.fromisoformat(e["date"]))
                            - ipct, 2))
        pilot_rows.append({**{k: e[k] for k in ("ticker", "t1_date", "date",
                                                "reason", "pnl_pct", "episode")},
                           "excess_net": excess_net})

    valid = [p["excess_net"] for p in pilot_rows if p["excess_net"] is not None]
    mean_excess = round(sum(valid) / len(valid), 3) if valid else None
    fm53 = r53["metrics"]["final_multiple"]
    fm54 = r54["metrics"]["final_multiple"]
    crit_i = bool(valid) and mean_excess is not None and mean_excess > 0
    crit_ii = fm54 >= fm53
    out = {
        "label": "Arm-54 A+B 관찰(look) — 통과 시에만 표본 C 재현 판정 이관",
        "prereg": ["docs/superpowers/specs/2026-08-14-issue54-pilot-path.md §4",
                   "docs/superpowers/specs/2026-07-21-independent-window-backtest-prereg.md §9.2"],
        "sample": "ab", "window": {"start": str(START), "end": str(END)},
        "arm53_metrics": r53["metrics"],
        "arm53_pilot54_metrics": r54["metrics"],
        "pilot_n": len(pilots),
        "pilot_wins": len([p for p in pilot_rows if p["pnl_pct"] > 0]),
        "pilot_mean_excess_net": mean_excess,
        "pilot54_stats": {k: v for k, v in r54["stats"].items()
                          if k.startswith(("n_skipped_pilot", "pilot54"))},
        "criteria": {
            "i_pilot_mean_excess_net_gt_0": crit_i,
            "ii_final_multiple_not_worse": crit_ii,
            "final_multiple": {"arm53": fm53, "arm53_pilot54": fm54},
        },
        "observation_passed": crit_i and crit_ii,
        "pilot_trades": pilot_rows,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
