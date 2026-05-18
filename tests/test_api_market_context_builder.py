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
            ON CONFLICT (date, index_code) DO NOTHING
            """
        )
    db.commit()

    result = build_market_context(db, market="KOSPI", on_date=date(2026, 5, 17))
    assert result["current_status"] == "confirmed_uptrend"
    assert result["distribution_day_count_last_25_sessions"] == 2
    assert result["last_follow_through_day"] == "2026-04-12"
    assert result["pct_stocks_above_200d_ma"] == 47.3


def test_build_market_context_missing_returns_none_dict(db):
    """on_date 이하 행이 하나도 없으면 모든 필드 null."""
    result = build_market_context(db, market="KOSPI", on_date=date(1999, 1, 1))
    assert result["current_status"] is None
    assert result["last_follow_through_day"] is None


def test_build_market_context_fallback_to_recent(db):
    """오늘 행 없으면 on_date 이하 가장 최근 평일 데이터로 fallback."""
    with db.cursor() as cur:
        # 테스트 격리 — 동일 KOSPI 행 정리
        cur.execute("DELETE FROM market_context_daily WHERE index_code = '1001' AND date BETWEEN '2026-05-10' AND '2026-05-20'")
        cur.execute(
            """
            INSERT INTO market_context_daily
              (date, index_code, current_status, distribution_day_count_last_25,
               last_follow_through_day, days_since_follow_through, pct_stocks_above_200d_ma, computation_notes)
            VALUES ('2026-05-15', '1001', 'under_pressure', 3, '2026-04-12', 33, 52.1, '{}')
            """
        )
    db.commit()

    # 5/18 조회 — 행 없음 → 5/15 fallback
    result = build_market_context(db, market="KOSPI", on_date=date(2026, 5, 18))
    assert result["current_status"] == "under_pressure"
    assert result["distribution_day_count_last_25_sessions"] == 3
    assert result["pct_stocks_above_200d_ma"] == 52.1
