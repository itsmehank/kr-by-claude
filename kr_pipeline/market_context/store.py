# kr_pipeline/market_context/store.py
"""market_context_daily UPSERT."""
from psycopg import Connection


COLUMNS = [
    "date", "index_code", "current_status",
    "distribution_day_count_last_25",
    "last_follow_through_day",
    "days_since_follow_through",
    "pct_stocks_above_200d_ma",
    "computation_notes",
]


def upsert_market_context(conn: Connection, rows: list[dict]) -> int:
    """rows: PHASE A 결과 dict 리스트. (date, index_code) PK 로 UPSERT."""
    if not rows:
        return 0
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    cols_sql = ", ".join(COLUMNS)
    update_sql = ", ".join([f"{c} = EXCLUDED.{c}" for c in COLUMNS if c not in ("date", "index_code")])

    sql = f"""
        INSERT INTO market_context_daily ({cols_sql}, updated_at)
        VALUES ({placeholders}, NOW())
        ON CONFLICT (date, index_code) DO UPDATE
           SET {update_sql}, updated_at = NOW()
    """

    tuples = [tuple(r.get(c) for c in COLUMNS) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, tuples)
        return cur.rowcount
