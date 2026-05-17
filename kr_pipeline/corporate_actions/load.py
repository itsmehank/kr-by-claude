# kr_pipeline/corporate_actions/load.py
"""DB SELECT 헬퍼."""
from psycopg import Connection


def load_active_tickers_with_corp_code(conn: Connection, limit: int | None = None) -> list[tuple[str, str]]:
    """[(ticker, corp_code), ...]. delisted_at IS NULL AND dart_corp_codes 매핑 존재.

    매핑 없는 종목은 skip (Task 6 의 sanity 가 카운트).
    """
    with conn.cursor() as cur:
        sql = """
            SELECT s.ticker, d.corp_code
              FROM stocks s
              JOIN dart_corp_codes d ON d.stock_code = s.ticker
             WHERE s.delisted_at IS NULL
             ORDER BY s.ticker
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return [(r[0], r[1]) for r in cur.fetchall()]


def count_active_tickers_without_mapping(conn: Connection) -> int:
    """매핑 없는 활성 종목 수 (sanity 용)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM stocks s
             WHERE s.delisted_at IS NULL
               AND NOT EXISTS (SELECT 1 FROM dart_corp_codes d WHERE d.stock_code = s.ticker)
        """)
        return cur.fetchone()[0] or 0
