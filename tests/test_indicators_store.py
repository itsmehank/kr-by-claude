# tests/test_indicators_store.py
from datetime import date

from kr_pipeline.indicators.store import (
    upsert_daily_indicators_phase_a,
    update_daily_indicators_rs_rating,
    update_daily_indicators_minervini_pass,
)


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_phase_a_inserts_new_row(db):
    _seed_stock(db)
    rows = [{
        "ticker": "005930",
        "date": date(2026, 5, 15),
        "adj_close": 70000.0,
        "sma_10": 69000.0, "sma_21": 68000.0, "sma_50": 65000.0,
        "sma_150": 60000.0, "sma_200": 55000.0,
        "w52_high": 80000.0, "w52_low": 50000.0,
        "pct_from_52w_high": -12.5, "pct_from_52w_low": 40.0,
        "rs_line": 0.0040, "rs_line_52w_high": 0.0050, "rs_line_52w_high_date": date(2026, 1, 15),
        "rs_line_at_52w_high": False,
        "rs_line_uptrend_6w": True, "rs_line_uptrend_13w": True,
        "rs_line_in_decline_7m": False,
        "minervini_c1": True, "minervini_c2": True, "minervini_c3": True,
        "minervini_c4": True, "minervini_c5": True, "minervini_c6": True,
        "minervini_c7": True,
    }]
    affected = upsert_daily_indicators_phase_a(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT adj_close, sma_50, minervini_c1, rs_rating FROM daily_indicators WHERE ticker='005930' AND date='2026-05-15'")
        row = cur.fetchone()
    assert row[0] == 70000.0
    assert row[1] == 65000.0
    assert row[2] == True
    assert row[3] is None   # rs_rating 은 Phase B 에서


def test_upsert_phase_a_updates_on_conflict(db):
    _seed_stock(db)
    rows_v1 = [{
        "ticker": "005930", "date": date(2026, 5, 15), "adj_close": 70000.0,
        "sma_10": None, "sma_21": None, "sma_50": None, "sma_150": None, "sma_200": None,
        "w52_high": None, "w52_low": None, "pct_from_52w_high": None, "pct_from_52w_low": None,
        "rs_line": None, "rs_line_52w_high": None, "rs_line_52w_high_date": None,
        "rs_line_at_52w_high": None, "rs_line_uptrend_6w": None, "rs_line_uptrend_13w": None,
        "rs_line_in_decline_7m": None,
        "minervini_c1": None, "minervini_c2": None, "minervini_c3": None,
        "minervini_c4": None, "minervini_c5": None, "minervini_c6": None, "minervini_c7": None,
    }]
    upsert_daily_indicators_phase_a(db, rows_v1)

    rows_v2 = [dict(rows_v1[0], adj_close=71000.0, sma_50=65000.0)]
    upsert_daily_indicators_phase_a(db, rows_v2)

    with db.cursor() as cur:
        cur.execute("SELECT adj_close, sma_50 FROM daily_indicators WHERE ticker='005930'")
        assert cur.fetchone() == (71000.0, 65000.0)


def test_update_rs_rating_sets_value(db):
    _seed_stock(db)
    rows = [dict(
        ticker="005930", date=date(2026, 5, 15), adj_close=70000.0,
        sma_10=None, sma_21=None, sma_50=None, sma_150=None, sma_200=None,
        w52_high=None, w52_low=None, pct_from_52w_high=None, pct_from_52w_low=None,
        rs_line=None, rs_line_52w_high=None, rs_line_52w_high_date=None,
        rs_line_at_52w_high=None, rs_line_uptrend_6w=None, rs_line_uptrend_13w=None,
        rs_line_in_decline_7m=None,
        minervini_c1=None, minervini_c2=None, minervini_c3=None,
        minervini_c4=None, minervini_c5=None, minervini_c6=None, minervini_c7=None,
    )]
    upsert_daily_indicators_phase_a(db, rows)

    affected = update_daily_indicators_rs_rating(db, [("005930", date(2026, 5, 15), 85)])
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT rs_rating FROM daily_indicators WHERE ticker='005930'")
        assert cur.fetchone() == (85,)


def test_update_minervini_pass_uses_sql(db):
    """SQL UPDATE 가 minervini_c8 와 pass 를 계산하는지."""
    _seed_stock(db)
    # 모든 c1-c7 True, rs_rating 85 시드
    rows = [dict(
        ticker="005930", date=date(2026, 5, 15), adj_close=70000.0,
        sma_10=None, sma_21=None, sma_50=65000.0, sma_150=60000.0, sma_200=55000.0,
        w52_high=80000.0, w52_low=50000.0, pct_from_52w_high=-12.5, pct_from_52w_low=40.0,
        rs_line=None, rs_line_52w_high=None, rs_line_52w_high_date=None,
        rs_line_at_52w_high=None, rs_line_uptrend_6w=None, rs_line_uptrend_13w=None,
        rs_line_in_decline_7m=None,
        minervini_c1=True, minervini_c2=True, minervini_c3=True,
        minervini_c4=True, minervini_c5=True, minervini_c6=True, minervini_c7=True,
    )]
    upsert_daily_indicators_phase_a(db, rows)
    update_daily_indicators_rs_rating(db, [("005930", date(2026, 5, 15), 85)])

    affected = update_daily_indicators_minervini_pass(db, date(2026, 5, 15), date(2026, 5, 15))
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT minervini_c8, minervini_pass FROM daily_indicators WHERE ticker='005930'")
        c8, pass_ = cur.fetchone()
    assert c8 == True       # rs_rating 85 >= 70
    assert pass_ == True    # 8 모두 True


def test_minervini_pass_false_when_any_condition_false(db):
    """c1-c7 중 하나라도 False 면 pass=False"""
    _seed_stock(db)
    rows = [dict(
        ticker="005930", date=date(2026, 5, 15), adj_close=70000.0,
        sma_10=None, sma_21=None, sma_50=None, sma_150=None, sma_200=None,
        w52_high=None, w52_low=None, pct_from_52w_high=None, pct_from_52w_low=None,
        rs_line=None, rs_line_52w_high=None, rs_line_52w_high_date=None,
        rs_line_at_52w_high=None, rs_line_uptrend_6w=None, rs_line_uptrend_13w=None,
        rs_line_in_decline_7m=None,
        minervini_c1=False, minervini_c2=True, minervini_c3=True,
        minervini_c4=True, minervini_c5=True, minervini_c6=True, minervini_c7=True,
    )]
    upsert_daily_indicators_phase_a(db, rows)
    update_daily_indicators_rs_rating(db, [("005930", date(2026, 5, 15), 85)])
    update_daily_indicators_minervini_pass(db, date(2026, 5, 15), date(2026, 5, 15))

    with db.cursor() as cur:
        cur.execute("SELECT minervini_pass FROM daily_indicators WHERE ticker='005930'")
        assert cur.fetchone() == (False,)
