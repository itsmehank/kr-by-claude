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


def test_build_excludes_future_actions(db):
    """as_of_date 이후(미래)의 기업행위는 known_actions 에서 제외 — 백필 look-ahead 방지."""
    _seed_stock(db, "FUT")
    as_of = date(2024, 5, 4)  # 과거 토요일 기준 백필
    future = as_of + timedelta(weeks=10)  # 분석 시점 이후 발생
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO corporate_actions (ticker, event_date, event_type, ratio, dart_rcept_no, raw_disclosure_title)
               VALUES ('FUT', %s, 'stock_split', '50:1', '20240801000001', '주식분할결정')
               ON CONFLICT DO NOTHING""",
            (future,),
        )
    db.commit()
    result = build_corporate_actions(db, "FUT", lookback_years=5, as_of_date=as_of)
    assert result["known_corporate_actions"] == []


def test_build_future_split_not_in_12w(db):
    """as_of 이후 발생한 분할은 '최근 12주 내 분할' 플래그를 켜면 안 됨 (look-ahead bias)."""
    _seed_stock(db, "FUTRV")
    as_of = date(2024, 5, 4)
    future = as_of + timedelta(weeks=4)  # as_of-12주 ~ ∞ 조건엔 걸리지만 미래임
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO corporate_actions (ticker, event_date, event_type, ratio, dart_rcept_no, raw_disclosure_title)
               VALUES ('FUTRV', %s, 'reverse_split', '1:10', '20240601000001', '주식병합결정')
               ON CONFLICT DO NOTHING""",
            (future,),
        )
    db.commit()
    result = build_corporate_actions(db, "FUTRV", lookback_years=5, as_of_date=as_of)
    assert result["reverse_split_within_12w"] is False


def test_build_includes_action_on_as_of_date(db):
    """as_of_date 당일 이벤트는 포함 (경계 포함)."""
    _seed_stock(db, "ONDAY")
    as_of = date(2024, 5, 4)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO corporate_actions (ticker, event_date, event_type, ratio, dart_rcept_no, raw_disclosure_title)
               VALUES ('ONDAY', %s, 'stock_split', '50:1', '20240504000001', '주식분할결정')
               ON CONFLICT DO NOTHING""",
            (as_of,),
        )
    db.commit()
    result = build_corporate_actions(db, "ONDAY", lookback_years=5, as_of_date=as_of)
    assert len(result["known_corporate_actions"]) == 1
