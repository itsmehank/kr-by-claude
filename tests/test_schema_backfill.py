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
