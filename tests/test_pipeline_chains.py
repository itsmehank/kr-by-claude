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
    ch.run_daily_chain(conn=None)
    assert calls == ["ohlcv", "ind_daily"]
    assert fake.kwargs["pipeline"] == "data_daily"
    assert state["details"] == {"ohlcv": {"rows": 0, "failures": 0}, "indicators_daily": {"rows": 0, "failures": 0}}


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
