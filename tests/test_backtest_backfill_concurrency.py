from datetime import date


def _ok_batch():
    return {"processed": 1, "failed_tickers": [], "integrity_skipped": [],
            "usage_limited": False, "usage_error": None}


def test_default_concurrency_is_2(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    captured = {}
    monkeypatch.setattr(bt, "get_qualifying_tickers",
                        lambda conn, as_of, tickers=None: [{"symbol": "X", "market": "KOSPI"}])
    monkeypatch.setattr(bt, "already_done", lambda conn, as_of: set())

    def fake_batch(*, dsn, candidates, process_fn, concurrency, dry_run, as_of, run_id=None, abort=None):
        captured["concurrency"] = concurrency
        return _ok_batch()
    monkeypatch.setattr(bt, "run_parallel_batch", fake_batch)

    bt.run_backtest_backfill(db, start=date(2022, 9, 5), end=date(2022, 9, 11),
                             tickers=["X"], dry_run=False)        # no concurrency arg
    assert captured["concurrency"] == 2


def test_explicit_concurrency_overrides(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    captured = {}
    monkeypatch.setattr(bt, "get_qualifying_tickers",
                        lambda conn, as_of, tickers=None: [{"symbol": "X", "market": "KOSPI"}])
    monkeypatch.setattr(bt, "already_done", lambda conn, as_of: set())
    def fake_batch(*, dsn, candidates, process_fn, concurrency, dry_run, as_of, run_id=None, abort=None):
        captured["concurrency"] = concurrency
        return _ok_batch()
    monkeypatch.setattr(bt, "run_parallel_batch", fake_batch)

    bt.run_backtest_backfill(db, start=date(2022, 9, 5), end=date(2022, 9, 11),
                             tickers=["X"], dry_run=False, concurrency=1)
    assert captured["concurrency"] == 1
