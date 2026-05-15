from datetime import date
import pandas as pd

from kr_pipeline.universe.store import upsert_stocks, mark_delisted


def test_upsert_inserts_new_stocks(db):
    df = pd.DataFrame([
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "전기·전자"},
        {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI", "sector": "전기·전자"},
    ])
    affected = upsert_stocks(db, df)
    assert affected == 2

    with db.cursor() as cur:
        cur.execute("SELECT ticker, name, sector FROM stocks ORDER BY ticker")
        rows = cur.fetchall()
    assert rows == [
        ("000660", "SK하이닉스", "전기·전자"),
        ("005930", "삼성전자", "전기·전자"),
    ]


def test_upsert_updates_existing_stocks(db):
    df1 = pd.DataFrame([{"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "전기·전자"}])
    upsert_stocks(db, df1)

    df2 = pd.DataFrame([{"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "반도체"}])
    upsert_stocks(db, df2)

    with db.cursor() as cur:
        cur.execute("SELECT sector FROM stocks WHERE ticker = '005930'")
        assert cur.fetchone() == ("반도체",)


def test_mark_delisted_does_nothing_on_empty_tickers(db):
    """empty current_tickers (e.g., fetch failure) 에서 mass-delist 되지 않음."""
    df = pd.DataFrame([{"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None}])
    upsert_stocks(db, df)
    marked = mark_delisted(db, current_tickers=set(), on_date=date(2026, 5, 15))
    assert marked == 0
    with db.cursor() as cur:
        cur.execute("SELECT delisted_at FROM stocks WHERE ticker = '005930'")
        assert cur.fetchone() == (None,)


def test_mark_delisted_sets_date_for_missing_tickers(db):
    df_before = pd.DataFrame([
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None},
        {"ticker": "999999", "name": "폐지예정", "market": "KOSPI", "sector": None},
    ])
    upsert_stocks(db, df_before)

    df_after = pd.DataFrame([
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None},
    ])
    marked = mark_delisted(db, current_tickers=set(df_after["ticker"]), on_date=date(2026, 5, 15))
    assert marked == 1

    with db.cursor() as cur:
        cur.execute("SELECT delisted_at FROM stocks WHERE ticker = '999999'")
        assert cur.fetchone() == (date(2026, 5, 15),)
        cur.execute("SELECT delisted_at FROM stocks WHERE ticker = '005930'")
        assert cur.fetchone() == (None,)
