"""#110 0단계 견적 — 자격 셀 전수 계산 + 비용·처리량 + 도달 MDE (읽기 전용, LLM 0·KRX 0).

셀 = (종목, 토요일). 자격 = 그 토요일 이하 최신 daily_indicators 행이
minervini_pass ∧ rs_line_not_declining_7m ∧ 당일 거래정지 아님(get_qualifying_tickers 와 동일 조건)
∧ stocks.security_group ∈ QUALIFYING_SECURITY_GROUPS(SECUGRP — 라이브 게이트는 2026-09-15 이후 전진 적용이라
  과거 행에는 걸리지 않음; 여기서는 설계 선택으로 적용)
∧ 현재 상장(delisted_at IS NULL — 상폐는 별도 집계: 라이브 테이블 잔존분 + #181 격리 테이블)
∧ backtest_classification 에 없는 셀(기존 표본 A·B·C·초기 잔여 제외).

도달 MDE: #116 P2-1 과 같은 트레이드(build_refined_trades, 표본 A·B·C)를 재구성해 **연도별 트레이드/셀** 과
클러스터 SE 풀링 트레이드당 분산으로 √n 외삽(판정 아님). 리뷰 R1(2026-11-02) 반영: 연도별 발생률,
격리 상폐 셀, 증권구분 집합, 처리량 중앙값, new-only MDE, 기존 종목 중복.
산출물: data/backtest/issue110_stage0_estimate_YYYYMMDD.json
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter
from datetime import date

import kr_pipeline.backtest.frozen_sample_c as fc
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.backtest.refinement import build_refined_trades
from kr_pipeline.common.security_group import QUALIFYING_SECURITY_GROUPS
from kr_pipeline.db.connection import connect

Z975, Z80 = 1.959964, 0.841621
MDE_TARGET = 3.0                      # 전문가 4차(#110 코멘트 2026-08-18): 도달 MDE80 > 3%p 면 기각
MDE_SOURCE = "data/backtest/issue116_mde_20260818.json"   # 클러스터 SE(권위 수치, 2026-08-18 커밋본)
# 관측 처리량(표본 C 일요일 4회, created_at 실측): 213·264·423·590 셀/일 → 중앙값 343.5, 평균 372.5
SUNDAY_CELLS_OBSERVED = (213, 264, 423, 590)
# 셀당 토큰(backtest_classification 가중 평균 실측): #103 전 입력 222k / 후(08-11~12) 142k, 출력 13.6k, 호출 중앙값 ≈160s
TOKENS_PER_CELL = {"input_pre_103": 222_000, "input_post_103": 142_000, "output": 13_600}
SAMPLE_WINDOWS = {"A": (date(2021, 1, 1), date(2024, 12, 31)), "B": (date(2021, 1, 1), date(2024, 12, 31)),
                  "C": (date(2017, 7, 1), date(2020, 12, 31))}

SQL = """
WITH sat AS (SELECT d::date AS s FROM generate_series(%(start)s::date, %(end)s::date, '7 days') d),
tgt AS (SELECT s, (SELECT max(date) FROM daily_indicators WHERE date <= s) AS t FROM sat),
q AS (
  SELECT tg.s, i.ticker, st.security_group, (st.delisted_at IS NOT NULL) AS now_delisted,
         EXISTS (SELECT 1 FROM backtest_classification b
                  WHERE b.symbol = i.ticker AND b.analyzed_for_date = tg.s) AS existing,
         (i.ticker = ANY(%(bt_tickers)s)) AS bt_ticker
  FROM tgt tg JOIN daily_indicators i ON i.date = tg.t
  JOIN stocks st ON st.ticker = i.ticker
  WHERE i.minervini_pass AND i.rs_line_not_declining_7m
    AND NOT EXISTS (SELECT 1 FROM daily_prices p
                     WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL)
),
iso AS (   -- #181 격리 상폐 테이블(같은 날짜·같은 조건) — 집계 전용
  SELECT tg.s, i.ticker FROM tgt tg JOIN delisted_daily_indicators i ON i.date = tg.t
  WHERE i.minervini_pass AND i.rs_line_not_declining_7m
    AND NOT EXISTS (SELECT 1 FROM delisted_daily_prices_adj p
                     WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL)
)
SELECT yr, max(qualifying), max(existing), max(now_delisted_live), max(non_qualifying_group),
       max(new_cells), max(new_tickers), max(new_cells_bt_ticker), max(saturdays), max(delisted_isolated)
