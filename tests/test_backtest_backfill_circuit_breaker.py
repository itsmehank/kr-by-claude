# tests/test_backtest_backfill_circuit_breaker.py
from datetime import date


def _batch(processed, failed):
    return {"processed": processed,
            "failed_tickers": [{"symbol": f"X{i}", "error": "rc=1"} for i in range(failed)],
            "integrity_skipped": [], "usage_limited": False, "usage_error": None}


def _wire(monkeypatch, bt, results):
    """results: 호출 순서대로 반환할 배치결과 리스트(소진되면 마지막 반복)."""
    monkeypatch.setattr(bt, "get_qualifying_tickers",
                        lambda conn, as_of, tickers=None: [{"symbol": "X", "market": "KOSPI"}])
    monkeypatch.setattr(bt, "already_done", lambda conn, as_of: set())
    seq = {"i": 0}
    def fake_batch(**kwargs):
        i = seq["i"]; seq["i"] += 1
        return results[i] if i < len(results) else results[-1]
    monkeypatch.setattr(bt, "run_parallel_batch", fake_batch)


def test_trips_on_total_failure(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    _wire(monkeypatch, bt, [_batch(0, 10)])           # 매주 100% 실패
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 2, 28),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is True
    assert agg["weeks"] == 2 and "stop_reason" in agg


def test_trips_on_chronic_partial_failure(db, monkeypatch):
    """핵심: 1건만 성공 + 나머지 대량 실패(=c4 패턴)도 트립해야 함."""
    from kr_pipeline.backtest import backfill as bt
    _wire(monkeypatch, bt, [_batch(1, 9)])            # 매주 90% 실패
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 2, 28),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is True
    assert agg["weeks"] == 2          # processed>0 이어도 fail_rate 기준으로 트립


def test_good_week_resets_counter(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    # 나쁨(90%), 좋음(20%), 나쁨, 나쁨 → 4주차에 2연속 채워 트립
    _wire(monkeypatch, bt, [_batch(1, 9), _batch(8, 2), _batch(1, 9), _batch(1, 9)])
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 2, 28),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is True
    assert agg["weeks"] == 4


def test_no_trip_low_failure_rate(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    _wire(monkeypatch, bt, [_batch(9, 1)])            # 매주 10% 실패 — 정상
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 1, 31),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is False
    assert agg["weeks"] >= 4          # 전 주 순회 완료


def test_tiny_week_deferred(db, monkeypatch):
    """시도수 < MIN_SAMPLE 인 주는 판정 보류(단독으로 트립 안 함)."""
    from kr_pipeline.backtest import backfill as bt
    _wire(monkeypatch, bt, [_batch(0, 1)])            # 매주 1건 시도·실패 (sample=1 < 3)
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 1, 31),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is False
    assert agg["weeks"] >= 4          # 보류라 트립 없이 완주
