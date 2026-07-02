from datetime import datetime, date, timezone


def test_load_watchlist_reads_backtest_table(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    from kr_pipeline.backtest.trigger_sim import load_watchlist
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('WL1','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='WL1'")
    db.commit()
    insert_backfill_classification(
        db, symbol="WL1", classified_at=datetime(2026, 6, 23, tzinfo=timezone.utc),
        market="KOSPI",
        result={"classification": "watch", "pattern": "flat_base", "pivot_price": 100.0,
                "pivot_basis": "range_high", "base_high": 100.0, "base_low": 90.0,
                "base_depth_pct": 8.0, "base_start_date": "2023-05-01", "risk_flags": [],
                "confidence": 0.7, "reasoning": "t", "watch_reason": "base_forming"},
        source="backtest",
        llm_meta={"duration_s": 1.0}, analyzed_for_date=date(2023, 6, 30),
        table="backtest_classification",
    )
    db.commit()
    try:
        rows = load_watchlist(db, "WL1", date(2023, 1, 1), date(2023, 12, 31),
                              table="backtest_classification")
        assert len(rows) == 1
        assert rows[0].pivot_price == 100.0
        # default 테이블에는 없음
        empty = load_watchlist(db, "WL1", date(2023, 1, 1), date(2023, 12, 31))
        assert empty == []
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM backtest_classification WHERE symbol='WL1'")
        db.commit()
