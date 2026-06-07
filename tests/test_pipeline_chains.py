"""tests/test_pipeline_chains.py — pipeline chains 순서 보장 테스트."""
import contextlib


class _Stats:
    def __init__(self):
        self.rows_affected = 0
        self.failures = []


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
    assert calls == ["ohlcv", "ind_daily"]
    assert fake.kwargs["pipeline"] == "data_daily"
    assert state["details"] == {
        "drift": {"detected": 0, "reloaded": 0, "failures": 0, "tickers": []},
        "ohlcv": {"rows": 0, "failures": 0},
        "indicators_daily": {"rows": 0, "failures": 0},
    }


def test_run_weekly_chain_calls_weekly_then_indicators_in_order(mocker):
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.weekly, "run", side_effect=lambda *a, **k: calls.append("weekly") or _Stats())
    mocker.patch.object(ch.indicators, "run_weekly", side_effect=lambda *a, **k: calls.append("ind_weekly") or _Stats())
    ch.run_weekly_chain(conn=None)
    assert calls == ["weekly", "ind_weekly"]
    assert fake.kwargs["pipeline"] == "data_weekly"
    assert state["details"] == {"weekly": {"rows": 0, "failures": 0}, "indicators_weekly": {"rows": 0, "failures": 0}}


def test_run_daily_chain_detects_before_ohlcv_then_reloads(mocker):
    """순서: detect(증분 전) → ohlcv 증분 → reload(감지분) → indicators 증분."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "recent_corp_action_tickers", return_value=["AAA"])
    mocker.patch.object(ch.drift, "detect_drifted_tickers",
                        side_effect=lambda *a, **k: calls.append("detect") or ["AAA"])
    mocker.patch.object(ch.drift, "reload_ticker",
                        side_effect=lambda *a, **k: calls.append("reload") or {"ticker": "AAA"})
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: calls.append("ohlcv") or _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily") or _Stats())

    ch.run_daily_chain(conn=None)
    assert calls == ["detect", "ohlcv", "reload", "ind_daily"]
    assert state["details"]["drift"]["detected"] == 1
    assert state["details"]["drift"]["reloaded"] == 1


def test_run_daily_chain_drift_false_skips_detect(mocker):
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers",
                        side_effect=lambda *a, **k: calls.append("detect") or [])
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: calls.append("ohlcv") or _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily") or _Stats())

    ch.run_daily_chain(conn=None, drift_check=False)
    assert calls == ["ohlcv", "ind_daily"]


def test_run_daily_chain_reload_failure_isolated(mocker):
    """한 종목 reload 실패는 로그+rollback+계속, indicators 증분은 그대로 실행."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "recent_corp_action_tickers", return_value=["AAA", "BBB"])
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
    assert state["details"]["drift"] == {"detected": 2, "reloaded": 1, "failures": 1, "tickers": ["AAA", "BBB"]}
    rb.assert_called_once()


def test_run_daily_chain_passes_corp_action_candidates(mocker):
    """detect 가 recent_corp_action_tickers 의 후보 목록을 tickers 로 받아 호출된다."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    mocker.patch.object(ch.drift, "recent_corp_action_tickers", return_value=["AAA", "BBB"])
    det = mocker.patch.object(ch.drift, "detect_drifted_tickers", return_value=[])
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: _Stats())

    ch.run_daily_chain(conn=None)
    assert det.call_args.kwargs["tickers"] == ["AAA", "BBB"]
