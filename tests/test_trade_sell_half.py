"""(#166 2026-09-08) 이익목표 절반매도(5B) 파리티 이식 — 순수 함수·러너(OFF/ON)·우선순위·백테스트 불변."""
from datetime import date, timedelta

import pytest

from kr_pipeline.common.thresholds import (
    EARLY_GAIN_DAYS, SELL_HALF_ENABLED, SELL_HALF_GAIN_PCT, TRADE_HOLD_MIN_DAYS,
)
from kr_pipeline.trade_management.sell_half import SellHalfState, evaluate_sell_half

E = date(2026, 3, 2)
P = 10000.0
T = P * (1 + SELL_HALF_GAIN_PCT)


def _ev(close, days, state=SellHalfState()):
    return evaluate_sell_half(entry_date=E, entry_price=P, close=close, as_of=E + timedelta(days=days), state=state)


def test_flag_default_off():
    assert SELL_HALF_ENABLED is False


# ---------- 21일 경계 ----------

def test_hit20_after_early_window_fires_immediately():
    d = _ev(T, EARLY_GAIN_DAYS + 1)
    assert d.fire and d.reason == "immediate" and d.hit20_new and d.within_early is False
    assert d.state.fired and d.state.hit20_date == E + timedelta(days=EARLY_GAIN_DAYS + 1)


def test_hit20_within_early_window_goes_pending():
    d = _ev(T, EARLY_GAIN_DAYS)  # 경계 = 21일 포함 → pending
    assert not d.fire and d.hit20_new and d.within_early is True
    assert d.state.half_pending and not d.state.fired


def test_below_target_no_hit():
    d = _ev(T - 0.01, EARLY_GAIN_DAYS + 5)
    assert not d.fire and not d.hit20_new and d.state == SellHalfState()


# ---------- 56일 대기·소멸 ----------

def test_pending_resolves_after_hold_min():
    st = SellHalfState(hit20_date=E + timedelta(days=5), half_pending=True)
    assert not _ev(T, TRADE_HOLD_MIN_DAYS, st).fire            # 56일 당일은 아직 (> 56 필요)
    d = _ev(T, TRADE_HOLD_MIN_DAYS + 1, st)
    assert d.fire and d.reason == "week8" and d.state.fired and not d.state.half_pending
    x = _ev(T - 1, TRADE_HOLD_MIN_DAYS + 1, st)
    assert not x.fire and x.state.half_expired and not x.state.half_pending


# ---------- 포지션당 1회 ----------

def test_fired_or_expired_is_terminal():
    for st in (SellHalfState(hit20_date=E, fired=True), SellHalfState(hit20_date=E, half_expired=True)):
        d = _ev(T * 2, TRADE_HOLD_MIN_DAYS + 10, st)
        assert not d.fire and d.state == st


# ---------- 러너: OFF 미동작 / ON 발화·멱등 / 우선순위 ----------

def _seed(db, symbol, entry_date, entry_price=P):
    from kr_pipeline.trade_management.store import open_position
    _cleanup(db, symbol)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
                    (symbol, symbol))
    pid = open_position(db, symbol=symbol, entry_date=entry_date, entry_price=entry_price, quantity=10)
    db.commit()
    return pid


def _cleanup(db, symbol):
    with db.cursor() as cur:
        for tbl in ("position_climax_evaluations", "position_stop_evaluations"):
            cur.execute(f"DELETE FROM {tbl} WHERE position_id IN (SELECT id FROM positions WHERE symbol=%s)", (symbol,))
        cur.execute("DELETE FROM positions WHERE symbol=%s", (symbol,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (symbol,))
        cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (symbol,))
    db.commit()


