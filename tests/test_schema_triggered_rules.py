"""triggered_rules JSONB 컬럼 존재 + nullable 검증."""


def test_triggered_rules_column_exists_and_nullable(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT data_type, is_nullable
              FROM information_schema.columns
             WHERE table_name = 'weekly_classification'
               AND column_name = 'triggered_rules'
        """)
        row = cur.fetchone()
    assert row is not None, "triggered_rules column must exist"
    assert row[0] == "jsonb", f"expected jsonb, got {row[0]}"
    assert row[1] == "YES", "triggered_rules must be nullable"


def test_triggered_rules_accepts_jsonb_and_key_query(db):
    """? 연산자로 룰 키 조회 가능해야 (회귀 검증의 기반)."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('TRTEST','TRTEST','KOSPI') ON CONFLICT DO NOTHING"
        )
        cur.execute("""
            INSERT INTO weekly_classification
              (symbol, classified_at, market, classification, source, triggered_rules)
            VALUES ('TRTEST', NOW(), 'KOSPI', 'watch', 'test', %s)
        """, ('{"2E_tier2": {"fired": true}}',))
        db.commit()
        cur.execute("""
            SELECT COUNT(*) FROM weekly_classification
             WHERE symbol = 'TRTEST' AND triggered_rules ? '2E_tier2'
        """)
        assert cur.fetchone()[0] == 1