FROM (
  SELECT extract(year from s)::int AS yr,
         count(*) AS qualifying,
         count(*) FILTER (WHERE existing) AS existing,
         count(*) FILTER (WHERE now_delisted) AS now_delisted_live,
         count(*) FILTER (WHERE NOT now_delisted AND NOT (security_group = ANY(%(groups)s))) AS non_qualifying_group,
         count(*) FILTER (WHERE NOT existing AND NOT now_delisted AND security_group = ANY(%(groups)s)) AS new_cells,
         count(DISTINCT ticker) FILTER (WHERE NOT existing AND NOT now_delisted AND security_group = ANY(%(groups)s)) AS new_tickers,
         count(*) FILTER (WHERE NOT existing AND NOT now_delisted AND security_group = ANY(%(groups)s) AND bt_ticker) AS new_cells_bt_ticker,
         count(DISTINCT s) AS saturdays, 0 AS delisted_isolated
  FROM q GROUP BY 1
  UNION ALL
  SELECT extract(year from s)::int, 0, 0, 0, 0, 0, 0, 0, 0, count(*) FROM iso GROUP BY 1
) u GROUP BY yr ORDER BY yr
"""

SAMPLE_CELLS_SQL = """
SELECT extract(year from analyzed_for_date)::int AS yr, count(*),
       count(*) FILTER (WHERE classification = 'ignore')
FROM backtest_classification
WHERE (symbol = ANY(%(a)s) AND analyzed_for_date BETWEEN '2021-01-01' AND '2024-12-31')
   OR (symbol = ANY(%(b)s) AND analyzed_for_date BETWEEN '2021-01-01' AND '2024-12-31')
   OR (symbol = ANY(%(c)s) AND analyzed_for_date BETWEEN '2017-07-01' AND '2020-12-31')
