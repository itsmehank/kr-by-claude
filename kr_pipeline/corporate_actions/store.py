# kr_pipeline/corporate_actions/store.py
"""corporate_actions UPSERT."""
from psycopg import Connection


def upsert_corporate_actions(conn: Connection, rows: list[dict]) -> int:
    """rows: dict 리스트. UPSERT — 같은 (ticker, event_date, event_type, dart_rcept_no) 면 note, raw_title 만 갱신.

    rows 의 각 키: ticker, event_date, event_type, ratio, note, dart_rcept_no, raw_disclosure_title.
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO corporate_actions
              (ticker, event_date, event_type, ratio, note, dart_rcept_no, raw_disclosure_title, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, event_date, event_type, dart_rcept_no) DO UPDATE
               SET note = EXCLUDED.note,
                   raw_disclosure_title = EXCLUDED.raw_disclosure_title,
                   ratio = EXCLUDED.ratio,
                   fetched_at = NOW()
            """,
            [
                (
                    r["ticker"], r["event_date"], r["event_type"], r.get("ratio"),
                    r.get("note"), r.get("dart_rcept_no"), r.get("raw_disclosure_title"),
                )
                for r in rows
            ],
        )
        return cur.rowcount
