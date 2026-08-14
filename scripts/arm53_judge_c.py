"""(#53) Arm-53 표본 C 재현 판정 — 독립 구간 1회 개봉의 포트폴리오층. 준거:
independent-window prereg §4·§9.2 · 2026-08-12 설계 §7 · A+B 관찰
(data/backtest/arm53_observe_ab_20260814.json — 방향 기준).

⚠️ 1회 실행 → 저장 → 해석. 재실행 비교 금지(멱등 재현만 허용 — 결정론).
판정: (i) 방향 재현 = A+B 에서 개선으로 관측된 final_multiple·CAGR 델타가
표본 C 에서도 양(+) AND (ii) 가드레일 = Arm-53 MDD 가 Arm A 대비 5pp 초과
악화하지 않음.

  uv run python scripts/arm53_judge_c.py > data/backtest/arm53_judge_c_<날짜>.json
"""
from __future__ import annotations

import json
import sys
from datetime import date

import kr_pipeline.backtest.frozen_sample_c as fc
from kr_pipeline.backtest.portfolio import (
    PortfolioConfig, load_ticker_data, run_portfolio,
)
from kr_pipeline.db.connection import connect

START_C, END_C = date(2017, 1, 1), date(2021, 6, 30)
WATCH_START_C, WATCH_END_C = date(2017, 7, 1), date(2020, 12, 31)


def main() -> int:
    tickers = list(fc.FROZEN_SAMPLE_C)
    with connect() as conn:
        data = load_ticker_data(conn, tickers, start=START_C, end=END_C,
                                watch_start=WATCH_START_C,
                                watch_end=WATCH_END_C)
    rA = run_portfolio(data, PortfolioConfig(gate_mode="prod",
                                             start=START_C, end=END_C))
    r53 = run_portfolio(data, PortfolioConfig(gate_mode="a53",
                                              start=START_C, end=END_C))
    mA, m53 = rA["metrics"], r53["metrics"]
    delta = {k: round(m53[k] - mA[k], 4)
             for k in ("final_multiple", "cagr_pct", "max_drawdown_pct")}
    direction_reproduced = (delta["final_multiple"] > 0
                            and delta["cagr_pct"] > 0)
    guardrail_ok = m53["max_drawdown_pct"] >= mA["max_drawdown_pct"] - 5.0
    out = {
        "label": "Arm-53 표본 C 재현 판정 (독립 구간 1회 개봉 — 포트폴리오층)",
        "window": {"px": [str(START_C), str(END_C)],
                   "watch": [str(WATCH_START_C), str(WATCH_END_C)]},
        "observed_direction_ab": {"final_multiple": +0.1126, "cagr_pct": +2.38,
                                  "mdd_pct": +0.87,
                                  "source": "arm53_observe_ab_20260814.json"},
        "armA_prod_metrics": mA,
        "arm53_metrics": m53,
        "delta_c": delta,
        "n_entries": {"armA": rA["stats"]["n_entries"],
                      "arm53": r53["stats"]["n_entries"]},
        "criteria": {"i_direction_reproduced": direction_reproduced,
                     "ii_mdd_guardrail_le_5pp": guardrail_ok},
        "verdict_adoption_candidate": direction_reproduced and guardrail_ok,
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
