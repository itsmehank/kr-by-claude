"""tests/test_api_indicators_series.py — 차트 시리즈 엔드포인트 adjusted 가격 검증.

라우터 함수를 직접 호출해 반환 모델의 모든 필드 매핑을 확인(positional 인덱스 밀림 탐지).
"""
from datetime import date


def _seed_daily(db, ticker="SPLIT"):
    """분할종목: raw ≠ adj 로 시드 + adj NULL 행(COALESCE fallback) 1건."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '분할', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )
        cur.execute(
            """INSERT INTO daily_prices
               (ticker, date, open, high, low, close, adj_close, adj_open, adj_high, adj_low, adj_volume, volume, value)
               VALUES (%s, %s, 10000, 10500, 9800, 10000, 2000, 2000, 2100, 1960, 5000.5, 1000, 10000000)
               ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 2)),
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, sma_50, volume_ratio_50d, distribution_day_flag)
               VALUES (%s, %s, 2000, 1950, 1.5, TRUE) ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 2)),
        )
        cur.execute(
            """INSERT INTO daily_prices
               (ticker, date, open, high, low, close, adj_close, volume, value)
               VALUES (%s, %s, 11000, 11200, 10800, 11000, 11000, 1500, 16500000)
               ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 5)),
        )
        cur.execute(
            """INSERT INTO daily_indicators (ticker, date, adj_close)
               VALUES (%s, %s, 11000) ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 5)),
        )
    db.commit()


def test_get_daily_returns_adjusted_ohlcv(db):
    from api.routers.indicators import get_daily
    _seed_daily(db)
    out = get_daily("SPLIT", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)
    assert len(out) == 2
    r1 = out[0]
    assert r1.adj_open == 2000.0
    assert r1.adj_high == 2100.0
    assert r1.adj_low == 1960.0
    assert r1.adj_volume == 5000.5
    assert r1.adj_close == 2000.0
    assert r1.open == 10000.0 and r1.close == 10000.0


def test_get_daily_positional_mapping_intact(db):
    from api.routers.indicators import get_daily
    _seed_daily(db)
    r1 = get_daily("SPLIT", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)[0]
    assert r1.sma_50 == 1950.0
    assert r1.volume_ratio_50d == 1.5
    assert r1.distribution_day_flag is True


def test_get_daily_adj_null_falls_back_to_raw(db):
    from api.routers.indicators import get_daily
    _seed_daily(db)
    r2 = get_daily("SPLIT", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)[1]
    assert r2.adj_open == 11000.0
    assert r2.adj_high == 11200.0
    assert r2.adj_low == 10800.0
    assert r2.adj_volume == 1500.0


def _seed_weekly(db, ticker="SPLITW"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '분할주봉', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )
        cur.execute(
            """INSERT INTO weekly_prices
               (ticker, week_end_date, open, high, low, close, adj_close, adj_open, adj_high, adj_low, adj_volume, volume, value, trading_days)
               VALUES (%s, %s, 10000, 10500, 9800, 10000, 2000, 2000, 2100, 1960, 5000.5, 1000, 10000000, 5)
               ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 2)),
        )
        cur.execute(
            """INSERT INTO weekly_indicators
               (ticker, week_end_date, adj_close, sma_10w, minervini_pass)
               VALUES (%s, %s, 2000, 1950, TRUE) ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 2)),
        )
        cur.execute(
            """INSERT INTO weekly_prices
               (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days)
               VALUES (%s, %s, 11000, 11200, 10800, 11000, 11000, 1500, 16500000, 5)
               ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 9)),
        )
        cur.execute(
            """INSERT INTO weekly_indicators (ticker, week_end_date, adj_close)
               VALUES (%s, %s, 11000) ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 9)),
        )
    db.commit()


def test_get_weekly_returns_adjusted_ohlcv(db):
    from api.routers.indicators import get_weekly
    _seed_weekly(db)
    out = get_weekly("SPLITW", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)
    assert len(out) == 2
    r1 = out[0]
    assert r1.adj_open == 2000.0
    assert r1.adj_high == 2100.0
    assert r1.adj_low == 1960.0
    assert r1.adj_volume == 5000.5
    assert r1.adj_close == 2000.0
    assert r1.open == 10000.0 and r1.close == 10000.0
    assert r1.sma_10w == 1950.0
    assert r1.minervini_pass is True


def test_get_weekly_adj_null_falls_back_to_raw(db):
    from api.routers.indicators import get_weekly
    _seed_weekly(db)
    r2 = get_weekly("SPLITW", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)[1]
    assert r2.adj_open == 11000.0
    assert r2.adj_high == 11200.0
    assert r2.adj_low == 10800.0
    assert r2.adj_volume == 1500.0
