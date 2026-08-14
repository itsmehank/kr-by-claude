"""[탐색적] Arm-53 표본 C 손익 분해 — 어디서 나빠졌나. (§0 탐색 조항 하 실행)

결정론 리플레이로 판정 실행(arm53_judge_c_20260814.json)과 동일한 계산을 재현,
요약 지표 완전 일치를 검증한 뒤에만 상세 분해를 산출한다(멱등 재현 증명).
분해 축: ① 공통 진입 vs arm53 단독 진입 ② 진입 연도별 ③ 진입 시점 국면별.
이 산출물은 '탐색' 등급 — 채택 근거로 사용 금지, 다음 설계의 재료.
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
WS, WE = date(2017, 7, 1), date(2020, 12, 31)


def agg(exits):
    n = len(exits)
    if not n:
        return {"n": 0}
    pnl = [e["pnl_pct"] for e in exits]
    return {"n": n, "sum_pnl_pct": round(sum(pnl), 2),
            "mean_pnl_pct": round(sum(pnl) / n, 2),
            "win_rate": round(len([p for p in pnl if p > 0]) / n, 3)}


def main() -> int:
    saved = json.load(open("data/backtest/arm53_judge_c_20260814.json"))
    tickers = list(fc.FROZEN_SAMPLE_C)
    with connect() as conn:
        data = load_ticker_data(conn, tickers, start=START_C, end=END_C,
                                watch_start=WS, watch_end=WE)
    rA = run_portfolio(data, PortfolioConfig(gate_mode="prod",
                                             start=START_C, end=END_C))
    r53 = run_portfolio(data, PortfolioConfig(gate_mode="a53",
                                              start=START_C, end=END_C))
    # 멱등 재현 검증 — 저장 판정과 완전 일치해야만 분해 진행
    assert rA["metrics"] == saved["armA_prod_metrics"], "armA 재현 불일치"
    assert r53["metrics"] == saved["arm53_metrics"], "arm53 재현 불일치"

    exA = rA["stats"]["exits"]
    ex53 = r53["stats"]["exits"]
    keyA = {(e["ticker"], e["t1_date"]) for e in exA}
    shared = [e for e in ex53 if (e["ticker"], e["t1_date"]) in keyA]
    only53 = [e for e in ex53 if (e["ticker"], e["t1_date"]) not in keyA]
    key53 = {(e["ticker"], e["t1_date"]) for e in ex53}
    onlyA = [e for e in exA if (e["ticker"], e["t1_date"]) not in key53]

    by_year = {}
    for e in only53:
        y = e["t1_date"][:4]
        by_year.setdefault(y, []).append(e)
    # 진입 시점 국면 (arm53 사다리 기준 — 시장은 종목의 market)
    phase_of = {}
    for t, td in data.items():
        phase_of[t] = td.phase_a53_by_date
    by_phase = {}
    for e in only53:
        ph = phase_of[e["ticker"]].get(date.fromisoformat(e["t1_date"]), "?")
        by_phase.setdefault(ph, []).append(e)

    out = {
        "label": "[탐색적] Arm-53 표본 C 분해 — 채택 근거 사용 금지",
        "reproduction_check": "PASS — 저장 판정 지표와 완전 일치",
        "totals": {"armA": agg(exA), "arm53": agg(ex53)},
        "shared_entries_arm53": agg(shared),
        "arm53_only_entries": agg(only53),
        "armA_only_entries": agg(onlyA),
        "arm53_only_by_year": {y: agg(v) for y, v in sorted(by_year.items())},
        "arm53_only_by_phase": {p: agg(v) for p, v in by_phase.items()},
        "arm53_only_trades": [
            {k: e[k] for k in ("ticker", "t1_date", "date", "reason", "pnl_pct")}
            for e in only53],
    }
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
