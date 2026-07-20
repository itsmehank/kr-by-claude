# kr_pipeline/market_context/load.py
"""market_context 파이프라인 입력 SELECT 헬퍼."""
from datetime import date

import pandas as pd
from psycopg import Connection


def load_index_daily_with_sma200(
    conn: Connection,
    index_code: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """지수 일봉 + 지수 자체의 SMA50, SMA200, high, low, yearly_high 시계열.

    index_daily 에는 sma 가 없으므로, 함수 내에서 rolling 으로 직접 계산.
    high/low 는 stalling 분배일 판정(일중 마감 위치, 이슈 #55)에 사용.

    return columns: date, close, volume, high, low, sma_50, sma_200, yearly_high
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, close, volume, high, low
              FROM index_daily
             WHERE index_code = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (index_code, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["sma_50"] = df["close"].rolling(window=50, min_periods=50).mean()
    df["sma_200"] = df["close"].rolling(window=200, min_periods=200).mean()
    df["yearly_high"] = df["close"].rolling(window=252, min_periods=1).max()
    return df


def load_market_daily_indicators(
    conn: Connection,
    market: str,
    on_date: date,
) -> list[dict]:
    """특정 시장 (KOSPI/KOSDAQ) 의 활성 종목들의 (adj_close, sma_200) at on_date.

    breadth 계산용.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.adj_close, i.sma_200
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date = %s
               AND s.market = %s
               AND s.delisted_at IS NULL
            """,
            (on_date, market),
        )
        return [{"adj_close": float(r[0]) if r[0] is not None else None,
                 "sma_200": float(r[1]) if r[1] is not None else None}
                for r in cur.fetchall()]


def get_index_min_date(conn: Connection, index_code: str) -> date | None:
    """index_daily 의 해당 index 가장 오래된 날짜."""
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(date) FROM index_daily WHERE index_code = %s", (index_code,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
