from datetime import date
from api.services.market_context_builder import build_market_context


def test_build_market_context_kospi(db):
    """market_context_daily 의 KOSPI row 조회."""
    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market_context_daily
              (date, index_code, current_status, distribution_day_count_last_25,
               last_follow_through_day, days_since_follow_through, pct_stocks_above_200d_ma, computation_notes)
            VALUES ('2026-05-17', '1001', 'confirmed_uptrend', 2, '2026-04-12', 35, 47.3, '{}')
            """
        )
    db.commit()

    result = build_market_context(db, market="KOSPI", on_date=date(2026, 5, 17))
    assert result["current_status"] == "confirmed_uptrend"
    assert result["distribution_day_count_last_25_sessions"] == 2
    assert result["last_follow_through_day"] == "2026-04-12"
    assert result["pct_stocks_above_200d_ma"] == 47.3


def test_build_market_context_missing_returns_none_dict(db):
    """해당 (market, date) 행 없으면 모든 필드 null."""
    result = build_market_context(db, market="KOSPI", on_date=date(1999, 1, 1))
    assert result["current_status"] is None
    assert result["last_follow_through_day"] is None
