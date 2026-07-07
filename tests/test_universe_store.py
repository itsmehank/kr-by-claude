from datetime import date
import numpy as np
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


def test_upsert_normalizes_nan_sector_to_null(db):
    """sector 컬럼이 NaN/None 이면 SQL NULL 로 저장되어야 함."""
    df = pd.DataFrame([
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": np.nan},
        {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI", "sector": None},
    ])
    upsert_stocks(db, df)
    with db.cursor() as cur:
        cur.execute("SELECT ticker, sector FROM stocks ORDER BY ticker")
        rows = cur.fetchall()
    assert rows == [("000660", None), ("005930", None)]


def test_mark_delisted_sets_date_for_missing_tickers(db):
    df_before = pd.DataFrame([
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None},
        {"ticker": "999999", "name": "폐지예정", "market": "KOSPI", "sector": None},
    ])
    upsert_stocks(db, df_before)

    # 대량 오폐지 가드(_MAX_DELIST_RATIO=2%) 도입 후 계약: current_tickers 는
    # '활성 전체에서 폐지분만 빠진' 집합. 활성 규모를 filler 로 확보해
    # 1건 폐지가 상한 이하가 되게 한다 (rollback 격리라 잔존 없음).
    filler = pd.DataFrame([
        {"ticker": f"F{i:05d}", "name": "필러", "market": "KOSPI", "sector": None}
        for i in range(60)
    ])
    upsert_stocks(db, filler)
    with db.cursor() as cur:
        cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NULL")
        active = {r[0] for r in cur.fetchall()}

    marked = mark_delisted(db, current_tickers=active - {"999999"}, on_date=date(2026, 5, 15))
    assert marked == 1

    with db.cursor() as cur:
        cur.execute("SELECT delisted_at FROM stocks WHERE ticker = '999999'")
        assert cur.fetchone() == (date(2026, 5, 15),)
        cur.execute("SELECT delisted_at FROM stocks WHERE ticker = '005930'")
        assert cur.fetchone() == (None,)


def test_upsert_does_not_wipe_existing_sector_with_null(db):
    """sector=None 으로 들어오면 기존 값을 유지해야 함."""
    df1 = pd.DataFrame([{"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "전기·전자"}])
    upsert_stocks(db, df1)

    df2 = pd.DataFrame([{"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None}])
    upsert_stocks(db, df2)

    with db.cursor() as cur:
        cur.execute("SELECT sector FROM stocks WHERE ticker = '005930'")
        assert cur.fetchone() == ("전기·전자",)


def test_upsert_clears_delisted_at_when_ticker_reappears(db):
    """delisted_at 이 세팅됐던 종목이 universe 에 다시 나타나면 NULL 로 복구."""
    df = pd.DataFrame([{"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None}])
    upsert_stocks(db, df)

    # 한 번 delist
    mark_delisted(db, current_tickers=set(), on_date=date(2026, 5, 15))  # empty: should NOT delist (guard)
    # 강제로 delisted_at 설정
    with db.cursor() as cur:
        cur.execute("UPDATE stocks SET delisted_at = '2026-01-01' WHERE ticker = '005930'")

    # 다시 universe 에 등장
    upsert_stocks(db, df)

    with db.cursor() as cur:
        cur.execute("SELECT delisted_at FROM stocks WHERE ticker = '005930'")
        assert cur.fetchone() == (None,)
