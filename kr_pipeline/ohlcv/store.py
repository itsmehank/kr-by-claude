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
    """full-refresh: (ticker, date, adj_close) 튜플로 adj_close 만 갱신. 없는 행은 무시.

    구현: TEMP TABLE 에 모든 row 를 한 번에 INSERT 한 후, JOIN-UPDATE 로 일괄 갱신.
    1-row-per-execute 대비 수십~수백배 빠름.
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        # 1. 트랜잭션 스코프 임시 테이블 (트랜잭션 종료 시 자동 DROP)
        cur.execute("""
            CREATE TEMP TABLE _adj_updates (
                ticker     VARCHAR(10)   NOT NULL,
                date       DATE          NOT NULL,
                adj_close  NUMERIC(12,4) NOT NULL,
                PRIMARY KEY (ticker, date)
            ) ON COMMIT DROP
        """)

        # 2. 모든 행을 임시 테이블에 일괄 INSERT
        cur.executemany(
            "INSERT INTO _adj_updates (ticker, date, adj_close) VALUES (%s, %s, %s)",
            rows,
        )

        # 3. JOIN-UPDATE - 매칭되는 daily_prices 행만 갱신, 없는 행은 무시
        cur.execute("""
            UPDATE daily_prices d
               SET adj_close = u.adj_close,
                   updated_at = NOW()
              FROM _adj_updates u
             WHERE d.ticker = u.ticker
               AND d.date = u.date
        """)
        affected = cur.rowcount

        # 4. ON COMMIT DROP 으로 자동 정리됨 (다음 commit 또는 트랜잭션 끝에서)

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
