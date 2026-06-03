from datetime import date


def test_run_weekend_runs_disqualify_before_weekend(db, monkeypatch):
    """full batch: disqualify 가 weekend.run 보다 먼저 호출된다."""
    import kr_pipeline.llm_runner.modes as modes
    calls = []
    monkeypatch.setattr(modes.disqualify, "run", lambda *a, **k: calls.append("disqualify") or {})
    monkeypatch.setattr(modes.weekend, "run", lambda *a, **k: calls.append("weekend") or {"processed": 0})
    monkeypatch.setattr(modes, "notify_weekend_digest", lambda **k: None)
    modes.run_weekend(db, dry_run=True, as_of=date(2025, 9, 30), limit=None)
    assert calls == ["disqualify", "weekend"]


def test_run_weekend_ticker_mode_skips_disqualify(db, monkeypatch):
    """단일 종목 디버그(ticker 지정)면 disqualify 스윕 생략."""
    import kr_pipeline.llm_runner.modes as modes
    calls = []
    monkeypatch.setattr(modes.disqualify, "run", lambda *a, **k: calls.append("disqualify") or {})
    monkeypatch.setattr(modes.weekend, "run", lambda *a, **k: calls.append("weekend") or {"processed": 0})
    monkeypatch.setattr(modes, "notify_weekend_digest", lambda **k: None)
    modes.run_weekend(db, dry_run=True, as_of=date(2025, 9, 30), limit=None, ticker="005930")
    assert "disqualify" not in calls
    assert calls == ["weekend"]
