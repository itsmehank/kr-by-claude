from datetime import date
import pytest


def _seed_prices(cur, n_rows, *, d=date(2099, 7, 1)):
    """sentinel 미래 날짜 d 에 n_rows 개 종목의 daily_prices 행 시드(MAX(date)=d 보장).

    daily_prices.ticker 는 stocks(ticker) 로 FK → 각 ticker 를 stocks 에 먼저 INSERT 필수.
    """
    for i in range(n_rows):
        t = f"CMP{i:04d}"
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING",
            (t,),
        )
        cur.execute(
            "INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
            "VALUES (%s,%s,100,100,100,100,100,1000,100000) ON CONFLICT DO NOTHING",
            (t, d),
        )


def test_complete_passes(db):
    from kr_pipeline.indicators.completeness import check_daily_ohlcv_complete
    with db.cursor() as cur:
        _seed_prices(cur, 10)
    check_daily_ohlcv_complete(db, active_count=10)


def test_partial_raises(db):
    from kr_pipeline.indicators.completeness import (
        check_daily_ohlcv_complete, IncompleteIngestionError)
    with db.cursor() as cur:
        _seed_prices(cur, 1)
    with pytest.raises(IncompleteIngestionError):
        check_daily_ohlcv_complete(db, active_count=10)


def test_threshold_boundary_passes(db):
    from kr_pipeline.indicators.completeness import check_daily_ohlcv_complete
    with db.cursor() as cur:
        _seed_prices(cur, 9)
    check_daily_ohlcv_complete(db, active_count=10)


def test_just_below_threshold_raises(db):
    from kr_pipeline.indicators.completeness import (
        check_daily_ohlcv_complete, IncompleteIngestionError)
    with db.cursor() as cur:
        _seed_prices(cur, 89)
    with pytest.raises(IncompleteIngestionError):
        check_daily_ohlcv_complete(db, active_count=100)


def test_zero_active_raises(db):
    from kr_pipeline.indicators.completeness import (
        check_daily_ohlcv_complete, IncompleteIngestionError)
    with pytest.raises(IncompleteIngestionError):
        check_daily_ohlcv_complete(db, active_count=0)
