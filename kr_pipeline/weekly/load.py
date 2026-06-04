"""weekly 파이프라인 입력 로딩 — daily_prices / index_daily 에서 SELECT."""
from datetime import date

import pandas as pd
from psycopg import Connection


def load_daily_for_ticker(
    conn: Connection,
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """한 종목의 일봉을 기간 범위로 가져옴.

    return columns: date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value
              FROM daily_prices
             WHERE ticker = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (ticker, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def load_index_daily(
    conn: Connection,
    index_code: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """한 지수의 일봉을 기간 범위로 가져옴.

    return columns: date, open, high, low, close, volume, value, adj_close(=close)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, open, high, low, close, volume, value
              FROM index_daily
             WHERE index_code = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (index_code, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["adj_close"] = df["close"]
        df["adj_high"] = df["high"]
        df["adj_low"] = df["low"]
    return df


def load_active_tickers(conn: Connection, limit: int | None = None) -> list[str]:
    """active universe — delisted_at IS NULL 종목."""
    with conn.cursor() as cur:
        sql = "SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


def get_daily_min_date(conn: Connection) -> date | None:
    """daily_prices 의 가장 오래된 날짜. None 이면 빈 테이블."""
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(date) FROM daily_prices")
        row = cur.fetchone()
        return row[0] if row and row[0] else None
