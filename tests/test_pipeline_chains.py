"""tests/test_pipeline_chains.py — pipeline chains 순서 보장 테스트."""
import contextlib


class _Stats:
    def __init__(self, adjusted=()):
        self.rows_affected = 0
        self.failures = []
        self.adjusted_tickers = list(adjusted)   # #207: ohlcv 증분이 기록·소급한 조정 종목


def _fake_run_tracking(mocker, ch):
    """run_tracking 을 DB 없이 동작하는 가짜로 대체. 기록된 state 를 반환해 검증."""
    state = {"run_id": 1, "warnings": [], "rows_affected": None, "total_count": None, "details": None}

    @contextlib.contextmanager
    def fake(*a, **k):
        fake.kwargs = k
        yield state

    mocker.patch.object(ch, "run_tracking", side_effect=fake)
    return state, fake


def test_run_daily_chain_calls_ohlcv_then_indicators_in_order(mocker):
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: calls.append("ohlcv") or _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily") or _Stats())
    ch.run_daily_chain(conn=None, drift_check=False)
    assert calls == ["ohlcv", "ind_daily"]      # drift_check=False: 안전망 스캔 생략(증분의 adjusted_tickers 는 그래도 reload)
    assert fake.kwargs["pipeline"] == "data_daily"
    assert state["details"] == {
        "drift": {"detected": 0, "reloaded": 0, "failures": 0, "tickers": [], "unverified": 0},
        "ohlcv": {"rows": 0, "failures": 0},
        "indicators_daily": {"rows": 0, "failures": 0},
    }


def test_run_weekly_chain_calls_weekly_then_indicators_in_order(mocker):
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.weekly, "run", side_effect=lambda *a, **k: calls.append("weekly") or _Stats())
    mocker.patch.object(ch.indicators, "run_weekly", side_effect=lambda *a, **k: calls.append("ind_weekly") or _Stats())
    mirror = {"rows": 3, "candidates_before": 61, "candidates_after": 66, "added": ["A"], "removed": []}
    mocker.patch.object(ch, "_mirror_gate_with_diff", side_effect=lambda *a, **k: calls.append("mirror") or mirror)
    ch.run_weekly_chain(conn=None, full_sweep=False)
    # #203: 주봉 지표 뒤 · LLM 선별 전에 주봉 게이트를 daily 로 미러(직전 주 게이트로 후보 선정되던 결함).
    assert calls == ["weekly", "ind_weekly", "mirror"]
    assert fake.kwargs["pipeline"] == "data_weekly"
    assert state["details"] == {
        "sweep": {"detected": 0, "reloaded": 0, "failures": 0, "unverified": 0},
        "weekly": {"rows": 0, "failures": 0},
        "indicators_weekly": {"rows": 0, "failures": 0},
        "daily_rs_gate_mirror": mirror,
    }


def test_run_daily_chain_ohlcv_then_detect_then_reloads(mocker):
    """#207 A안 순서: ohlcv 증분(조정일 기록·소급) → detect(DB 창 안전망, 접촉 0) → reload(합집합) → indicators 증분."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers",
                        side_effect=lambda *a, **k: calls.append("detect") or ["BBB"])
    mocker.patch.object(ch.drift, "reload_ticker",
                        side_effect=lambda conn, t, **k: calls.append(("reload", t)) or {"ticker": t})
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: calls.append("ohlcv") or _Stats(adjusted=["AAA"]))
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily") or _Stats())

    ch.run_daily_chain(conn=None)
    assert calls == ["ohlcv", "detect", ("reload", "AAA"), ("reload", "BBB"), "ind_daily"]
    assert state["details"]["drift"]["detected"] == 2 and state["details"]["drift"]["reloaded"] == 2
    assert state["details"]["drift"]["tickers"] == ["AAA", "BBB"]


def test_run_daily_chain_drift_false_skips_detect(mocker):
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers",
                        side_effect=lambda *a, **k: calls.append("detect") or [])
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: calls.append("ohlcv") or _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily") or _Stats())

    ch.run_daily_chain(conn=None, drift_check=False)
    assert calls == ["ohlcv", "ind_daily"]      # drift_check=False: 안전망 스캔 생략(증분의 adjusted_tickers 는 그래도 reload)


def test_run_daily_chain_reload_failure_isolated(mocker):
    """한 종목 reload 실패는 로그+rollback+계속, indicators 증분은 그대로 실행."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers", side_effect=lambda *a, **k: ["AAA", "BBB"])
    def boom(conn, t, **k):
        if t == "AAA":
            raise RuntimeError("reload fail")
        return {"ticker": t}
    mocker.patch.object(ch.drift, "reload_ticker", side_effect=boom)
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily") or _Stats())
    rb = mocker.patch.object(ch, "_rollback", side_effect=lambda conn: None)

    ch.run_daily_chain(conn=None)
    assert calls == ["ind_daily"]
    assert state["details"]["drift"] == {"detected": 2, "reloaded": 1, "failures": 1, "tickers": ["AAA", "BBB"], "unverified": 0}
    rb.assert_called_once()


