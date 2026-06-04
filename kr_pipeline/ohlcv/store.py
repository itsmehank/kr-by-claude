from psycopg import Connection


def upsert_daily_prices(conn: Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO daily_prices
              (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, date) DO UPDATE
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
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount


def update_adj_prices(conn: Connection, rows: list[tuple]) -> int:
    """full-refresh: (ticker, date, adj_close, adj_high, adj_low) 튜플로 수정 OHLC 3종 갱신.

    TEMP TABLE + JOIN-UPDATE. 매칭 없는 행은 무시.
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE _adj_updates (
                ticker     VARCHAR(10)   NOT NULL,
                date       DATE          NOT NULL,
                adj_close  NUMERIC(12,4) NOT NULL,
                adj_high   NUMERIC(12,4),
                adj_low    NUMERIC(12,4),
                PRIMARY KEY (ticker, date)
            ) ON COMMIT DROP
        """)
        cur.executemany(
            "INSERT INTO _adj_updates (ticker, date, adj_close, adj_high, adj_low) "
            "VALUES (%s, %s, %s, %s, %s)",
            rows,
        )
        cur.execute("""
            UPDATE daily_prices d
               SET adj_close = u.adj_close,
                   adj_high = u.adj_high,
                   adj_low = u.adj_low,
                   updated_at = NOW()
              FROM _adj_updates u
             WHERE d.ticker = u.ticker AND d.date = u.date
        """)
        affected = cur.rowcount
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
