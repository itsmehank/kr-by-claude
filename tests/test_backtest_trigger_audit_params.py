"""trigger_audit 파라미터화 — 표본·경로·보정(5% 추격) 대상 전달."""


def test_collect_down_trades_accepts_tickers_and_chase(db, monkeypatch):
    import kr_pipeline.backtest.trigger_audit as ta
    seen = {}

    def fake_simulate(ticker, rows, bars, mode="production", **kw):
        seen.setdefault("chase", kw.get("max_chase_pct"))
        return [], 0

    monkeypatch.setattr(ta, "simulate", fake_simulate)
    monkeypatch.setattr(ta, "load_watchlist", lambda *a, **k: [])
    monkeypatch.setattr(ta, "load_daily_series", lambda *a, **k: [])
    monkeypatch.setattr(ta, "classify_rows", lambda wr: {"production": []})
    monkeypatch.setattr(ta, "_market_of", lambda conn, t: "KOSPI")
    monkeypatch.setattr(ta.ph, "load_phase_map", lambda conn, code: [])
    out = ta.collect_down_trades(db, tickers=["000001"], max_chase_pct=5.0)
    assert out == []
    assert seen["chase"] == 5.0


def test_run_audit_threads_params_to_collect(db, tmp_path, monkeypatch):
    """run_audit 가 tickers·max_chase_pct 를 collect 로 전달하고 커스텀 path 를 쓰는지."""
    import kr_pipeline.backtest.trigger_audit as ta
    seen = {}

    def fake_collect(conn, tickers=None, max_chase_pct=None):
        seen.update(tickers=tickers, chase=max_chase_pct)
        return []

    monkeypatch.setattr(ta, "collect_down_trades", fake_collect)
    p = tmp_path / "audit_b.json"
    agg = ta.run_audit(db, dry_run=True, path=p, tickers=["000001"], max_chase_pct=5.0)
    assert seen["tickers"] == ["000001"]
    assert seen["chase"] == 5.0
    assert agg["total"] == 0                      # 대상 0건 — 예외 없이 집계 반환
    # 기본 A 경로 파일은 이 테스트가 건드리지 않는다(쓰기 발생 시 아래가 실패해야 함):
    assert not (tmp_path / "trigger_audit_20260702.json").exists()
