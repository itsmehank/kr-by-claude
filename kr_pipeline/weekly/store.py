"""weekly_prices / weekly_index UPSERT 헬퍼."""
from datetime import date, timedelta

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


def _delete_superseded(conn: Connection, table: str, key_col: str, key: str,
                       week_end_dates: list[date]) -> int:
    """같은 ISO 주(월~일)에서 week_end_date 가 다른 행 삭제.

    week_end_date 는 '그 시점에 존재하는 일봉의 max' 라서, 일봉이 덜 적재된
    상태의 부분집계가 (예: 화요일 키) 행으로 남고, 완전한 데이터로 재집계하면
    금요일 키의 *새 행* 이 들어가 부분 행이 고아로 영구 잔존한다.
    upsert 직후 호출해 새 키가 속한 ISO 주의 구(舊) 키 행을 정리한다.
    """
    deleted = 0
    with conn.cursor() as cur:
        for d in week_end_dates:
            monday = d - timedelta(days=d.weekday())
            cur.execute(
                f"""
                DELETE FROM {table}
                 WHERE {key_col} = %s
                   AND week_end_date BETWEEN %s AND %s
                   AND week_end_date <> %s
                """,
                (key, monday, monday + timedelta(days=6), d),
            )
            deleted += cur.rowcount
    return deleted


def delete_superseded_weekly_prices(conn: Connection, ticker: str,
                                    week_end_dates: list[date]) -> int:
    return _delete_superseded(conn, "weekly_prices", "ticker", ticker, week_end_dates)


def delete_superseded_weekly_index(conn: Connection, index_code: str,
                                   week_end_dates: list[date]) -> int:
    return _delete_superseded(conn, "weekly_index", "index_code", index_code, week_end_dates)


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
