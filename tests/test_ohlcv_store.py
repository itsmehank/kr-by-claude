from datetime import date

from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_close_only, upsert_index_daily


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_inserts_new_rows(db):
    _seed_stock(db)
    rows = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 1000, 70_500_000)]
    affected = upsert_daily_prices(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT close, adj_close FROM daily_prices WHERE ticker='005930' AND date='2026-05-12'")
        assert cur.fetchone() == (70500, 35250.0)


def test_upsert_updates_on_conflict(db):
    _seed_stock(db)
    rows_v1 = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 1000, 70_500_000)]
    upsert_daily_prices(db, rows_v1)
    rows_v2 = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70600, 35300.0, 1100, 77_660_000)]
    upsert_daily_prices(db, rows_v2)

    with db.cursor() as cur:
        cur.execute("SELECT close, adj_close, volume FROM daily_prices WHERE ticker='005930' AND date='2026-05-12'")
        assert cur.fetchone() == (70600, 35300.0, 1100)


def test_full_refresh_only_updates_adj_close(db):
    _seed_stock(db)
    rows = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 1000, 70_500_000)]
    upsert_daily_prices(db, rows)

    affected = update_adj_close_only(db, [("005930", date(2026, 5, 12), 36000.0)])
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT close, adj_close, volume FROM daily_prices WHERE ticker='005930' AND date='2026-05-12'")
        # close, volume 안 바뀜. adj_close 만 바뀜.
        assert cur.fetchone() == (70500, 36000.0, 1000)


def test_full_refresh_skips_missing_rows(db):
    _seed_stock(db)
    affected = update_adj_close_only(db, [("005930", date(2026, 5, 12), 36000.0)])
    assert affected == 0


def test_upsert_index_daily(db):
    rows = [("1001", date(2026, 5, 12), 2500, 2520, 2490, 2510, None, None)]
    affected = upsert_index_daily(db, rows)
    assert affected == 1
