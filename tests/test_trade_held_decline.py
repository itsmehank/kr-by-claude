"""(#164 2026-09-09) 보유 종목 약세 매도 — 결합식·억제 없음·3모드·우선순위 3단·파리티·백테스트 reason=decline."""
from datetime import date, timedelta

import pytest

from kr_pipeline.common.thresholds import TRADE_HOLD_MIN_DAYS
from kr_pipeline.trade_management.held_climax import gates_from_series
from kr_pipeline.trade_management.held_decline import (
    HELD_DECLINE_SIGNALS, HeldDeclineDecision, decline_metrics, evaluate_held_decline,
)

ENTRY = date(2026, 1, 5)
EARLY = ENTRY + timedelta(days=5)                        # 8주 억제 없음 — 5일 보유도 발화 가능
LATE = ENTRY + timedelta(days=TRADE_HOLD_MIN_DAYS + 10)


def _g(**over):
    g = {"left_censored": False, "no_transition": False, "quality_flag": False,
         "anchor_week": "2025-06-06", "weeks_since": 30, "maturity_ok": True,
         "ta_max_decline_now": False, "ta_d_daily_max_decline_now": False,
         "p2_accel_ok": False, "scope_active": True}
    g.update(over)
    return g


# ---------- 결합식 ----------

@pytest.mark.parametrize("sig", HELD_DECLINE_SIGNALS)
def test_fires_on_either_signal_with_p1(sig):
    d = evaluate_held_decline(_g(**{sig: True}), ENTRY, LATE)
    assert d.fired is True and d.signals == (sig,) and d.mode == "anchored"


def test_no_signal_no_fire():
    d = evaluate_held_decline(_g(), ENTRY, LATE)
    assert d.fired is False and d.signals == ()


def test_p1_unmet_never_fires():
    d = evaluate_held_decline(_g(maturity_ok=False, ta_max_decline_now=True,
                                 ta_d_daily_max_decline_now=True), ENTRY, LATE)
    assert d.fired is False and d.signals == HELD_DECLINE_SIGNALS


def test_no_hold_min_suppression():
    # 하락 신호에 리더십 예외 없음 — 보유 5일에도 발화(climax 의 8주 억제와 다름)
    d = evaluate_held_decline(_g(ta_d_daily_max_decline_now=True), ENTRY, EARLY)
    assert d.fired is True and d.hold_days == 5


def test_null_signal_is_unevaluated_not_fired():
    # TA-d None(재개일 등) + T-A False → 미평가·미발화(False, None 아님)
    d = evaluate_held_decline(_g(ta_d_daily_max_decline_now=None), ENTRY, LATE)
    assert d.fired is False and d.ta_d_daily_max_decline_now is None
    # TA-d None + T-A True → 나머지로만 판정 → 발화
    d2 = evaluate_held_decline(_g(ta_d_daily_max_decline_now=None, ta_max_decline_now=True), ENTRY, LATE)
    assert d2.fired is True and d2.signals == ("ta_max_decline_now",)


def test_p2_scope_g0_not_required():
    # P2·scope·G0 는 결합식에 없다 — P2 False·scope False 여도 P1∧TA-d 로 발화
    d = evaluate_held_decline(_g(ta_d_daily_max_decline_now=True, p2_accel_ok=False, scope_active=False),
                              ENTRY, LATE)
    assert d.fired is True


# ---------- 3모드 None ----------

@pytest.mark.parametrize("mode_kw,mode", [
    ({"left_censored": True, "maturity_ok": None, "ta_max_decline_now": None, "ta_d_daily_max_decline_now": None},
     "left_censored"),
    ({"no_transition": True, "anchor_week": None, "weeks_since": None, "maturity_ok": None,
      "ta_max_decline_now": None, "ta_d_daily_max_decline_now": None}, "no_transition"),
    ({"quality_flag": True, "ta_d_daily_max_decline_now": None}, "quality"),
])
def test_missing_modes_yield_none(mode_kw, mode):
    d = evaluate_held_decline(_g(**{"ta_max_decline_now": True, **mode_kw}), ENTRY, LATE)
    assert d.fired is None and d.mode == mode


# ---------- gates_from_series 가 T-A 를 공급(파리티: compute_topping_gates 와 동일 산술) ----------

def _weekly(seq, start=date(2018, 1, 5)):
    return [{"week_end": str(start + timedelta(weeks=i)), "open": p, "high": p * 1.02, "low": p * 0.98,
             "close": p, "volume": v} for i, (p, v) in enumerate(seq)]


