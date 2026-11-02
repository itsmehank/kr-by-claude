"""#110 0단계 견적 — 자격 셀 전수 계산 + 비용·처리량 + 도달 MDE (읽기 전용, LLM 0·KRX 0).

셀 = (종목, 토요일). 자격 = 그 토요일 이하 최신 daily_indicators 행이
minervini_pass ∧ rs_line_not_declining_7m ∧ 당일 거래정지 아님(get_qualifying_tickers 와 동일 조건)
∧ stocks.security_group='주권'(SECUGRP 현행 필터) ∧ 현재 상장(delisted_at IS NULL — 상폐 포함은 #180 ②-2 후 별도)
∧ backtest_classification 에 없는 셀(기존 표본 A·B·C·초기 잔여 제외).

도달 MDE 는 #116 P2-1 의 표본별 클러스터 SE 로 트레이드당 분산을 풀링해 √n 외삽한다(판정 아님).
산출물: data/backtest/issue110_stage0_estimate_YYYYMMDD.json
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date

from kr_pipeline.db.connection import connect

Z975, Z80 = 1.959964, 0.841621
MDE_TARGET = 3.0                      # 전문가 4차(#110 코멘트 2026-08-18): 도달 MDE80 > 3%p 면 기각
MDE_SOURCE = "data/backtest/issue116_mde_20260818.json"
# 표본 셀 수(귀속분) — #112 판독 §2: A 2,135 / B 1,952 / C 1,771
SAMPLE_CELLS = {"A": 2135, "B": 1952, "C": 1771}
# 관측 처리량(표본 C 일요일 4회: 264·423·590·213 셀/일, #112 PR 견적 §) — 계획값은 중앙값 근사
SUNDAY_CELLS_PLAN = 400
SUNDAY_CELLS_RANGE = (213, 590)
# 셀당 토큰(backtest_classification 실측): #103 전 ≈21만 입력 / 후 08-11~12 ≈15.0만·12.2만, 출력 ≈1.3만
TOKENS_PER_CELL = {"input_pre_103": 215_000, "input_post_103": 136_000, "output": 13_300}
# 기각(ignore) 비율 — 기존 저장본 연도별(#112 판독 §7 슬라이스 근거)
IGNORE_RATE_BY_YEAR = {2017: 1 / 304, 2018: 10 / 421, 2019: 4 / 347, 2020: 7 / 699,
                       2021: 161 / 1792, 2022: 34 / 588, 2023: 30 / 998, 2024: 48 / 873}

SQL = """
WITH sat AS (SELECT d::date AS s FROM generate_series(%(start)s::date, %(end)s::date, '7 days') d),
tgt AS (SELECT s, (SELECT max(date) FROM daily_indicators WHERE date <= s) AS t FROM sat),
q AS (
  SELECT tg.s, i.ticker, st.security_group, (st.delisted_at IS NOT NULL) AS now_delisted,
         EXISTS (SELECT 1 FROM backtest_classification b
                  WHERE b.symbol = i.ticker AND b.analyzed_for_date = tg.s) AS existing
  FROM tgt tg JOIN daily_indicators i ON i.date = tg.t
  JOIN stocks st ON st.ticker = i.ticker
  WHERE i.minervini_pass AND i.rs_line_not_declining_7m
    AND NOT EXISTS (SELECT 1 FROM daily_prices p
                     WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL)
)
SELECT extract(year from s)::int AS yr,
       count(*) AS qualifying,
       count(*) FILTER (WHERE existing) AS existing,
       count(*) FILTER (WHERE now_delisted) AS now_delisted,
       count(*) FILTER (WHERE security_group IS DISTINCT FROM '주권') AS non_equity,
       count(*) FILTER (WHERE NOT existing AND NOT now_delisted AND security_group = '주권') AS new_cells,
       count(DISTINCT ticker) FILTER (WHERE NOT existing AND NOT now_delisted AND security_group = '주권') AS new_tickers,
       count(DISTINCT s) AS saturdays
