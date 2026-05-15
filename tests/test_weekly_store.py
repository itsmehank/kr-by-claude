from datetime import date

from kr_pipeline.weekly.store import upsert_weekly_prices, upsert_weekly_index


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_weekly_prices_inserts_new(db):
    _seed_stock(db)
    rows = [(
        "005930", date(2026, 5, 15),
        100, 130, 95, 125, 125.0, 6000, 679000, 5,
    )]
    affected = upsert_weekly_prices(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT close, adj_close, trading_days FROM weekly_prices "
            "WHERE ticker = '005930' AND week_end_date = '2026-05-15'"
        )
        assert cur.fetchone() == (125, 125.0, 5)


def test_upsert_weekly_prices_updates_on_conflict(db):
    _seed_stock(db)
    rows_v1 = [("005930", date(2026, 5, 15), 100, 130, 95, 125, 125.0, 6000, 679000, 5)]
    upsert_weekly_prices(db, rows_v1)
    rows_v2 = [("005930", date(2026, 5, 15), 100, 135, 90, 128, 128.0, 7000, 800000, 5)]
    upsert_weekly_prices(db, rows_v2)

    with db.cursor() as cur:
        cur.execute(
            "SELECT high, low, close, adj_close, volume FROM weekly_prices "
            "WHERE ticker = '005930' AND week_end_date = '2026-05-15'"
        )
        assert cur.fetchone() == (135, 90, 128, 128.0, 7000)


def test_upsert_weekly_prices_empty_returns_zero(db):
    affected = upsert_weekly_prices(db, [])
    assert affected == 0


def test_upsert_weekly_index_inserts(db):
    rows = [("1001", date(2026, 5, 15), 2500, 2520, 2490, 2510, None, None, 5)]
    affected = upsert_weekly_index(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT close, volume FROM weekly_index "
            "WHERE index_code = '1001' AND week_end_date = '2026-05-15'"
        )
        assert cur.fetchone() == (2510, None)


def test_upsert_weekly_index_updates_on_conflict(db):
    rows_v1 = [("1001", date(2026, 5, 15), 2500, 2520, 2490, 2510, 1000, 1000000, 5)]
    upsert_weekly_index(db, rows_v1)
    rows_v2 = [("1001", date(2026, 5, 15), 2500, 2530, 2480, 2520, 2000, 2000000, 5)]
    upsert_weekly_index(db, rows_v2)

    with db.cursor() as cur:
        cur.execute("SELECT close, volume FROM weekly_index WHERE index_code='1001' AND week_end_date='2026-05-15'")
        assert cur.fetchone() == (2520, 2000)
