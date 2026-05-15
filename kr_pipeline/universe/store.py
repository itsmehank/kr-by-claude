from datetime import date
import pandas as pd
from psycopg import Connection


def upsert_stocks(conn: Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = [
        (r["ticker"], r["name"], r["market"], r.get("sector"))
        for _, r in df.iterrows()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO stocks (ticker, name, market, sector, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (ticker) DO UPDATE
               SET name = EXCLUDED.name,
                   market = EXCLUDED.market,
                   sector = EXCLUDED.sector,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount


def mark_delisted(conn: Connection, *, current_tickers: set[str], on_date: date) -> int:
    """현재 universe 에 없는, 아직 delisted_at 이 NULL 인 종목을 폐지 처리.

    Safety: current_tickers 가 비어 있으면 (fetch 실패 등) 아무것도 하지 않음.
    """
    if not current_tickers:
        return 0
    tickers_list = list(current_tickers)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE stocks
               SET delisted_at = %s, updated_at = NOW()
             WHERE delisted_at IS NULL
               AND ticker != ALL(%s)
            """,
            (on_date, tickers_list),
        )
        return cur.rowcount
