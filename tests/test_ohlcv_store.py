from datetime import date

from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_prices, upsert_index_daily


def test_warn_unnormalized_halt_detects_and_logs(caplog):
    """tripwire: chokepoint(nullify_halt_adj) 우회로 halt 패턴(adj OHLV=0·close>0) 행이
    store 에 도달하면 경고+카운트 반환. 정규화(None)·정상 행은 미탐지(데이터 변경 없음)."""
    from kr_pipeline.ohlcv.store import _warn_unnormalized_halt
    rows = [
        ("AAA", date(2024, 1, 2), 10.0, 11.0, 8.0, 9.0, 100.0),    # 정상 거래
        ("AAA", date(2024, 1, 3), 10.0, 0, 0, 0, 0),                # halt 미정규화 → 탐지
        ("AAA", date(2024, 1, 4), 10.0, None, None, None, None),    # 정규화됨 → 미탐지
    ]
    with caplog.at_level("WARNING"):
        n = _warn_unnormalized_halt(rows)
    assert n == 1
    assert "halt" in caplog.text.lower()


def test_warn_unnormalized_halt_clean_no_warning(caplog):
    from kr_pipeline.ohlcv.store import _warn_unnormalized_halt
    rows = [("AAA", date(2024, 1, 2), 10.0, 11.0, 8.0, 9.0, 100.0)]
    with caplog.at_level("WARNING"):
        n = _warn_unnormalized_halt(rows)
    assert n == 0
    assert "halt" not in caplog.text.lower()


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_inserts_new_rows(db):
    _seed_stock(db)
    rows = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 35500.0, 34750.0, 35000.0, 2000.0, 1000, 70_500_000)]
    affected = upsert_daily_prices(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT close, adj_close FROM daily_prices WHERE ticker='005930' AND date='2026-05-12'")
        assert cur.fetchone() == (70500, 35250.0)


def test_upsert_updates_on_conflict(db):
    _seed_stock(db)
    rows_v1 = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 35500.0, 34750.0, 35000.0, 2000.0, 1000, 70_500_000)]
    upsert_daily_prices(db, rows_v1)
    rows_v2 = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70600, 35300.0, 35550.0, 34800.0, 35100.0, 2100.0, 1100, 77_660_000)]
    upsert_daily_prices(db, rows_v2)

    with db.cursor() as cur:
        cur.execute("SELECT close, adj_close, volume FROM daily_prices WHERE ticker='005930' AND date='2026-05-12'")
        assert cur.fetchone() == (70600, 35300.0, 1100)


def test_full_refresh_only_updates_adj_prices(db):
    _seed_stock(db)
    rows = [("005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 35500.0, 34750.0, 35000.0, 2000.0, 1000, 70_500_000)]
    upsert_daily_prices(db, rows)

    affected = update_adj_prices(db, [("005930", date(2026, 5, 12), 36000.0, 36300.0, 35700.0, 35800.0, 2000.0)])
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT close, adj_close, volume FROM daily_prices WHERE ticker='005930' AND date='2026-05-12'")
        # close, volume 안 바뀜. adj_close 만 바뀜.
        assert cur.fetchone() == (70500, 36000.0, 1000)


def test_full_refresh_skips_missing_rows(db):
    _seed_stock(db)
    affected = update_adj_prices(db, [("005930", date(2026, 5, 12), 36000.0, 36300.0, 35700.0, 35800.0, 2000.0)])
    assert affected == 0


def test_update_adj_prices_updates_high_low(db):
    from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_prices
    from datetime import date
    _seed_stock(db, "005930")
    upsert_daily_prices(db, [(
        "005930", date(2026, 5, 12), 70000, 71000, 69500, 70500,
        35250.0, 35500.0, 34750.0, 35000.0, 2000.0, 1000, 70_500_000
    )])
    update_adj_prices(db, [("005930", date(2026, 5, 12), 30000.0, 30300.0, 29800.0, 29900.0, 1500.0)])
    with db.cursor() as cur:
        cur.execute("SELECT adj_close, adj_high, adj_low FROM daily_prices "
                    "WHERE ticker='005930' AND date='2026-05-12'")
        assert cur.fetchone() == (30000.0, 30300.0, 29800.0)


def test_upsert_index_daily(db):
    rows = [("1001", date(2026, 5, 12), 2500, 2520, 2490, 2510, None, None)]
    affected = upsert_index_daily(db, rows)
    assert affected == 1


def test_update_adj_prices_updates_adj_open_volume(db):
    from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_prices
    from datetime import date
    d = date(2025, 1, 3)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ADJ2','A','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM daily_prices WHERE ticker='ADJ2'")
    db.commit()
    # ticker,date,open,high,low,close,adj_close,adj_high,adj_low,adj_open,adj_volume,volume,value
    upsert_daily_prices(db, [("ADJ2", d, 100,110,90,105, 105.0,110.0,90.0,100.0,1000.0,1000,105000)])
    db.commit()
    # (ticker,date,adj_close,adj_high,adj_low,adj_open,adj_volume)
    update_adj_prices(db, [("ADJ2", d, 21.0, 22.0, 18.0, 20.0, 5000.0)])
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT adj_close,adj_high,adj_low,adj_open,adj_volume FROM daily_prices WHERE ticker='ADJ2' AND date=%s",(d,))
            r = cur.fetchone()
        assert [float(x) for x in r] == [21.0, 22.0, 18.0, 20.0, 5000.0]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker='ADJ2'")
        db.commit()


def test_upsert_daily_prices_stores_adj_open_volume(db):
    from kr_pipeline.ohlcv.store import upsert_daily_prices
    from datetime import date
    _seed_stock(db, "ADJ1")
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_prices WHERE ticker='ADJ1'")
    db.commit()
    # 튜플: ticker,date,open,high,low,close,adj_close,adj_high,adj_low,adj_open,adj_volume,volume,value
    rows = [("ADJ1", date(2025,1,2), 100,110,90,105, 21.0, 22.0, 18.0, 20.0, 5000.0, 1000, 105000)]
    upsert_daily_prices(db, rows)
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT adj_open, adj_volume FROM daily_prices WHERE ticker='ADJ1' AND date=%s", (date(2025,1,2),))
            r = cur.fetchone()
        assert float(r[0]) == 20.0 and float(r[1]) == 5000.0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker='ADJ1'")
        db.commit()
