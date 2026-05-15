# kr_pipeline/indicators/load.py
"""indicators 파이프라인 입력 SELECT 헬퍼."""
from datetime import date

import pandas as pd
from psycopg import Connection


def load_daily_prices(
    conn: Connection,
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """한 종목의 일봉 (date, adj_close, close, volume).

    V2: split-adjusted volume 계산 위해 close, volume 도 가져옴.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, adj_close, close, volume
              FROM daily_prices
             WHERE ticker = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (ticker, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["adj_close"] = df["adj_close"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
    return df


def load_index_daily(
    conn: Connection,
    index_code: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """지수 일봉 (date, close)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, close
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
        df["close"] = df["close"].astype(float)
    return df


def load_weekly_prices(conn: Connection, ticker: str, start: date, end: date) -> pd.DataFrame:
    """한 종목의 주봉 (date, adj_close, close, volume). V2: close, volume 추가."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT week_end_date AS date, adj_close, close, volume
              FROM weekly_prices
             WHERE ticker = %s AND week_end_date BETWEEN %s AND %s
             ORDER BY week_end_date
            """,
            (ticker, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["adj_close"] = df["adj_close"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
    return df


def load_weekly_index(conn: Connection, index_code: str, start: date, end: date) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT week_end_date AS date, close
              FROM weekly_index
             WHERE index_code = %s AND week_end_date BETWEEN %s AND %s
             ORDER BY week_end_date
            """,
            (index_code, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["close"] = df["close"].astype(float)
    return df


def load_active_tickers_with_market(conn: Connection, limit: int | None = None) -> list[tuple[str, str]]:
    """[(ticker, market), ...] — RS Line 벤치마크 결정용."""
    with conn.cursor() as cur:
        sql = "SELECT ticker, market FROM stocks WHERE delisted_at IS NULL ORDER BY ticker"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return [(r[0], r[1]) for r in cur.fetchall()]


def get_daily_prices_min_date(conn: Connection) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(date) FROM daily_prices")
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def get_weekly_prices_min_date(conn: Connection) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(week_end_date) FROM weekly_prices")
        row = cur.fetchone()
        return row[0] if row and row[0] else None