GROUP BY 1 ORDER BY 1
"""


def mde80(sigma2: float, n: float) -> float:
    return (Z975 + Z80) * math.sqrt(sigma2 / n)


def main() -> int:
    with open(MDE_SOURCE) as f:
        mde_src = json.load(f)["samples"]
    with connect() as conn:
        conn.execute("SET default_transaction_read_only = on")
        bt_tickers = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM backtest_classification").fetchall()]
        rows = conn.execute(SQL, {"start": date(2017, 7, 1), "end": date(2024, 12, 28),
                                  "groups": sorted(QUALIFYING_SECURITY_GROUPS), "bt_tickers": bt_tickers}).fetchall()
        sample_rows = conn.execute(SAMPLE_CELLS_SQL, {"a": list(FROZEN_SAMPLE), "b": list(FROZEN_SAMPLE_B),
                                                      "c": list(fc.FROZEN_SAMPLE_C)}).fetchall()
        # 표본 트레이드 재구성(#116 P2-1 과 동일 호출) — 연도별 발생률·iid 분산용
        trades = {
            "A": build_refined_trades(conn, tickers=list(FROZEN_SAMPLE))[0],
            "B": build_refined_trades(conn, tickers=list(FROZEN_SAMPLE_B))[0],
            "C": build_refined_trades(conn, tickers=list(fc.FROZEN_SAMPLE_C),
                                      watch_start=date(2017, 7, 1), watch_end=date(2020, 12, 31),
                                      px_start=date(2017, 1, 1), px_end=date(2021, 6, 30))[0],
        }

    # --- 트레이드당 분산(클러스터 SE 풀링, 권위 수치 2026-08-18) + iid 분산 → 설계효과 ---
    n_src = sum(v["n_trades"] for v in mde_src.values())
    sigma2 = sum(v["n_trades"] * (v["n_trades"] * v["se"] ** 2) for v in mde_src.values()) / n_src
    # 트레이드의 셀 연도 귀속: 트레이드에는 분류일이 없어 entry_date 연도를 쓰되, watch 창 종료 뒤 진입
    # (A/B: 2025 진입, C: 2021-H1 진입)은 창 마지막 연도(2024 / 2020)의 셀에서 나온 것이므로 그 해로 귀속.
    for name, ts in trades.items():
        last = SAMPLE_WINDOWS[name][1].year
        for t in ts:
            t["cell_year"] = min(t["entry_date"].year, last)
    all_trades = [t for ts in trades.values() for t in ts if t.get("excess_net") is not None]
    iid_var = statistics.pvariance([t["excess_net"] for t in all_trades])
    n_now = len(all_trades)

    # --- 연도별 트레이드/셀 (표본 셀 연도 = analyzed_for_date, 트레이드 연도 = entry_date) ---
    cells_by_year = {int(r[0]): {"cells": r[1], "ignore": r[2]} for r in sample_rows}
    trades_by_year = Counter(t["cell_year"] for t in all_trades)
    trades_by_entry_year = Counter(t["entry_date"].year for t in all_trades)
    rate_by_year = {y: round(trades_by_year.get(y, 0) / v["cells"], 5) for y, v in cells_by_year.items()}
    sample_cells_total = sum(v["cells"] for v in cells_by_year.values())
    pooled_rate = n_now / sample_cells_total
    ignore_rate_by_year = {y: v["ignore"] / v["cells"] for y, v in cells_by_year.items()}

    by_year: dict[int, dict] = {}
    for r in rows:
        y = int(r[0])
        rate = rate_by_year.get(y, pooled_rate)
        by_year[y] = {"qualifying": r[1], "existing": r[2], "now_delisted_live": r[3],
                      "non_qualifying_group": r[4], "new_cells": r[5], "new_tickers": r[6],
                      "new_cells_bt_ticker": r[7], "saturdays": r[8], "delisted_isolated": r[9],
                      "trades_per_cell_year": rate, "expected_trades": round(r[5] * rate, 1),
                      "expected_trades_pooled_rate": round(r[5] * pooled_rate, 1),
                      "expected_ignore": round(r[5] * ignore_rate_by_year.get(y, 0.049))}

    med = statistics.median(SUNDAY_CELLS_OBSERVED)
    mean = statistics.mean(SUNDAY_CELLS_OBSERVED)

    def plan(years: list[int], label: str) -> dict:
        cells = sum(by_year[y]["new_cells"] for y in years)
        tr_new = sum(by_year[y]["expected_trades"] for y in years)
        tr_pooled = cells * pooled_rate
        return {
            "label": label, "years": years, "new_cells": cells,
            "new_cells_on_existing_bt_tickers": sum(by_year[y]["new_cells_bt_ticker"] for y in years),
            "delisted_cells_excluded": sum(by_year[y]["now_delisted_live"] + by_year[y]["delisted_isolated"] for y in years),
            "expected_new_trades_year_rate": round(tr_new), "expected_new_trades_pooled_rate": round(tr_pooled),
            "mde80_new_only": round(mde80(sigma2, tr_new), 2),
            "mde80_incl_existing": round(mde80(sigma2, tr_new + n_now), 2),
            "mde80_new_only_pooled_rate": round(mde80(sigma2, tr_pooled), 2),
            "passes_target_new_only": mde80(sigma2, tr_new) <= MDE_TARGET,
            "passes_target_incl_existing": mde80(sigma2, tr_new + n_now) <= MDE_TARGET,
            "expected_ignore_cells": sum(by_year[y]["expected_ignore"] for y in years),
            "sundays_median": math.ceil(cells / med), "sundays_mean": math.ceil(cells / mean),
            "sundays_range": [math.ceil(cells / max(SUNDAY_CELLS_OBSERVED)), math.ceil(cells / min(SUNDAY_CELLS_OBSERVED))],
            "input_tokens_post_103_M": round(cells * TOKENS_PER_CELL["input_post_103"] / 1e6),
            "output_tokens_M": round(cells * TOKENS_PER_CELL["output"] / 1e6),
        }

    n_needed = sigma2 * ((Z975 + Z80) / MDE_TARGET) ** 2
    out = {
        "issue": 110, "stage": 0, "grade": "estimate_non_judgment", "as_of": date.today().isoformat(),
        "filter": ("minervini_pass ∧ rs_line_not_declining_7m ∧ not halted ∧ security_group ∈ "
                   f"{sorted(QUALIFYING_SECURITY_GROUPS)} ∧ listed now ∧ not in backtest_classification"),
        "assumptions": {
            "mde_formula": "MDE80 = (z0.975+z0.80)·sqrt(sigma2/n_trades); sigma2 = Σ n_i·(n_i·se_i²)/Σ n_i (#116 P2-1 클러스터 SE)",
            "mde_target": MDE_TARGET,
            "trades_per_cell_pooled": round(pooled_rate, 5),
            "trades_per_cell_by_year": rate_by_year,
            "sample_cells_by_year": cells_by_year,
            "sample_trades_by_cell_year": dict(sorted(trades_by_year.items())),
            "sample_trades_by_entry_year": dict(sorted(trades_by_entry_year.items())),
            "ignore_rate_by_year": {y: round(v, 4) for y, v in ignore_rate_by_year.items()},
            "sunday_cells_observed": SUNDAY_CELLS_OBSERVED, "sunday_cells_median": med, "sunday_cells_mean": mean,
            "tokens_per_cell": TOKENS_PER_CELL,
        },
        "trade_variance": {
            "n_trades_src_20260818": n_src, "n_trades_rebuilt_today": n_now,
            "sigma2_per_trade_cluster": round(sigma2, 1), "sigma_per_trade": round(math.sqrt(sigma2), 2),
            "sigma2_per_trade_iid": round(iid_var, 1), "design_effect": round(sigma2 / iid_var, 3),
            "per_sample": {k: {"n": v["n_trades"], "se": v["se"], "sigma2": round(v["n_trades"] * v["se"] ** 2, 1)}
                           for k, v in mde_src.items()},
        },
        "trades_needed_for_target": round(n_needed),
        "new_trades_needed_incl_existing": round(n_needed - n_now),
        "by_year": by_year,
        "plans": {
            "slice_2021": plan([2021], "2021 단독"),
            "slice_2021_2024": plan([2021, 2024], "2021+2024 (사용자 선택 2026-11-02)"),
            "slice_2021_2023_2024": plan([2021, 2023, 2024], "2021+2023+2024"),
            "range_2021_2024": plan([2021, 2022, 2023, 2024], "2021~2024"),
            "range_2019_2024": plan([2019, 2020, 2021, 2022, 2023, 2024], "2019~2024 (이슈 본문 = 최대 범위)"),
            "range_2017H2_2024": plan(list(range(2017, 2025)), "2017-H2~2024 (확장)"),
        },
    }
    path = f"data/backtest/issue110_stage0_estimate_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({"rates": rate_by_year, "pooled": round(pooled_rate, 5), "deff": out["trade_variance"]["design_effect"],
                      "plans": {k: {kk: v[kk] for kk in ("new_cells", "expected_new_trades_year_rate", "mde80_new_only",
                                                         "mde80_incl_existing", "expected_ignore_cells", "sundays_median")}
                                for k, v in out["plans"].items()}}, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
