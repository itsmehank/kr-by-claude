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


def test_as_of_date_present_when_exact_row(db):
    """B안: 요청일 행이 있으면 as_of_date = 요청일 (신선도 추적 필드)."""
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
    assert result["as_of_date"] == "2026-05-17"


def test_as_of_date_and_warning_on_fallback(db, caplog):
    """B안: 폴백 시 as_of_date = 실제 사용한 행 날짜 + warning 로그 1건."""
    import logging
    with db.cursor() as cur:
        cur.execute("DELETE FROM market_context_daily WHERE index_code = '1001' AND date BETWEEN '2026-05-10' AND '2026-05-20'")
        cur.execute(
            """
            INSERT INTO market_context_daily
              (date, index_code, current_status, distribution_day_count_last_25,
               last_follow_through_day, days_since_follow_through, pct_stocks_above_200d_ma, computation_notes)
            VALUES ('2026-05-15', '1001', 'correction', 3, '2026-04-12', 33, 52.1, '{}')
            """
        )
    db.commit()

    with caplog.at_level(logging.WARNING, logger="api.services.market_context_builder"):
        result = build_market_context(db, market="KOSPI", on_date=date(2026, 5, 18))

    assert result["as_of_date"] == "2026-05-15"
    fallback_logs = [r for r in caplog.records if "fallback" in r.message]
    assert len(fallback_logs) == 1


def test_as_of_date_none_when_no_rows(db):
    """B안: 행이 하나도 없으면 as_of_date 도 None."""
    result = build_market_context(db, market="KOSPI", on_date=date(1999, 1, 1))
    assert result["as_of_date"] is None
