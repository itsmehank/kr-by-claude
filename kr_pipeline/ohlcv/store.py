from psycopg import Connection


def upsert_daily_prices(conn: Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO daily_prices
              (ticker, date, open, high, low, close, adj_close, volume, value, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, date) DO UPDATE
               SET open = EXCLUDED.open,
                   high = EXCLUDED.high,
                   low = EXCLUDED.low,
                   close = EXCLUDED.close,
                   adj_close = EXCLUDED.adj_close,
                   volume = EXCLUDED.volume,
                   value = EXCLUDED.value,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount


def update_adj_close_only(conn: Connection, rows: list[tuple]) -> int:
    """full-refresh: (ticker, date, adj_close) 튜플로 adj_close 만 갱신. 없는 행은 무시."""
    if not rows:
        return 0
    affected = 0
    with conn.cursor() as cur:
        for ticker, dt, adj_close in rows:
            cur.execute(
                "UPDATE daily_prices SET adj_close = %s, updated_at = NOW() WHERE ticker = %s AND date = %s",
                (adj_close, ticker, dt),
            )
            affected += cur.rowcount
    return affected


def upsert_index_daily(conn: Connection, rows: list[tuple]) -> int:
    """rows: (index_code, date, open, high, low, close, volume, value)"""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (index_code, date) DO UPDATE
               SET open = EXCLUDED.open, high = EXCLUDED.high,
                   low = EXCLUDED.low, close = EXCLUDED.close,
                   volume = EXCLUDED.volume, value = EXCLUDED.value,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount
