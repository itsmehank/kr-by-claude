# tests/test_backtest_classification_store.py
from datetime import datetime, date, timezone


def _result(cls="watch", pivot=100.0):
    return {
        "classification": cls, "pattern": "flat_base", "pivot_price": pivot,
        "pivot_basis": "range_high", "base_high": pivot, "base_low": pivot * 0.9,
        "base_depth_pct": 8.0, "base_start_date": "2025-08-01", "risk_flags": [],
        "confidence": 0.7, "reasoning": "t",
    }


def test_insert_into_backtest_classification_table(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BT1','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='BT1'")
    db.commit()
    insert_backfill_classification(
        db, symbol="BT1", classified_at=datetime(2026, 6, 23, 1, tzinfo=timezone.utc),
        market="KOSPI", result=_result("watch"), source="backtest",
        llm_meta={"duration_s": 5.0, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2023, 6, 30), table="backtest_classification",
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT classification, source FROM backtest_classification WHERE symbol='BT1'")
            rows = cur.fetchall()
            # 기존 테이블에는 안 들어가야 함(격리)
            cur.execute("SELECT COUNT(*) FROM classification_backfill WHERE symbol='BT1'")
            other = cur.fetchone()[0]
        assert len(rows) == 1 and rows[0] == ("watch", "backtest")
        assert other == 0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM backtest_classification WHERE symbol='BT1'")
        db.commit()


def test_insert_rejects_unknown_table(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    import pytest
    with pytest.raises(ValueError):
        insert_backfill_classification(
            db, symbol="BT1", classified_at=datetime(2026, 6, 23, tzinfo=timezone.utc),
            market="KOSPI", result=_result(), source="backtest",
            llm_meta={"duration_s": 1.0}, analyzed_for_date=date(2023, 6, 30),
            table="weekly_classification; DROP TABLE x",
        )


def test_backfill_insert_persists_structural_low(db, monkeypatch):
    """(#175) insert_backfill_classification 도 handle_low·handle_start·handle_end 를 기록(backtest_classification)."""
    from decimal import Decimal
    import kr_pipeline.llm_runner.store as store_mod
    from kr_pipeline.llm_runner.store import insert_backfill_classification

    sl = {"kind": "handle_low", "price": 91.0, "start": "2023-06-20", "end": "2023-06-30", "days": 9}

    def gate(conn, s, t, r, **kw):
        r["structural_low"] = sl
        return r, None

    monkeypatch.setattr(store_mod, "apply_phase1_gates", gate)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BTSL','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='BTSL'")
    db.commit()
    insert_backfill_classification(
        db, symbol="BTSL", classified_at=datetime(2026, 6, 23, 1, tzinfo=timezone.utc),
        market="KOSPI", result=_result("watch"), source="backtest", llm_meta={},
        analyzed_for_date=date(2023, 6, 30), table="backtest_classification",
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT handle_low, handle_start, handle_end FROM backtest_classification WHERE symbol='BTSL'")
            assert cur.fetchone() == (Decimal("91.0000"), date(2023, 6, 20), date(2023, 6, 30))
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM backtest_classification WHERE symbol='BTSL'")
        db.commit()
