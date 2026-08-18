"""#111 minervini_forward 단위 테스트 — 스펙 §2 정의 검증."""
from datetime import date, timedelta

import pytest

from kr_pipeline.backtest.minervini_forward import (
    agg_bootstrap_ci, extract_transitions, forward_excess, horizon_stats, verdict_of,
    iter_ticker_rows, load_index_closes, load_markets, transition_events,
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


def _seed_db(db):
    d0 = date(2024, 1, 1)
    with db.cursor() as cur:
        for t in ("111110", "111120"):
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') "
                "ON CONFLICT DO NOTHING", (t,))
        for i in range(30):
            d = d0 + timedelta(days=i)
            cur.execute(
                "INSERT INTO index_daily (index_code, date, open, high, low, close) "
                "VALUES ('1001', %s, 1, 1, 1, %s)", (d, 1000 + i))
            for t, base in (("111110", 100), ("111120", 200)):
                cur.execute(
                    "INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass) "
                    "VALUES (%s, %s, %s, %s)",
                    (t, d, base + i, i >= 5 if t == "111110" else False))
    return d0


def test_loaders(db):
    d0 = _seed_db(db)
    idx = load_index_closes(db)
    assert idx["1001"][d0] == 1000.0
    assert load_markets(db)["111110"] == "KOSPI"
    rows_by = dict(iter_ticker_rows(db))
    rows = rows_by["111110"]
    assert rows[0][0] == d0 and rows[0][1] == 100.0   # date 오름차순·float 변환
    assert extract_transitions(rows) == [5]
    assert extract_transitions(rows_by["111120"]) == []


def test_transition_events_and_exclusions(db):
    _seed_db(db)
    events, excluded = transition_events(db)
    assert len(events) == 1
    e = events[0]
    assert e["ticker"] == "111110" and "excess_20" in e
    # 행 30개: 전환 i=5, T+1=6, 20행 뒤=26 존재 / 40·65 는 부족 → horizon별 제외
    assert "excess_40" not in e and "excess_65" not in e
    assert excluded == {20: 0, 40: 1, 65: 1}