def _bar(db, symbol, d, close):
    with db.cursor() as cur:
        cur.execute("""INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,1000,1000) ON CONFLICT DO NOTHING""",
                    (symbol, d, close, close, close, close, close))
        cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close, sma_50) VALUES (%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING", (symbol, d, close, 9000.0))
    db.commit()


def _no_climax(mocker, runner):
    from kr_pipeline.trade_management.held_climax import HeldClimaxDecision
    return mocker.patch.object(runner, "compute_held_climax", return_value=HeldClimaxDecision(
        fired=False, suppressed=False, hold_days=30, triggers=(), mode="anchored", anchor_week="2025-06-06",
        weeks_since=30, maturity_ok=True, p2_accel_ok=False, scope_active=True))


def test_runner_off_does_nothing(db, mocker):
    from kr_pipeline.trade_management import runner
    assert runner.SELL_HALF_ENABLED is False
    pid = _seed(db, "SH1", date(2026, 5, 1))
    _no_climax(mocker, runner); mocker.patch.object(runner, "notify_stop_triggered")
    notify = mocker.patch.object(runner, "notify_sell_half")
    _bar(db, "SH1", date(2026, 6, 10), T + 100)  # +20% 초과, 21일 초과 — ON 이면 발화 조건
    r = runner.run_daily_eval(db, as_of=date(2026, 6, 10)); db.commit()
    assert r["half_fired"] == 0
    notify.assert_not_called()
    with db.cursor() as cur:
        cur.execute("SELECT hit20_date, half_fired_at FROM positions WHERE id=%s", (pid,))
        assert cur.fetchone() == (None, None)  # 블록 미진입 → 상태 무변경
    _cleanup(db, "SH1")


def test_runner_on_fires_once_and_persists(db, mocker):
    from kr_pipeline.trade_management import runner
    mocker.patch.object(runner, "SELL_HALF_ENABLED", True)
    pid = _seed(db, "SH2", date(2026, 5, 1))
    _no_climax(mocker, runner); mocker.patch.object(runner, "notify_stop_triggered")
    notify = mocker.patch.object(runner, "notify_sell_half")
    _bar(db, "SH2", date(2026, 6, 10), T + 100)
    r = runner.run_daily_eval(db, as_of=date(2026, 6, 10)); db.commit()
    assert r["half_fired"] == 1
    notify.assert_called_once()
    assert notify.call_args.kwargs["basis"] == "immediate"
    runner.run_daily_eval(db, as_of=date(2026, 6, 10)); db.commit()   # 멱등 재실행
    _bar(db, "SH2", date(2026, 6, 11), T + 500)
    runner.run_daily_eval(db, as_of=date(2026, 6, 11)); db.commit()   # 다음 날 — 포지션당 1회
    assert notify.call_count == 1
    with db.cursor() as cur:
        cur.execute("SELECT hit20_date, half_fired_at, half_pending FROM positions WHERE id=%s", (pid,))
        assert cur.fetchone() == (date(2026, 6, 10), date(2026, 6, 10), False)
    _cleanup(db, "SH2")


def test_runner_on_pending_then_week8(db, mocker):
    from kr_pipeline.trade_management import runner
    mocker.patch.object(runner, "SELL_HALF_ENABLED", True)
    e = date(2026, 5, 1)
    pid = _seed(db, "SH3", e)
    _no_climax(mocker, runner); mocker.patch.object(runner, "notify_stop_triggered")
    notify = mocker.patch.object(runner, "notify_sell_half")
    _bar(db, "SH3", e + timedelta(days=10), T + 1)          # 21일 내 도달 → pending
    runner.run_daily_eval(db, as_of=e + timedelta(days=10)); db.commit()
    notify.assert_not_called()
    with db.cursor() as cur:
        cur.execute("SELECT hit20_date, half_pending FROM positions WHERE id=%s", (pid,))
        assert cur.fetchone() == (e + timedelta(days=10), True)
    _bar(db, "SH3", e + timedelta(days=TRADE_HOLD_MIN_DAYS + 1), T + 1)   # 8주차 ≥ 목표 → 발화
    r = runner.run_daily_eval(db, as_of=e + timedelta(days=TRADE_HOLD_MIN_DAYS + 1)); db.commit()
    assert r["half_fired"] == 1 and notify.call_args.kwargs["basis"] == "week8"
    _cleanup(db, "SH3")


def test_runner_priority_stop_and_climax_before_half(db, mocker):
    from kr_pipeline.trade_management import runner
    from kr_pipeline.trade_management.held_climax import HeldClimaxDecision
    mocker.patch.object(runner, "SELL_HALF_ENABLED", True)
    pid = _seed(db, "SH4", date(2026, 5, 1))
    mocker.patch.object(runner, "compute_held_climax", return_value=HeldClimaxDecision(
        fired=True, suppressed=False, hold_days=40, triggers=("t2_max_volume_now",), mode="anchored",
        anchor_week="2025-06-06", weeks_since=30, maturity_ok=True, p2_accel_ok=True, scope_active=True))
    mocker.patch.object(runner, "notify_sell_into_strength"); mocker.patch.object(runner, "notify_stop_triggered")
    notify = mocker.patch.object(runner, "notify_sell_half")
    _bar(db, "SH4", date(2026, 6, 10), T + 100)  # climax 발화일 → 5B 미평가
    r = runner.run_daily_eval(db, as_of=date(2026, 6, 10)); db.commit()
    assert r["climax_fired"] == 1 and r["half_fired"] == 0
    notify.assert_not_called()
    with db.cursor() as cur:
        cur.execute("SELECT hit20_date FROM positions WHERE id=%s", (pid,))
        assert cur.fetchone()[0] is None
    _cleanup(db, "SH4")


# ---------- 백테스트: 같은 함수·리터럴→상수 후 동작 불변 ----------

def _bars(start, seq):
    from kr_pipeline.backtest.trigger_sim import DayBar
    out, prev, d = [], None, start
    for close, vol, sma in seq:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(DayBar(d=d, close=close, volume=vol, sma_50=sma, avg_volume_50d=100.0, prev_close=prev))
        prev = close; d += timedelta(days=1)
    return out


def _tdata(bars):
    from kr_pipeline.backtest.portfolio import TickerData
    from kr_pipeline.backtest.trigger_sim import WatchRow
    wr = [WatchRow(ticker="T", sat=bars[0].d - timedelta(days=2), pivot_price=100.0, base_low=90.0,
                   watch_reason="valid_base_awaiting_breakout")]
    return TickerData(market="KOSPI", bars=bars, watch_rows=wr, rs_by_date={b.d: 80 for b in bars}, phase_by_date={})


def test_backtest_uses_shared_function_and_flag_default():
    import kr_pipeline.backtest.portfolio as pf
    assert pf.PortfolioConfig().sell_half is SELL_HALF_ENABLED
    start = date(2024, 1, 8)
    seq = [(98, 200, 90), (101, 200, 95)] + [(101, 200, 95)] * 18 + [(122, 200, 95)]  # 21일 초과 후 +20.8%
    r_on = pf.run_portfolio({"T": _tdata(_bars(start, seq))}, pf.PortfolioConfig(sell_half=True))
    assert r_on["stats"]["n_half_sells"] == 1
    r_off = pf.run_portfolio({"T": _tdata(_bars(start, seq))}, pf.PortfolioConfig(sell_half=False))
    assert r_off["stats"]["n_half_sells"] == 0
    # 21일 내 도달 → 대기 → 8주차(>56일) 종가 ≥ 목표 → 절반매도
    seq2 = [(98, 200, 90), (101, 200, 95), (122, 200, 95)] + [(122, 200, 95)] * 45
    r2 = pf.run_portfolio({"T": _tdata(_bars(start, seq2))}, pf.PortfolioConfig(sell_half=True))
    assert r2["stats"]["n_half_sells"] == 1
    # 8주차 미달 → 소멸(절반매도 0), 8주 면제(exempt)는 별개로 유지됨
    seq3 = [(98, 200, 90), (101, 200, 95), (122, 200, 95)] + [(110, 200, 95)] * 45
    r3 = pf.run_portfolio({"T": _tdata(_bars(start, seq3))}, pf.PortfolioConfig(sell_half=True))
    assert r3["stats"]["n_half_sells"] == 0