def _anchored_weekly():
    # tests/test_climax_topping._fixture_climax_run 과 같은 형태: 40주 드리프트-다운(Stage 1) →
    # 돌파 주(거래량 3배, SMA 위) → 20주 상승 → 마지막 주 큰 하락(baseline 최대 하락 주)
    down = [(1000.0 - (1000.0 - 800.0) / 59 * i, 100_000) for i in range(60)]
    brk = [(950.0, 300_000)]
    up = [(960.0 + 20 * i, 120_000) for i in range(20)]
    last = [(up[-1][0] * 0.85, 150_000)]
    return _weekly(down + brk + up + last)


def test_gates_from_series_supplies_ta_consistent_with_topping_gates():
    from kr_pipeline.llm_runner.compute.climax_topping import compute_topping_gates, find_anchor
    wk = _anchored_weekly()
    anchor = find_anchor(wk)
    assert anchor["anchor_week"] is not None
    g = gates_from_series(wk, [])
    assert g["ta_max_decline_now"] == compute_topping_gates(wk, None, anchor)["ta_max_decline_now"] is True
    d = evaluate_held_decline(g, ENTRY, LATE)
    assert d.mode == "anchored" and d.maturity_ok is True and d.fired is True
    assert d.signals == ("ta_max_decline_now",)  # 일봉 없음 → TA-d None(미평가), T-A 만으로 발화


def test_gates_from_series_left_censored_ta_none():
    wk = _weekly([(1000.0 - i, 100_000) for i in range(40)])
    g = gates_from_series(wk, [])
    assert g["left_censored"] is True and g["ta_max_decline_now"] is None
    assert evaluate_held_decline(g, ENTRY, LATE).fired is None


def test_decline_metrics_echo_matches_signals():
    wk = _anchored_weekly()
    g = gates_from_series(wk, [])
    m = decline_metrics(wk, [], g["anchor_week"])
    # T-A True ↔ 당주 하락률이 baseline 최대(동률 허용)
    assert m.week_decline_pct is not None and m.week_decline_pct >= m.baseline_max_weekly_decline_pct
    assert m.today_decline_pct is None and m.baseline_max_daily_decline_pct is None  # 일봉 없음
    assert decline_metrics(wk, [], None) == decline_metrics([], [], None)  # anchor 부재 → 전부 None


# ---------- 러너: 우선순위 스탑 > 약세 > 강세 · 알림 · 병기 · 멱등 ----------

from tests.test_trade_held_climax import _bar, _runner_cleanup, _runner_seed  # noqa: E402


def _gates_both():
    return _g(ta_d_daily_max_decline_now=True, p2_accel_ok=True, scope_active=True,
              t2_max_volume_now=True, **{k: False for k in (
                  "t1_max_spread_now", "t3_gap_up_today", "t4_ok", "t5_daily_max_up_now",
                  "t6_daily_max_spread_now")})


def test_runner_decline_fires_notifies_and_records_climax_also(db, mocker):
    from kr_pipeline.trade_management import runner
    pid = _runner_seed(db, "HDCL1")  # entry 2026-05-01 → 7/10 = 70일(climax 비억제)
    mocker.patch.object(runner, "compute_held_gates", return_value=_gates_both())
    mocker.patch.object(runner, "fetch_series", return_value=([], []))
    n_weak = mocker.patch.object(runner, "notify_sell_on_weakness")
    n_strong = mocker.patch.object(runner, "notify_sell_into_strength")
    mocker.patch.object(runner, "notify_stop_triggered")
    _bar(db, "HDCL1", date(2026, 7, 10), 15000.0)
    r = runner.run_daily_eval(db, as_of=date(2026, 7, 10)); db.commit()
    assert r["triggered"] == 0 and r["decline_fired"] == 1 and r["climax_fired"] == 0
    n_weak.assert_called_once(); n_strong.assert_not_called()   # 라벨은 앞선 것(약세)
    assert n_weak.call_args.kwargs["signals"] == ["ta_d_daily_max_decline_now"]
    assert n_weak.call_args.kwargs["climax_also"] is True
    runner.run_daily_eval(db, as_of=date(2026, 7, 10)); db.commit()
    assert n_weak.call_count == 1  # 멱등
    with db.cursor() as cur:
        cur.execute("SELECT fired, mode, signals, climax_also_fired FROM position_decline_evaluations "
                    "WHERE position_id=%s", (pid,))
        assert cur.fetchone() == (True, "anchored", ["ta_d_daily_max_decline_now"], True)
        cur.execute("SELECT fired FROM position_climax_evaluations WHERE position_id=%s", (pid,))
        assert cur.fetchone() == (True,)  # climax 도 기록(병기)
    _runner_cleanup(db, "HDCL1")


