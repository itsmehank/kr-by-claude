from datetime import date

from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_prices, upsert_index_daily, update_change_pct


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


def test_upsert_persists_change_pct_and_keeps_previous_when_null(db):
    """#207: change_pct 저장 + 재적재가 NULL 이면 기존 값 보존(COALESCE) — 등락률 없는 경로가 값을 지우지 않는다."""
    _seed_stock(db)
    row = ("005930", date(2026, 9, 14), 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 1000.0, 1000, 105000, 2.5)
    upsert_daily_prices(db, [row])
    with db.cursor() as cur:
        cur.execute("SELECT change_pct FROM daily_prices WHERE ticker='005930' AND date='2026-09-14'")
        assert float(cur.fetchone()[0]) == 2.5
    upsert_daily_prices(db, [row[:13] + (None,)])
    with db.cursor() as cur:
        cur.execute("SELECT change_pct, close FROM daily_prices WHERE ticker='005930' AND date='2026-09-14'")
        cp, close = cur.fetchone()
        assert float(cp) == 2.5 and close == 105


def test_upsert_accepts_legacy_13_tuple(db):
    """구 호출처(13-튜플) 호환 — change_pct NULL 로 적재."""
    _seed_stock(db)
    upsert_daily_prices(db, [("005930", date(2026, 9, 15), 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 1000.0, 1000, 105000)])
    with db.cursor() as cur:
        cur.execute("SELECT change_pct FROM daily_prices WHERE ticker='005930' AND date='2026-09-15'")
        assert cur.fetchone()[0] is None


def test_update_change_pct_only_touches_change_pct(db):
    """#207 백필: (ticker, date, change_pct) 로 change_pct 만 갱신 — OHLCV·adj_* 불변, 매칭 없는 행 무시."""
    _seed_stock(db)
    upsert_daily_prices(db, [("005930", date(2026, 9, 14), 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 1000.0, 1000, 105000)])
    n = update_change_pct(db, [("005930", date(2026, 9, 14), -1.25), ("005930", date(2026, 9, 15), 3.0)])
    assert n == 1
    with db.cursor() as cur:
        cur.execute("SELECT change_pct, close, adj_close FROM daily_prices WHERE ticker='005930' AND date='2026-09-14'")
        cp, close, adj = cur.fetchone()
        assert float(cp) == -1.25 and close == 105 and adj == 105.0


def test_update_change_pct_dedupes_duplicate_keys(db):
    """#207 백필 사고(09-27): 스냅샷(날짜별)과 per-ticker(종목별) 수집이 같은 (ticker,date) 를 두 번 내면
    TEMP PK 위반으로 전체 롤백 → 접촉 결과 유실. 중복은 마지막 값으로 합쳐 적재한다."""
    _seed_stock(db)
    upsert_daily_prices(db, [("005930", date(2026, 9, 14), 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 1000.0, 1000, 105000)])
    n = update_change_pct(db, [("005930", date(2026, 9, 14), -1.25), ("005930", date(2026, 9, 14), -1.25)])
    assert n == 1


def test_upsert_adj_from_preserves_adj_before_date(db):
    """#207: adj_from 이전 날짜 행은 충돌 시 raw 만 갱신(adj_* 보존), 이후 행은 adj 도 갱신."""
    _seed_stock(db)
    base = ("005930", date(2026, 9, 11), 100, 110, 90, 105, 50.0, 55.0, 45.0, 50.0, 2000.0, 1000, 105000, None)
    upsert_daily_prices(db, [base, base[:1] + (date(2026, 9, 14),) + base[2:]])
    upd = ("005930", date(2026, 9, 11), 100, 110, 90, 106, 106.0, 110.0, 90.0, 100.0, 1000.0, 1000, 106000, 1.0)
    upd2 = upd[:1] + (date(2026, 9, 14),) + upd[2:]
    upsert_daily_prices(db, [upd, upd2], adj_from=date(2026, 9, 14))
    with db.cursor() as cur:
        cur.execute("SELECT date, close, adj_close, adj_volume FROM daily_prices WHERE ticker='005930' ORDER BY 1")
        assert [(d, c, float(a), float(v)) for d, c, a, v in cur.fetchall()] == [
            (date(2026, 9, 11), 106, 50.0, 2000.0), (date(2026, 9, 14), 106, 106.0, 1000.0)]


def test_update_adj_prices_twice_in_one_transaction(db):
    """#207 재산출 크래시(09-26): TEMP TABLE _adj_updates 가 ON COMMIT DROP 이라 한 트랜잭션 안에서 두 번째 호출이
    DuplicateTable — 종목 16개를 커밋 전에 순회하는 ingest_events 경로에서 재현. 호출마다 정리해야 한다."""
    _seed_stock(db)
    upsert_daily_prices(db, [("005930", date(2026, 9, 14), 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 1000.0, 1000, 105000)])
    assert update_adj_prices(db, [("005930", date(2026, 9, 14), 210.0, 220.0, 180.0, 200.0, 500.0)]) == 1
    assert update_adj_prices(db, [("005930", date(2026, 9, 14), 420.0, 440.0, 360.0, 400.0, 250.0)]) == 1
    with db.cursor() as cur:
        cur.execute("SELECT adj_close FROM daily_prices WHERE ticker='005930' AND date='2026-09-14'")
        assert float(cur.fetchone()[0]) == 420.0
