from datetime import date
from datetime import date as date_cls
from freezegun import freeze_time
import pandas as pd

from kr_pipeline.ohlcv.modes import compute_date_range, Mode


@freeze_time("2026-05-15")
def test_backfill_range_for_2_years():
    start, end = compute_date_range(Mode.BACKFILL, years=2)
    assert start == date(2024, 5, 15)
    assert end == date(2026, 5, 14)


@freeze_time("2026-05-15")
def test_incremental_range_for_30_days():
    start, end = compute_date_range(Mode.INCREMENTAL, window_days=30)
    assert start == date(2026, 4, 15)
    assert end == date(2026, 5, 15)


def test_full_refresh_range_uses_db_min(monkeypatch):
    from kr_pipeline.ohlcv import modes
    monkeypatch.setattr(modes, "_get_db_min_date", lambda conn: date(2024, 1, 2))

    with freeze_time("2026-05-15"):
        start, end = compute_date_range(Mode.FULL_REFRESH, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 14)


def test_full_refresh_retries_failed_tickers_at_end(monkeypatch, db):
    """첫 시도에서 실패한 종목이 끝에서 한 번 더 시도되어 성공하면 failures 에 안 남음."""
    from kr_pipeline.ohlcv import modes

    # 시드: stocks 테이블에 종목 한 개 + daily_prices 한 행 (update 대상)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('005930', '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("""
            INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
            VALUES ('005930', '2026-05-12', 70000, 71000, 69500, 70500, 35250, 1000, 70500000)
            ON CONFLICT DO NOTHING
        """)
    db.commit()

    # fetch_adj_only mock: 첫 호출은 RuntimeError, 두 번째는 성공
    call_count = {"n": 0}

    def fake_fetch(ticker, start, end):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient")
        return pd.DataFrame([{"date": date_cls(2026, 5, 12), "close": 36000.0}])

    import kr_pipeline.ohlcv.fetch as fetch_mod
    monkeypatch.setattr(fetch_mod, "fetch_adj_only", fake_fetch)

    try:
        stats = modes._run_full_refresh(db, ["005930"], date_cls(2026, 5, 1), date_cls(2026, 5, 14), max_workers=1)

        assert call_count["n"] == 2  # 첫 시도 + 재시도
        assert stats.failures == []   # 재시도 성공으로 failures 비어있음
        assert stats.rows_affected == 1
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker = '005930' AND date = '2026-05-12'")
            cur.execute("DELETE FROM stocks WHERE ticker = '005930'")
        db.commit()


def test_full_refresh_records_persistent_failures(monkeypatch, db):
    """첫 시도 + 재시도 모두 실패하면 failures 에 기록."""
    from kr_pipeline.ohlcv import modes

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('005930', '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING")
    db.commit()

    def always_fail(ticker, start, end):
        raise RuntimeError("permanent")

    import kr_pipeline.ohlcv.fetch as fetch_mod
    monkeypatch.setattr(fetch_mod, "fetch_adj_only", always_fail)

    try:
        stats = modes._run_full_refresh(db, ["005930"], date_cls(2026, 5, 1), date_cls(2026, 5, 14), max_workers=1)

        assert len(stats.failures) == 1
        assert stats.failures[0][0] == "005930"
        assert "permanent" in stats.failures[0][1]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker = '005930'")
            cur.execute("DELETE FROM stocks WHERE ticker = '005930'")
        db.commit()
