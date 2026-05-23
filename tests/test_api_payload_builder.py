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
