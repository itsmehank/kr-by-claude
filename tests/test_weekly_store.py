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
        100, 130, 95, 125, 125.0, 130.0, 95.0, 100.0, 6000.0, 6000, 679000, 5,
    )]
    affected = upsert_weekly_prices(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT close, adj_close, adj_high, adj_low, trading_days FROM weekly_prices "
            "WHERE ticker = '005930' AND week_end_date = '2026-05-15'"
        )
        assert cur.fetchone() == (125, 125.0, 130.0, 95.0, 5)


def test_upsert_weekly_prices_updates_on_conflict(db):
    _seed_stock(db)
    rows_v1 = [("005930", date(2026, 5, 15), 100, 130, 95, 125, 125.0, 130.0, 95.0, 100.0, 6000.0, 6000, 679000, 5)]
    upsert_weekly_prices(db, rows_v1)
    rows_v2 = [("005930", date(2026, 5, 15), 100, 135, 90, 128, 128.0, 135.0, 90.0, 100.0, 7000.0, 7000, 800000, 5)]
    upsert_weekly_prices(db, rows_v2)

    with db.cursor() as cur:
        cur.execute(
            "SELECT high, low, close, adj_close, adj_high, adj_low, volume FROM weekly_prices "
            "WHERE ticker = '005930' AND week_end_date = '2026-05-15'"
        )
        assert cur.fetchone() == (135, 90, 128, 128.0, 135.0, 90.0, 7000)


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


def test_delete_superseded_weekly_prices_removes_partial_row(db):
    """같은 ISO 주에 더 이른 week_end_date 의 부분집계 행(고아)이 있으면 삭제.

    production 사고: 일봉이 화요일까지만 적재된 상태에서 집계 → week_end=화(td=2)
    행 기록 → 완전한 데이터로 재집계 시 week_end=금 행이 *새로* 들어가고 화 행이
    영구 잔존(597종목 실측)."""
    from kr_pipeline.weekly.store import delete_superseded_weekly_prices
    _seed_stock(db, "ORPH1")
    partial = [("ORPH1", date(2026, 6, 2), 100, 110, 95, 105, 105.0, 110.0, 95.0, 100.0, 2000.0, 2000, 1, 2)]
    full = [("ORPH1", date(2026, 6, 5), 100, 130, 95, 125, 125.0, 130.0, 95.0, 100.0, 6000.0, 6000, 2, 4)]
    upsert_weekly_prices(db, partial)
    upsert_weekly_prices(db, full)

    deleted = delete_superseded_weekly_prices(db, "ORPH1", [date(2026, 6, 5)])

    assert deleted == 1
    with db.cursor() as cur:
        cur.execute("SELECT week_end_date FROM weekly_prices WHERE ticker='ORPH1' ORDER BY week_end_date")
        assert [r[0] for r in cur.fetchall()] == [date(2026, 6, 5)]


def test_delete_superseded_does_not_touch_other_weeks(db):
    """다른 ISO 주의 행은 건드리지 않는다."""
    from kr_pipeline.weekly.store import delete_superseded_weekly_prices
    _seed_stock(db, "ORPH2")
    prev_week = [("ORPH2", date(2026, 5, 29), 100, 110, 95, 105, 105.0, 110.0, 95.0, 100.0, 5000.0, 5000, 1, 5)]
    this_week = [("ORPH2", date(2026, 6, 5), 100, 130, 95, 125, 125.0, 130.0, 95.0, 100.0, 6000.0, 6000, 2, 4)]
    upsert_weekly_prices(db, prev_week)
    upsert_weekly_prices(db, this_week)

    deleted = delete_superseded_weekly_prices(db, "ORPH2", [date(2026, 6, 5)])

    assert deleted == 0
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker='ORPH2'")
        assert cur.fetchone()[0] == 2


def test_delete_superseded_weekly_index_removes_partial_row(db):
    """weekly_index 도 동일한 고아 정리 (지수 4건 실측)."""
    from kr_pipeline.weekly.store import delete_superseded_weekly_index
    partial = [("9901", date(2026, 6, 2), 2500, 2520, 2490, 2510, 1000, 1, 2)]
    full = [("9901", date(2026, 6, 5), 2500, 2540, 2480, 2530, 5000, 5, 4)]
    upsert_weekly_index(db, partial)
    upsert_weekly_index(db, full)

    deleted = delete_superseded_weekly_index(db, "9901", [date(2026, 6, 5)])

    assert deleted == 1
    with db.cursor() as cur:
        cur.execute("SELECT week_end_date FROM weekly_index WHERE index_code='9901' ORDER BY week_end_date")
        assert [r[0] for r in cur.fetchall()] == [date(2026, 6, 5)]
        cur.execute("DELETE FROM weekly_index WHERE index_code='9901'")
    db.commit()
