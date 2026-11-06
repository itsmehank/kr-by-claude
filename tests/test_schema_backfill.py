def test_classification_backfill_table_exists_with_pk(db):
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.classification_backfill')")
        assert cur.fetchone()[0] is not None, "classification_backfill 테이블 없음"
        cur.execute(
            """SELECT a.attname
                 FROM pg_index i
                 JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = 'classification_backfill'::regclass AND i.indisprimary
                ORDER BY a.attname"""
        )
        pk_cols = sorted(r[0] for r in cur.fetchall())
    assert pk_cols == ["analyzed_for_date", "symbol"], f"PK 불일치: {pk_cols}"


def test_handle_low_columns_on_all_classification_tables(db):
    """(#175 2026-11-06) 구조 저점 3열 — 네 분류 테이블 전부(nullable)."""
    for t in ("weekly_classification", "classification_backfill", "backtest_classification", "recall_audit_classification"):
        with db.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (t,))
            cols = {r[0] for r in cur.fetchall()}
        assert {"handle_low", "handle_start", "handle_end"} <= cols, f"{t}: {cols}"