def test_run_daily_chain_detect_scans_all_active_without_candidates(mocker):
    """detect 는 공시 후보 목록 없이(접촉 0 이므로) 활성 전 종목 창을 스캔 — tickers 인자 없음."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    det = mocker.patch.object(ch.drift, "detect_drifted_tickers", return_value=[])
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: _Stats())

    ch.run_daily_chain(conn=None)
    assert "tickers" not in det.call_args.kwargs and det.call_args.kwargs["as_of"] is not None


def test_run_weekly_chain_full_sweep_reloads_before_weekly(mocker):
    """full_sweep: 전 종목(tickers=None) detect+reload 가 weekly 단계 '전'에 90일 창으로 실행."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers",
                        side_effect=lambda *a, **k: calls.append(("detect", k.get("tickers"), k.get("recent_days"))) or ["AAA"])
    mocker.patch.object(ch.drift, "reload_ticker",
                        side_effect=lambda *a, **k: calls.append("reload") or {"ticker": "AAA"})
    mocker.patch.object(ch.weekly, "run", side_effect=lambda *a, **k: calls.append("weekly") or _Stats())
    mocker.patch.object(ch.indicators, "run_weekly", side_effect=lambda *a, **k: calls.append("ind_weekly") or _Stats())
    mocker.patch.object(ch, "_mirror_gate_with_diff", side_effect=lambda *a, **k: calls.append("mirror") or {})

    ch.run_weekly_chain(conn=None)
    assert [c[0] if isinstance(c, tuple) else c for c in calls] == ["detect", "reload", "weekly", "ind_weekly", "mirror"]
    assert calls[0][1] is None    # tickers=None → 전 종목
    assert calls[0][2] == ch.drift.SWEEP_RECENT_DAYS
    assert state["details"]["sweep"] == {"detected": 1, "reloaded": 1, "failures": 0, "unverified": 0}


def test_run_weekly_chain_sweep_reload_failure_isolated(mocker):
    """스윕 reload 실패는 rollback+계속, weekly/indicators 는 그대로."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers", side_effect=lambda *a, **k: ["AAA", "BBB"])
    def boom(conn, t, **k):
        if t == "AAA":
            raise RuntimeError("reload fail")
        return {"ticker": t}
    mocker.patch.object(ch.drift, "reload_ticker", side_effect=boom)
    mocker.patch.object(ch.weekly, "run", side_effect=lambda *a, **k: calls.append("weekly") or _Stats())
    mocker.patch.object(ch.indicators, "run_weekly", side_effect=lambda *a, **k: calls.append("ind_weekly") or _Stats())
    rb = mocker.patch.object(ch, "_rollback", side_effect=lambda conn: None)
    mocker.patch.object(ch, "_mirror_gate_with_diff", side_effect=lambda *a, **k: calls.append("mirror") or {})

    ch.run_weekly_chain(conn=None)
    assert calls == ["weekly", "ind_weekly", "mirror"]
    assert state["details"]["sweep"] == {"detected": 2, "reloaded": 1, "failures": 1, "unverified": 0}
    rb.assert_called_once()


def test_main_weekly_no_sweep_passes_full_sweep_false(mocker):
    """CLI --no-sweep → run_weekly_chain(full_sweep=False)."""
    import importlib
    m = importlib.import_module("kr_pipeline.pipeline.__main__")

    mocker.patch.object(m, "Config")
    mocker.patch.object(m, "setup_logging")
    conn_cm = mocker.patch.object(m, "connect")
    conn_cm.return_value.__enter__.return_value = "CONN"
    rw = mocker.patch.object(m.chains, "run_weekly_chain", return_value={})
    mocker.patch("sys.argv", ["prog", "--chain=weekly", "--no-sweep"])

    m.main()
    rw.assert_called_once_with("CONN", limit_tickers=None, full_sweep=False)


def test_run_weekly_chain_mirror_failure_is_fail_closed(mocker):
    """#203 미러 실패 = 예외 전파(data_weekly failed → weekend_chain.sh 가 LLM 선별 중단). 미러 없이 선별하면
    직전 주 게이트 결함이 그대로 재현되므로 fail-soft 로 계속하지 않는다."""
    import pytest
    import kr_pipeline.pipeline.chains as ch

    _fake_run_tracking(mocker, ch)
    mocker.patch.object(ch.weekly, "run", return_value=_Stats())
    mocker.patch.object(ch.indicators, "run_weekly", return_value=_Stats())
    mocker.patch.object(ch, "_mirror_gate_with_diff", side_effect=RuntimeError("lock timeout"))
    with pytest.raises(RuntimeError, match="lock timeout"):
        ch.run_weekly_chain(conn=None, full_sweep=False)
