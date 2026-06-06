from datetime import date
from api.services.payload_builder import build_payload


def _seed_full(db, ticker="PLD1"):
    """payload 빌더에 필요한 모든 테이블에 시드."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, sector) VALUES (%s, 'P', 'KOSPI', '전기·전자') ON CONFLICT DO NOTHING", (ticker,))
        cur.execute("""
            INSERT INTO daily_indicators
              (ticker, date, adj_close, volume, sma_50, sma_150, sma_200, w52_high, w52_low,
               rs_rating, minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5,
               minervini_c6, minervini_c7, minervini_c8, minervini_pass,
               avg_volume_50d, volume_ratio_50d)
            VALUES (%s, '2026-05-17', 80000, 12000000, 75000, 70000, 65000, 95000, 50000,
                    95, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, 11000000, 1.09)
            ON CONFLICT DO NOTHING
        """, (ticker,))
        cur.execute("""
            INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
            VALUES (%s, '2026-05-17', 79500, 80500, 79000, 80000, 80000, 12000000, 960000000000)
            ON CONFLICT DO NOTHING
        """, (ticker,))
    db.commit()


def test_build_payload_basic_structure(db):
    _seed_full(db)
    payload = build_payload(db, "PLD1", on_date=date(2026, 5, 17))

    assert payload["symbol"] == "PLD1"
    assert payload["market"] == "KOSPI"
    assert payload["date"] == "2026-05-17"

    assert "conditions_met" in payload
    assert "conditions_detail" in payload
    assert payload["rs_rating"] == 95

    assert payload["current_metrics"]["close"] == 80000.0
    assert payload["current_metrics"]["w52_high"] == 95000.0

    assert "market_context" in payload
    assert "price_data_notes" in payload


def test_build_payload_unknown_ticker(db):
    """존재 안 하는 종목 → ValueError."""
    import pytest
    with pytest.raises(ValueError, match="not found"):
        build_payload(db, "NOEXIST", on_date=date(2026, 5, 17))


def test_fetch_daily_ohlcv_uses_adjusted(db):
    from api.services.payload_builder import _fetch_daily_ohlcv
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ADJD','t','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("""INSERT INTO daily_prices
            (ticker,date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value)
            VALUES ('ADJD',%s,10000,10500,9800,10000,2000,2000,2100,1960,500.0,1000,10000000)
            ON CONFLICT DO NOTHING""", (date(2026,1,2),))
    db.commit()
    out = _fetch_daily_ohlcv(db, "ADJD", date(2026,1,31), days=60)
    assert len(out) == 1
    bar = out[0]
    assert bar["open"] == 2000.0 and bar["high"] == 2100.0
    assert bar["low"] == 1960.0 and bar["close"] == 2000.0
    assert bar["volume"] == 500   # adj_volume


def test_fetch_weekly_ohlcv_uses_adjusted(db):
    from api.services.payload_builder import _fetch_weekly_ohlcv
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ADJW','t','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("""INSERT INTO weekly_prices
            (ticker,week_end_date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value,trading_days)
            VALUES ('ADJW',%s,10000,10500,9800,10000,2000,2000,2100,1960,500.0,1000,10000000,5)
            ON CONFLICT DO NOTHING""", (date(2026,1,2),))
    db.commit()
    out = _fetch_weekly_ohlcv(db, "ADJW", date(2026,1,31), weeks=104)
    assert out[0]["open"] == 2000.0 and out[0]["high"] == 2100.0
    assert out[0]["low"] == 1960.0 and out[0]["close"] == 2000.0
    assert out[0]["volume"] == 500   # adj_volume (int(round(float)))
