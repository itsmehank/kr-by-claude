# tests/test_market_context_store.py
from datetime import date
from decimal import Decimal

from kr_pipeline.market_context.store import upsert_market_context


def test_upsert_inserts_new_row(db):
    rows = [{
        "date": date(2026, 5, 17),
        "index_code": "1001",
        "current_status": "confirmed_uptrend",
        "distribution_day_count_last_25": 2,
        "last_follow_through_day": date(2026, 4, 12),
        "days_since_follow_through": 35,
        "pct_stocks_above_200d_ma": 47.3,
        "computation_notes": '{"distribution_day_pct_threshold": -0.2}',
    }]
    affected = upsert_market_context(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT current_status, distribution_day_count_last_25, pct_stocks_above_200d_ma FROM market_context_daily WHERE date='2026-05-17' AND index_code='1001'")
        assert cur.fetchone() == ("confirmed_uptrend", 2, Decimal("47.30"))


def test_upsert_updates_on_conflict(db):
    """같은 (date, index_code) 두 번 → 두 번째 값으로 덮어쓰기."""
    rows_v1 = [{
        "date": date(2026, 5, 17), "index_code": "1001",
        "current_status": "rally_attempt",
        "distribution_day_count_last_25": 1, "last_follow_through_day": None,
        "days_since_follow_through": None, "pct_stocks_above_200d_ma": 30.0,
        "computation_notes": None,
    }]
    upsert_market_context(db, rows_v1)

    rows_v2 = [{
        "date": date(2026, 5, 17), "index_code": "1001",
        "current_status": "confirmed_uptrend",
        "distribution_day_count_last_25": 2, "last_follow_through_day": date(2026, 4, 1),
        "days_since_follow_through": 46, "pct_stocks_above_200d_ma": 55.5,
        "computation_notes": None,
    }]
    upsert_market_context(db, rows_v2)

    with db.cursor() as cur:
        cur.execute("SELECT current_status, distribution_day_count_last_25 FROM market_context_daily WHERE date='2026-05-17' AND index_code='1001'")
        assert cur.fetchone() == ("confirmed_uptrend", 2)
