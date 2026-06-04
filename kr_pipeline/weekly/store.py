"""weekly_prices / weekly_index UPSERT 헬퍼."""
from psycopg import Connection


def upsert_weekly_prices(conn: Connection, rows: list[tuple]) -> int:
    """
    rows: (ticker, week_end_date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, trading_days)
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO weekly_prices
              (ticker, week_end_date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, trading_days, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, week_end_date) DO UPDATE
               SET open = EXCLUDED.open,
                   high = EXCLUDED.high,
                   low = EXCLUDED.low,
                   close = EXCLUDED.close,
                   adj_close = EXCLUDED.adj_close,
                   adj_high = EXCLUDED.adj_high,
                   adj_low = EXCLUDED.adj_low,
                   adj_open = EXCLUDED.adj_open,
                   adj_volume = EXCLUDED.adj_volume,
                   volume = EXCLUDED.volume,
                   value = EXCLUDED.value,
                   trading_days = EXCLUDED.trading_days,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount


def upsert_weekly_index(conn: Connection, rows: list[tuple]) -> int:
    """
    rows: (index_code, week_end_date, open, high, low, close, volume, value, trading_days)
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO weekly_index
              (index_code, week_end_date, open, high, low, close, volume, value, trading_days, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (index_code, week_end_date) DO UPDATE
               SET open = EXCLUDED.open,
                   high = EXCLUDED.high,
                   low = EXCLUDED.low,
                   close = EXCLUDED.close,
                   volume = EXCLUDED.volume,
                   value = EXCLUDED.value,
                   trading_days = EXCLUDED.trading_days,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount
