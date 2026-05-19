"""insert_classification — analyzed_for_date 인자 동작."""
from datetime import date, datetime, timezone


def test_insert_classification_with_analyzed_for_date(db):
    """analyzed_for_date 인자가 DB 컬럼에 저장됨."""
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='STRA'")
    db.commit()

    insert_classification(
        db,
        symbol="STRA",
        classified_at=datetime.now(timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch",
            "pattern": "flat_base",
            "pivot_price": 1000.0,
            "pivot_basis": "high_of_base",
            "base_high": 1000.0,
            "base_low": 900.0,
            "base_depth_pct": 10.0,
            "base_start_date": "2026-03-01",
            "risk_flags": [],
            "confidence": 0.5,
            "reasoning": "test",
        },
        source="weekend",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2026, 5, 18),
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT analyzed_for_date FROM weekly_classification WHERE symbol='STRA'"
        )
        row = cur.fetchone()
    assert row[0] == date(2026, 5, 18)


def test_insert_classification_default_analyzed_for_date_is_null(db):
    """analyzed_for_date 인자 안 주면 컬럼 NULL."""
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='STRB'")
    db.commit()

    insert_classification(
        db,
        symbol="STRB",
        classified_at=datetime.now(timezone.utc),
        market="KOSDAQ",
        result={
            "classification": "ignore",
            "pattern": "none",
            "pivot_price": None,
            "pivot_basis": None,
            "base_high": None,
            "base_low": None,
            "base_depth_pct": None,
            "base_start_date": None,
            "risk_flags": [],
            "confidence": 0.8,
            "reasoning": "test",
        },
        source="daily_delta",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT analyzed_for_date FROM weekly_classification WHERE symbol='STRB'"
        )
        row = cur.fetchone()
    assert row[0] is None