def test_runner_stop_precedes_decline(db, mocker):
    from kr_pipeline.trade_management import runner
    pid = _runner_seed(db, "HDCL2")
    cg = mocker.patch.object(runner, "compute_held_gates", return_value=_gates_both())
    n_weak = mocker.patch.object(runner, "notify_sell_on_weakness")
    mocker.patch.object(runner, "notify_stop_triggered")
    _bar(db, "HDCL2", date(2026, 7, 10), 9000.0)  # < 초기 스탑 9,200
    r = runner.run_daily_eval(db, as_of=date(2026, 7, 10)); db.commit()
    assert r["triggered"] == 1 and r["decline_fired"] == 0
    cg.assert_not_called(); n_weak.assert_not_called()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM position_decline_evaluations WHERE position_id=%s", (pid,))
        assert cur.fetchone()[0] == 0
    _runner_cleanup(db, "HDCL2")


def test_runner_climax_notifies_when_decline_silent(db, mocker):
    from kr_pipeline.trade_management import runner
    pid = _runner_seed(db, "HDCL3")
    g = _gates_both(); g["ta_d_daily_max_decline_now"] = False
    mocker.patch.object(runner, "compute_held_gates", return_value=g)
    n_weak = mocker.patch.object(runner, "notify_sell_on_weakness")
    n_strong = mocker.patch.object(runner, "notify_sell_into_strength")
    mocker.patch.object(runner, "notify_stop_triggered")
    _bar(db, "HDCL3", date(2026, 7, 10), 15000.0)
    r = runner.run_daily_eval(db, as_of=date(2026, 7, 10)); db.commit()
    assert r["decline_fired"] == 0 and r["climax_fired"] == 1
    n_weak.assert_not_called(); n_strong.assert_called_once()
    with db.cursor() as cur:
        cur.execute("SELECT fired, climax_also_fired FROM position_decline_evaluations WHERE position_id=%s", (pid,))
        assert cur.fetchone() == (False, True)
    _runner_cleanup(db, "HDCL3")


# ---------- 백테스트: reason=decline · 우선순위 · 병기 · decline_sell OFF ----------

from tests.test_trade_held_climax import _bars, _fired, _tdata  # noqa: E402


def _hd(fired=True, **over):
    base = dict(fired=fired, hold_days=10, signals=("ta_d_daily_max_decline_now",), mode="anchored",
                anchor_week="2025-06-06", weeks_since=30, maturity_ok=True,
                ta_max_decline_now=False, ta_d_daily_max_decline_now=True)
    base.update(over)
    return HeldDeclineDecision(**base)


def test_backtest_decline_exit_inside_hold_min(mocker):
    """진입 10 거래일 뒤 decline 발화 → 8주 안이라도 reason=decline 전량 청산(억제 없음)."""
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    seq = [(98, 200, 96), (104, 200, 97)] + [(104 + i * 0.5, 200, 97) for i in range(1, 40)]
    bars = _bars(start, seq)
    fire_day = bars[11].d
    mocker.patch.object(pf, "evaluate_held_decline",
                        side_effect=lambda g, e, d: _hd(fired=(d >= fire_day), hold_days=(d - e).days))
    mocker.patch.object(pf, "evaluate_held_climax", return_value=_fired(fired=False))
    r = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig())
    assert r["stats"]["exit_reasons"] == {"decline": 1}
    ex = r["stats"]["exits"][0]
    assert ex["date"] == fire_day.isoformat() and ex["also"] == []
    assert (fire_day - bars[1].d).days < TRADE_HOLD_MIN_DAYS
    # decline_sell=False → climax 만(False) → 청산 없음
    r2 = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig(decline_sell=False))
    assert r2["stats"]["exit_reasons"] == {}


def test_backtest_decline_precedes_climax_same_day_with_also(mocker):
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (104, 200, 97), (105, 200, 97)])
    mocker.patch.object(pf, "evaluate_held_decline", return_value=_hd())
    mocker.patch.object(pf, "evaluate_held_climax", return_value=_fired())
    r = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig())
    assert r["stats"]["exit_reasons"] == {"decline": 1}
    assert r["stats"]["exits"][0]["also"] == ["climax"]


def test_backtest_stop_precedes_decline_same_day(mocker):
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (104, 200, 97), (90, 200, 97)])
    mocker.patch.object(pf, "evaluate_held_decline", return_value=_hd())
    mocker.patch.object(pf, "evaluate_held_climax", return_value=_fired())
    r = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig())
    assert r["stats"]["exit_reasons"] == {"stop8": 1}


def test_backtest_synthetic_without_weekly_never_fires_decline():
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (104, 200, 97)] + [(104 + i * 0.5, 200, 97) for i in range(1, 70)])
    r = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig())
    assert "decline" not in r["stats"]["exit_reasons"]  # 주봉 없음 → left_censored → None


def test_production_and_backtest_use_same_decline_function():
    import kr_pipeline.backtest.portfolio as pf
    from kr_pipeline.trade_management import runner
    assert pf.evaluate_held_decline is runner.evaluate_held_decline is evaluate_held_decline
