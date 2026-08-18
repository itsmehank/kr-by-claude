"""#111 minervini_forward 단위 테스트 — 스펙 §2 정의 검증."""
from datetime import date, timedelta

import pytest

from kr_pipeline.backtest.minervini_forward import (
    agg_bootstrap_ci, extract_transitions, forward_excess, horizon_stats, verdict_of,
)
from kr_pipeline.backtest.refinement import cluster_bootstrap_ci


def _row(i, close, label, cc=None):
    return (date(2024, 1, 1) + timedelta(days=i), close, label, cc)


def test_extract_transitions_basic():
    rows = [_row(0, 100, False), _row(1, 100, False), _row(2, 100, True),
            _row(3, 100, True), _row(4, 100, False), _row(5, 100, True)]
    assert extract_transitions(rows) == [2, 5]


def test_extract_transitions_first_row_and_null_excluded():
    # 최초 관측·직전 NULL 은 전환 아님 (스펙 §2.1)
    assert extract_transitions([_row(0, 100, True)]) == []
    assert extract_transitions([_row(0, 100, None), _row(1, 100, True)]) == []
    rows = [_row(0, 100, False), _row(1, 100, None), _row(2, 100, True)]
    assert extract_transitions(rows) == []


def test_forward_excess_known_values():
    rows = [_row(0, 50, True), _row(1, 100, True), _row(2, 105, True),
            _row(3, 110, True)]
    iclose = {rows[1][0]: 1000.0, rows[3][0]: 1050.0}
    # T=행0 → 기준 T+1(행1)=100, 2행 뒤(행3)=110: 종목 +10% − 지수 +5% = +5.0
    assert forward_excess(rows, 0, 2, iclose) == pytest.approx(5.0)


def test_forward_excess_insufficient_rows_returns_none():
    rows = [_row(0, 100, True), _row(1, 100, True)]
    assert forward_excess(rows, 0, 2, {rows[1][0]: 1.0}) is None


def test_forward_excess_missing_index_returns_none():
    rows = [_row(0, 50, True), _row(1, 100, True), _row(2, 105, True),
            _row(3, 110, True)]
    assert forward_excess(rows, 0, 2, {rows[1][0]: 1000.0}) is None


def test_verdict_of():
    assert verdict_of(0.1, 2.0) == "유효"
    assert verdict_of(-0.5, 1.0) == "미입증"
    assert verdict_of(-2.0, -0.1) == "역효과"


def test_agg_bootstrap_matches_refinement():
    # 등가성: 같은 seed·b 에서 기존 함수와 동일 결과 (스펙 §2.5)
    vals = {"A": [1.0, 2.0], "B": [-3.0], "C": [0.5, 4.5, -1.0]}
    trades = [{"ticker": t, "excess_net": v} for t, vs in vals.items() for v in vs]
    expected = cluster_bootstrap_ci(trades, b=500, seed=20260721)
    agg = {t: (sum(vs), len(vs)) for t, vs in vals.items()}
    assert agg_bootstrap_ci(agg, b=500, seed=20260721) == expected


def test_horizon_stats_counts_mean_median():
    events = [{"ticker": "A", "excess_20": 1.0}, {"ticker": "A", "excess_20": 3.0},
              {"ticker": "B", "excess_20": -1.0}, {"ticker": "B"}]  # 마지막 = 결손
    st = horizon_stats(events, 20)
    assert st["n"] == 3 and st["tickers"] == 2
    assert st["mean"] == 1.0 and st["median"] == 1.0
    assert len(st["ci95"]) == 2


def test_horizon_stats_empty():
    assert horizon_stats([{"ticker": "A"}], 20) == {"n": 0}
