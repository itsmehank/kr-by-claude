import pytest

@pytest.mark.parametrize("table", ["trigger_evaluation_log", "entry_params"])
def test_analyzed_for_date_column_exists(db, table):
    """rerun-idempotency: 두 테이블에 analyzed_for_date(DATE) 컬럼 존재 검증."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = 'analyzed_for_date'",
            (table,),
        )
        row = cur.fetchone()
    assert row is not None, "analyzed_for_date 컬럼 없음"
    assert row[0] == "date"
