from datetime import date, timedelta
from freezegun import freeze_time

from kr_pipeline.weekly.modes import Mode, compute_date_range


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.FULL_REFRESH.value == "full-refresh"


@freeze_time("2026-05-18")  # Monday
def test_incremental_range_4_weeks():
    """today=Mon 5/18 → start=5/18 - 28일 = 4/20, end=today-1 = 5/17"""
    start, end = compute_date_range(Mode.INCREMENTAL, window_weeks=4)
    assert start == date(2026, 4, 20)
    assert end == date(2026, 5, 17)


@freeze_time("2026-05-18")
def test_incremental_default_window_is_4():
    start, end = compute_date_range(Mode.INCREMENTAL)
    assert (date(2026, 5, 18) - start).days == 28


def test_backfill_uses_db_min(monkeypatch):
    """backfill 은 DB 의 MIN(date) 를 시작점으로."""
    from kr_pipeline.weekly import modes
    monkeypatch.setattr(modes, "_get_daily_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        start, end = compute_date_range(Mode.BACKFILL, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 17)


def test_full_refresh_uses_db_min(monkeypatch):
    from kr_pipeline.weekly import modes
    monkeypatch.setattr(modes, "_get_daily_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        start, end = compute_date_range(Mode.FULL_REFRESH, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 17)


def test_unknown_mode_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown mode"):
        compute_date_range("oops")  # type: ignore


def test_run_isolates_exception_in_one_ticker(db, monkeypatch):
    """한 종목에서 예외 발생 → 다른 종목은 정상 적재, 실패 종목은 failures 기록.

    Tests the try/except + end-of-run retry path in weekly/modes.run().
    """
    from kr_pipeline.weekly import modes

    # Seed: 2 stocks + minimal daily data for both
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_prices")
        cur.execute("DELETE FROM weekly_index")
        cur.execute("DELETE FROM daily_prices")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('EXCTEST1', 'EXCTEST2')")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EXCTEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EXCTEST2', 'T2', 'KOSPI') ON CONFLICT DO NOTHING")
        # Both tickers get daily data for week 2026-05-04 ~ 2026-05-08 (completed week)
        from datetime import date
        for t in ("EXCTEST1", "EXCTEST2"):
            for d in [date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8)]:
                cur.execute(
                    "INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) "
                    "VALUES (%s, %s, 100, 110, 90, 105, 105.0, 1000, 105000)",
                    (t, d),
                )
    db.commit()

    try:
        # Patch _process_ticker to always raise for EXCTEST2, success for others
        original_process_ticker = modes._process_ticker
        call_log = []

        def faulty_process_ticker(conn, ticker, start, end, today):
            call_log.append(ticker)
            if ticker == "EXCTEST2":
                raise RuntimeError("simulated transient failure")
            return original_process_ticker(conn, ticker, start, end, today)

        monkeypatch.setattr(modes, "_process_ticker", faulty_process_ticker)

        stats = modes.run(db, modes.Mode.BACKFILL, limit_tickers=2)

        # EXCTEST2 should have been retried (1st pass + retry pass = 2 calls)
        excttest2_calls = [t for t in call_log if t == "EXCTEST2"]
        assert len(excttest2_calls) == 2, f"expected 2 calls for EXCTEST2, got {len(excttest2_calls)}"

        # Failure recorded
        assert len(stats.failures) == 1
        assert stats.failures[0][0] == "EXCTEST2"
        assert "simulated" in stats.failures[0][1]

        # EXCTEST1 still got processed → weekly_prices row exists for it
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker = 'EXCTEST1'")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker = 'EXCTEST2'")
            assert cur.fetchone()[0] == 0  # 실패했으므로 적재 안 됨
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_prices WHERE ticker LIKE 'EXCTEST%'")
            cur.execute("DELETE FROM weekly_index")
            cur.execute("DELETE FROM daily_prices WHERE ticker LIKE 'EXCTEST%'")
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'EXCTEST%'")
            cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'weekly'")
        db.commit()


def test_run_retry_succeeds_on_second_attempt(db, monkeypatch):
    """1차 시도 실패 → 끝-of-run 재시도 → 성공 → failures 비어있음.

    Verifies the end-of-run retry loop actually retries (not just records as failed).
    """
    from kr_pipeline.weekly import modes

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_prices")
        cur.execute("DELETE FROM daily_prices WHERE ticker LIKE 'RETRYTEST%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RETRYTEST%'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('RETRYTEST1', 'R1', 'KOSPI') ON CONFLICT DO NOTHING")
        from datetime import date
        for d in [date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8)]:
            cur.execute(
                "INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) "
                "VALUES ('RETRYTEST1', %s, 100, 110, 90, 105, 105.0, 1000, 105000)",
                (d,),
            )
    db.commit()

    try:
        original_process_ticker = modes._process_ticker
        attempt_count = {"n": 0}

        def flaky_process_ticker(conn, ticker, start, end, today):
            attempt_count["n"] += 1
            if attempt_count["n"] == 1:
                raise RuntimeError("first attempt fails")
            return original_process_ticker(conn, ticker, start, end, today)

        monkeypatch.setattr(modes, "_process_ticker", flaky_process_ticker)

        stats = modes.run(db, modes.Mode.BACKFILL, limit_tickers=1)

        assert attempt_count["n"] == 2  # 1차 실패 + 재시도 성공
        assert stats.failures == []  # 재시도 성공으로 failures 비어있음

        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker = 'RETRYTEST1'")
            assert cur.fetchone()[0] == 1
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_prices WHERE ticker LIKE 'RETRYTEST%'")
            cur.execute("DELETE FROM weekly_index")
            cur.execute("DELETE FROM daily_prices WHERE ticker LIKE 'RETRYTEST%'")
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RETRYTEST%'")
            cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'weekly'")
        db.commit()