FROM q GROUP BY 1 ORDER BY 1
"""


def pooled_trade_variance(mde_json: dict) -> dict:
    """표본별 클러스터 SE → 트레이드당 분산 σ_i² = n_i·se_i², 트레이드 수 가중 풀링."""
    s = mde_json["samples"]
    n_tot = sum(v["n_trades"] for v in s.values())
    var = sum(v["n_trades"] * (v["n_trades"] * v["se"] ** 2) for v in s.values()) / n_tot
    cells = sum(SAMPLE_CELLS.values())
    return {"n_trades_existing": n_tot, "sigma2_per_trade": round(var, 1),
            "sigma_per_trade": round(math.sqrt(var), 2),
            "trades_per_cell": round(n_tot / cells, 5), "sample_cells": cells,
            "per_sample": {k: {"n": v["n_trades"], "se": v["se"],
                               "sigma2": round(v["n_trades"] * v["se"] ** 2, 1)} for k, v in s.items()}}


def mde80(sigma2: float, n: float) -> float:
    return (Z975 + Z80) * math.sqrt(sigma2 / n)


def main() -> int:
    with open(MDE_SOURCE) as f:
        pv = pooled_trade_variance(json.load(f))
    with connect() as conn:
        conn.execute("SET default_transaction_read_only = on")
        rows = conn.execute(SQL, {"start": date(2017, 7, 1), "end": date(2024, 12, 28)}).fetchall()
    by_year = {int(r[0]): {"qualifying": r[1], "existing": r[2], "now_delisted": r[3],
                           "non_equity": r[4], "new_cells": r[5], "new_tickers": r[6],
                           "saturdays": r[7],
                           "expected_ignore": round(r[5] * IGNORE_RATE_BY_YEAR[int(r[0])]),
                           "expected_trades": round(r[5] * pv["trades_per_cell"], 1)}
               for r in rows}

    def plan(years: list[int], label: str) -> dict:
        cells = sum(by_year[y]["new_cells"] for y in years)
        trades_new = cells * pv["trades_per_cell"]
        trades_all = trades_new + pv["n_trades_existing"]
        ignore = sum(by_year[y]["expected_ignore"] for y in years)
        return {
            "label": label, "years": years, "new_cells": cells,
            "new_tickers_union_upper_bound": sum(by_year[y]["new_tickers"] for y in years),
            "expected_new_trades": round(trades_new), "expected_trades_incl_existing": round(trades_all),
            "mde80_new_only": round(mde80(pv["sigma2_per_trade"], trades_new), 2),
            "mde80_incl_existing": round(mde80(pv["sigma2_per_trade"], trades_all), 2),
            "passes_target": mde80(pv["sigma2_per_trade"], trades_all) <= MDE_TARGET,
            "expected_ignore_cells": ignore,
            "sundays_plan": math.ceil(cells / SUNDAY_CELLS_PLAN),
            "sundays_range": [math.ceil(cells / SUNDAY_CELLS_RANGE[1]), math.ceil(cells / SUNDAY_CELLS_RANGE[0])],
            "input_tokens_post_103_M": round(cells * TOKENS_PER_CELL["input_post_103"] / 1e6),
            "output_tokens_M": round(cells * TOKENS_PER_CELL["output"] / 1e6),
        }

    # 최소 셀 수 for MDE 목표(기존 244 트레이드 포함)
    n_needed = pv["sigma2_per_trade"] * ((Z975 + Z80) / MDE_TARGET) ** 2
    cells_needed = (n_needed - pv["n_trades_existing"]) / pv["trades_per_cell"]

    # 누적 슬라이스(#112 §7 우선순위: ignore 발생 많은 연도부터)
    order = sorted([y for y in by_year if y >= 2019], key=lambda y: -by_year[y]["expected_ignore"])
    cumulative = []
    acc: list[int] = []
    for y in order:
        acc.append(y)
        cumulative.append(plan(sorted(acc), f"누적 {'+'.join(map(str, sorted(acc)))}"))

    out = {
        "issue": 110, "stage": 0, "grade": "estimate_non_judgment", "as_of": date.today().isoformat(),
        "filter": "minervini_pass ∧ rs_line_not_declining_7m ∧ not halted ∧ security_group='주권' ∧ listed now ∧ not in backtest_classification",
        "assumptions": {
            "trades_per_cell_from_samples": pv["trades_per_cell"],
            "sigma2_per_trade_pooled_cluster": pv["sigma2_per_trade"],
            "mde_formula": "MDE80 = (z0.975+z0.80)·sqrt(sigma2/n_trades); 표본 클러스터 SE 풀링(#116 P2-1)",
            "mde_target": MDE_TARGET,
            "sunday_cells_plan": SUNDAY_CELLS_PLAN, "sunday_cells_range_observed": SUNDAY_CELLS_RANGE,
            "tokens_per_cell": TOKENS_PER_CELL, "ignore_rate_by_year": {k: round(v, 4) for k, v in IGNORE_RATE_BY_YEAR.items()},
        },
        "trade_variance": pv,
        "trades_needed_for_target": round(n_needed), "new_cells_needed_for_target": round(cells_needed),
        "by_year": by_year,
        "plans": {
            "range_2019_2024": plan([2019, 2020, 2021, 2022, 2023, 2024], "2019~2024 (이슈 본문)"),
            "range_2017H2_2024": plan(list(range(2017, 2025)), "2017-H2~2024 (확장)"),
            "slice_2021": plan([2021], "2021 단독"),
            "slice_2021_2024": plan([2021, 2024], "2021+2024"),
        },
        "cumulative_by_ignore_priority": cumulative,
    }
    path = f"data/backtest/issue110_stage0_estimate_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({"trades_needed": out["trades_needed_for_target"], "cells_needed": out["new_cells_needed_for_target"],
                      "plans": {k: {kk: v[kk] for kk in ("new_cells", "mde80_incl_existing", "expected_ignore_cells", "sundays_plan", "sundays_range")}
                                for k, v in out["plans"].items()}}, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
