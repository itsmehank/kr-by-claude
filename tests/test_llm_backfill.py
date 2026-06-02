from datetime import datetime, date, timezone


def _result(cls="watch", pivot=100.0):
    return {
        "classification": cls, "pattern": "flat_base", "pivot_price": pivot,
        "pivot_basis": "range_high", "base_high": pivot, "base_low": pivot * 0.9,
        "base_depth_pct": 8.0, "base_start_date": "2025-08-01", "risk_flags": [],
        "confidence": 0.7, "reasoning": "t",
    }


def test_insert_backfill_classification_basic(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKF1','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF1'")
    db.commit()
    insert_backfill_classification(
        db, symbol="BKF1", classified_at=datetime(2026, 6, 3, 1, tzinfo=timezone.utc),
        market="KOSPI", result=_result("watch"), source="backfill",
        llm_meta={"duration_s": 10.0, "input_tokens": 100, "output_tokens": 50},
        analyzed_for_date=date(2025, 9, 30),
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT classification, analyzed_for_date, source FROM classification_backfill WHERE symbol='BKF1'"
            )
            rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "watch"
        assert rows[0][1] == date(2025, 9, 30)
        assert rows[0][2] == "backfill"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF1'")
        db.commit()


def test_insert_backfill_idempotent_on_symbol_analyzed_for_date(db):
    """같은 (symbol, analyzed_for_date) 재삽입 → ON CONFLICT DO NOTHING (1행 유지, 덮어쓰기 안 함)."""
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKF2','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF2'")
    db.commit()
    afd = date(2025, 9, 30)
    insert_backfill_classification(db, symbol="BKF2", classified_at=datetime(2026, 6, 3, 1, tzinfo=timezone.utc),
                                   market="KOSPI", result=_result("watch", 111.0), source="backfill",
                                   llm_meta={"duration_s": 1, "input_tokens": 1, "output_tokens": 1},
                                   analyzed_for_date=afd)
    db.commit()
    insert_backfill_classification(db, symbol="BKF2", classified_at=datetime(2026, 6, 3, 2, tzinfo=timezone.utc),
                                   market="KOSPI", result=_result("ignore", 999.0), source="backfill",
                                   llm_meta={"duration_s": 1, "input_tokens": 1, "output_tokens": 1},
                                   analyzed_for_date=afd)
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT count(*), max(classification) FROM classification_backfill WHERE symbol='BKF2'")
            cnt, cls = cur.fetchone()
        assert cnt == 1
        assert cls == "watch"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF2'")
        db.commit()
