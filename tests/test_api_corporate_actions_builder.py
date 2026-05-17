from datetime import date, timedelta
from api.services.corporate_actions_builder import build_corporate_actions


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성', 'KOSPI') ON CONFLICT DO NOTHING", (ticker,))


def test_build_no_actions(db):
    """이벤트 없는 종목 → 빈 리스트, 모든 12w flag False."""
    _seed_stock(db, "NOEVT")
    result = build_corporate_actions(db, "NOEVT", lookback_years=5, as_of_date=date(2026, 5, 17))
    assert result["known_corporate_actions"] == []
    assert result["reverse_split_within_12w"] is False
    assert result["forward_split_within_12w"] is False


def test_build_with_recent_reverse_split(db):
    """12주 이내 reverse_split → flag True."""
    _seed_stock(db, "RVSP")
    today = date(2026, 5, 17)
    recent = today - timedelta(weeks=8)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO corporate_actions (ticker, event_date, event_type, ratio, dart_rcept_no, raw_disclosure_title)
               VALUES ('RVSP', %s, 'reverse_split', '1:10', '20260101000001', '주식병합결정')
               ON CONFLICT DO NOTHING""",
            (recent,),
        )
    db.commit()
    result = build_corporate_actions(db, "RVSP", lookback_years=5, as_of_date=today)
    assert result["reverse_split_within_12w"] is True
    assert len(result["known_corporate_actions"]) == 1
    assert result["known_corporate_actions"][0]["type"] == "reverse_split"


def test_build_old_split_not_in_12w(db):
    """1년 전 stock_split → known_actions 포함, but forward_split_within_12w False."""
    _seed_stock(db, "OLD")
    today = date(2026, 5, 17)
    old = today - timedelta(weeks=52)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO corporate_actions (ticker, event_date, event_type, ratio, dart_rcept_no, raw_disclosure_title)
               VALUES ('OLD', %s, 'stock_split', '50:1', '20250101000001', '주식분할결정')
               ON CONFLICT DO NOTHING""",
            (old,),
        )
    db.commit()
    result = build_corporate_actions(db, "OLD", lookback_years=5, as_of_date=today)
    assert len(result["known_corporate_actions"]) == 1
    assert result["forward_split_within_12w"] is False
