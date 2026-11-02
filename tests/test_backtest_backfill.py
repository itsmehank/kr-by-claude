from datetime import datetime, date, timezone


def test_already_done_reads_backtest_table(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    from kr_pipeline.backtest.backfill import already_done
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BD1','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='BD1'")
    db.commit()
    assert already_done(db, date(2023, 6, 30)) == set() or "BD1" not in already_done(db, date(2023, 6, 30))
    insert_backfill_classification(
        db, symbol="BD1", classified_at=datetime(2026, 6, 23, tzinfo=timezone.utc),
        market="KOSPI",
        result={"classification": "watch", "pattern": "flat_base", "pivot_price": 100.0,
                "pivot_basis": "range_high", "base_high": 100.0, "base_low": 90.0,
                "base_depth_pct": 8.0, "base_start_date": "2023-05-01", "risk_flags": [],
                "confidence": 0.7, "reasoning": "t", "watch_reason": "base_forming"},
        llm_meta={"duration_s": 1.0}, analyzed_for_date=date(2023, 6, 30),
        source="backtest",
        table="backtest_classification",
    )
    db.commit()
    try:
        assert "BD1" in already_done(db, date(2023, 6, 30))
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM backtest_classification WHERE symbol='BD1'")
        db.commit()


def test_run_backtest_backfill_dry_run_no_insert(db, monkeypatch):
    # call_claude 를 mock(웹/실호출 없이) — dry_run 경로는 insert 안 함
    from kr_pipeline.backtest import backfill as bt
    # 토요일 1개 범위, 후보를 강제 주입(실제 qualifying 조회 우회)
    monkeypatch.setattr(bt, "get_qualifying_tickers",
                        lambda conn, as_of, tickers=None: [{"symbol": "BD2", "market": "KOSPI"}])
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BD2','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='BD2'")
    db.commit()
    r = bt.run_backtest_backfill(db, start=date(2023, 6, 26), end=date(2023, 7, 1),
                                 tickers=["BD2"], dry_run=True, concurrency=1)
    assert r["weeks"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM backtest_classification WHERE symbol='BD2'")
        assert cur.fetchone()[0] == 0   # dry_run 은 적재 안 함


def test_run_backtest_backfill_candidates_by_date_overrides_live_query(db, monkeypatch):
    """(#242) 스냅샷 후보 주입 — 라이브 get_qualifying_tickers 를 호출하지 않고, 주어진 토요일만 돈다."""
    from kr_pipeline.backtest import backfill as bt
    called = []
    monkeypatch.setattr(bt, "get_qualifying_tickers",
                        lambda conn, as_of, tickers=None: called.append(as_of) or [])
    seen = []
    monkeypatch.setattr(bt, "run_parallel_batch",
                        lambda **kw: seen.append((kw["as_of"], [c["symbol"] for c in kw["candidates"]])) or
                        {"processed": 0, "failed_tickers": [], "integrity_skipped": [],
                         "usage_limited": False, "usage_error": None})
    cbd = {date(2023, 6, 24): [{"symbol": "BD3", "market": "KOSPI"}],
           date(2023, 7, 8): [{"symbol": "BD3", "market": "KOSPI"}, {"symbol": "BD4", "market": "KOSDAQ"}]}
    r = bt.run_backtest_backfill(db, start=date(2023, 6, 1), end=date(2023, 7, 31), tickers=[],
                                 dry_run=True, concurrency=1, candidates_by_date=cbd)
    assert called == []                                   # 라이브 조회 0
    assert seen == [(date(2023, 6, 24), ["BD3"]), (date(2023, 7, 8), ["BD3", "BD4"])]
    assert r["weeks"] == 2


def test_run_backtest_backfill_candidates_by_date_respects_window(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    seen = []
    monkeypatch.setattr(bt, "run_parallel_batch",
                        lambda **kw: seen.append(kw["as_of"]) or
                        {"processed": 0, "failed_tickers": [], "integrity_skipped": [],
                         "usage_limited": False, "usage_error": None})
    cbd = {date(2023, 6, 24): [{"symbol": "BD3", "market": "KOSPI"}],
           date(2024, 1, 6): [{"symbol": "BD3", "market": "KOSPI"}]}
    bt.run_backtest_backfill(db, start=date(2023, 6, 1), end=date(2023, 7, 31), tickers=[],
                             dry_run=True, concurrency=1, candidates_by_date=cbd)
    assert seen == [date(2023, 6, 24)]                    # 창 밖 토요일 제외
