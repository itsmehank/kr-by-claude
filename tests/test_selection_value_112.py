"""#112 선별 가치 측정 — 순수 함수 테스트 (설계 2026-11-02-issue112-selection-value-design.md)."""
from __future__ import annotations

from datetime import date

import pytest

from kr_pipeline.backtest.selection_value import (
    assign_sample, cell_excess, diff_bootstrap, ignore_reason,
)


def _rows(start: date, closes: list[float]):
    from datetime import timedelta
    return [(start + timedelta(days=i), c) for i, c in enumerate(closes)]


def test_cell_excess_uses_next_row_after_saturday_and_horizon():
    # 토요일 2024-01-06 분류 → 다음 관측행 01-08(월) 기준, horizon 2 → 01-10
    rows = [(date(2024, 1, 5), 100.0), (date(2024, 1, 8), 110.0),
            (date(2024, 1, 9), 120.0), (date(2024, 1, 10), 121.0)]
    idx = {date(2024, 1, 8): 1000.0, date(2024, 1, 10): 1050.0}
    v = cell_excess(rows, date(2024, 1, 6), 2, idx)
    # 종목 +10% − 지수 +5% = +5.0
    assert v == pytest.approx(5.0)


def test_cell_excess_ignores_rows_on_or_before_analyzed_date():
    rows = [(date(2024, 1, 6), 999.0), (date(2024, 1, 8), 100.0),
            (date(2024, 1, 9), 101.0)]
    idx = {date(2024, 1, 8): 1.0, date(2024, 1, 9): 1.0}
    assert cell_excess(rows, date(2024, 1, 6), 1, idx) == pytest.approx(1.0)


def test_cell_excess_none_when_insufficient_rows_or_index_missing():
    rows = [(date(2024, 1, 8), 100.0), (date(2024, 1, 9), 101.0)]
    idx = {date(2024, 1, 8): 1.0, date(2024, 1, 9): 1.0}
    assert cell_excess(rows, date(2024, 1, 6), 5, idx) is None
    assert cell_excess(rows, date(2024, 1, 6), 1, {date(2024, 1, 8): 1.0}) is None
    assert cell_excess([], date(2024, 1, 6), 1, idx) is None


def test_assign_sample_by_membership_and_window():
    sets = {"A": {"000001"}, "B": {"000002"}, "C": {"000003"}}
    assert assign_sample("000001", date(2022, 3, 5), sets) == "A"
    assert assign_sample("000002", date(2024, 12, 28), sets) == "B"
    assert assign_sample("000003", date(2017, 7, 1), sets) == "C"
    # 창 밖·미소속 → None
    assert assign_sample("000001", date(2019, 3, 5), sets) is None
    assert assign_sample("000003", date(2022, 3, 5), sets) is None
    assert assign_sample("999999", date(2022, 3, 5), sets) is None


def test_ignore_reason_priority():
    assert ignore_reason(["climax_run", "reverse_split_distortion"]) == "reverse_split"
    assert ignore_reason(["topping_distribution", "climax_run"]) == "climax"
    assert ignore_reason(["unfavorable_market_context", "topping_distribution"]) == "topping"
    assert ignore_reason(["extended_from_ma"]) == "other"
    assert ignore_reason(None) == "other"


def test_diff_bootstrap_difference_of_means_and_ci_brackets_point():
    cells = [
        {"ticker": "A", "group": "sel", "x": 3.0},
        {"ticker": "A", "group": "sel", "x": 5.0},
        {"ticker": "B", "group": "sel", "x": 4.0},
        {"ticker": "B", "group": "rej", "x": -2.0},
        {"ticker": "C", "group": "rej", "x": 0.0},
    ]
    out = diff_bootstrap(cells, key="x", sel="sel", rej="rej", b=500, seed=1, min_clusters=2)
    assert out["n_sel"] == 3 and out["n_rej"] == 2
    assert out["mean_sel"] == pytest.approx(4.0)
    assert out["mean_rej"] == pytest.approx(-1.0)
    assert out["diff"] == pytest.approx(5.0)
    lo, hi = out["ci95"]
    assert lo <= 5.0 <= hi


def test_diff_bootstrap_deterministic_for_seed():
    cells = [{"ticker": t, "group": g, "x": float(i)}
             for i, (t, g) in enumerate([("A", "sel"), ("B", "sel"), ("C", "rej"), ("D", "rej")])]
    a = diff_bootstrap(cells, key="x", sel="sel", rej="rej", b=200, seed=7)
    b_ = diff_bootstrap(cells, key="x", sel="sel", rej="rej", b=200, seed=7)
    assert a == b_


def test_diff_bootstrap_empty_group_returns_n_zero():
    cells = [{"ticker": "A", "group": "sel", "x": 1.0}]
    out = diff_bootstrap(cells, key="x", sel="sel", rej="rej", b=10, seed=1)
    assert out["n_rej"] == 0 and out["ci95"] is None


def test_diff_bootstrap_min_clusters_guard_suppresses_ci():
    # 기각군 종목 클러스터가 min_clusters 미만이면 CI 를 내지 않는다(소표본 부트스트랩 퇴화 방지)
    cells = [{"ticker": "A", "group": "sel", "x": 1.0}, {"ticker": "B", "group": "sel", "x": 2.0},
             {"ticker": "C", "group": "sel", "x": 3.0}, {"ticker": "D", "group": "rej", "x": 0.0},
             {"ticker": "E", "group": "rej", "x": -1.0}]
    out = diff_bootstrap(cells, key="x", sel="sel", rej="rej", b=50, seed=1, min_clusters=5)
    assert out["n_rej"] == 2 and out["diff"] == pytest.approx(2.5)
    assert out["ci95"] is None and out["ci_suppressed"] == "rej_clusters<5"
    ok = diff_bootstrap(cells, key="x", sel="sel", rej="rej", b=50, seed=1, min_clusters=2)
    assert ok["ci95"] is not None and ok["ci_suppressed"] is None
