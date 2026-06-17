import logging

from psycopg import Connection

log = logging.getLogger("kr_pipeline.ohlcv.store")


def _warn_unnormalized_halt(rows: list[tuple]) -> int:
    """tripwire(경보 전용) — chokepoint(transform.nullify_halt_adj) 를 안 거친 halt 행이
    store 에 도달했는지 탐지. update_adj_prices 7-튜플
    (ticker, date, adj_close, adj_high, adj_low, adj_open, adj_volume) 기준,
    halt 패턴(adj_high=adj_low=adj_open=adj_volume=0 AND adj_close>0)이면 정규화 누락 의심.

    데이터를 바꾸지 않는다(halt 정의의 SSOT 는 nullify_halt_adj 1곳). 정규화된 halt 행은
    adj_*=None 이라 미탐지. 향후 신규 writer 가 chokepoint 를 우회하면 조기에 로그로 드러낸다."""
    n = 0
    for r in rows:
        adj_close, adj_high, adj_low, adj_open, adj_volume = r[2], r[3], r[4], r[5], r[6]
        if (adj_high == 0 and adj_low == 0 and adj_open == 0 and adj_volume == 0
                and adj_close is not None and adj_close > 0):
            n += 1
    if n:
        log.warning(
            "%d halt-pattern rows reached store un-normalized (transform.nullify_halt_adj "
            "bypass?) — check the adj_* writer (drift.reload_ticker / _run_full_refresh)", n
        )
    return n


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
    """full-refresh: (ticker, date, adj_close, adj_high, adj_low, adj_open, adj_volume) 7-튜플로
    수정 OHLC 5종 갱신.

    TEMP TABLE + JOIN-UPDATE. 매칭 없는 행은 무시.
    """
    if not rows:
        return 0
    _warn_unnormalized_halt(rows)  # tripwire — 정규화 누락 조기탐지(데이터 변경 없음)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE _adj_updates (
                ticker      VARCHAR(10)   NOT NULL,
                date        DATE          NOT NULL,
                adj_close   NUMERIC(12,4) NOT NULL,
                adj_high    NUMERIC(12,4),
                adj_low     NUMERIC(12,4),
                adj_open    NUMERIC(12,4),
                adj_volume  NUMERIC(20,2),
                PRIMARY KEY (ticker, date)
            ) ON COMMIT DROP
        """)
        cur.executemany(
            "INSERT INTO _adj_updates (ticker, date, adj_close, adj_high, adj_low, adj_open, adj_volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
        cur.execute("""
            UPDATE daily_prices d
               SET adj_close  = u.adj_close,
                   adj_high   = u.adj_high,
                   adj_low    = u.adj_low,
                   adj_open   = u.adj_open,
                   adj_volume = u.adj_volume,
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
