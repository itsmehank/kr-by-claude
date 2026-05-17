from datetime import date
from kr_pipeline.corporate_actions.store import upsert_corporate_actions


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_inserts_new_event(db):
    _seed_stock(db)
    rows = [{
        "ticker": "005930",
        "event_date": date(2024, 3, 12),
        "event_type": "stock_split",
        "ratio": "50:1",
        "note": None,
        "dart_rcept_no": "20240312000123",
        "raw_disclosure_title": "주식분할결정",
    }]
    affected = upsert_corporate_actions(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT event_type, ratio FROM corporate_actions WHERE ticker = '005930'")
        assert cur.fetchone() == ("stock_split", "50:1")


def test_upsert_updates_on_conflict(db):
    """같은 (ticker, event_date, event_type, dart_rcept_no) → note / raw_title 만 갱신."""
    _seed_stock(db)
    rows_v1 = [{
        "ticker": "005930", "event_date": date(2024, 3, 12), "event_type": "stock_split",
        "ratio": "50:1", "note": None, "dart_rcept_no": "20240312000123",
        "raw_disclosure_title": "주식분할결정",
    }]
    upsert_corporate_actions(db, rows_v1)

    rows_v2 = [dict(rows_v1[0], note="액면금액 5,000원 → 100원", raw_disclosure_title="[기재정정]주식분할결정")]
    upsert_corporate_actions(db, rows_v2)

    with db.cursor() as cur:
        cur.execute("SELECT note, raw_disclosure_title FROM corporate_actions WHERE ticker='005930'")
        assert cur.fetchone() == ("액면금액 5,000원 → 100원", "[기재정정]주식분할결정")


def test_upsert_empty_returns_zero(db):
    affected = upsert_corporate_actions(db, [])
    assert affected == 0
