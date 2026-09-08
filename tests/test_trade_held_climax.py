"""(항목 ③ 2026-09-08) 보유 종목 climax 강세 매도 — 결합식·8주 억제·3모드·parity·러너·백테스트."""
from datetime import date, timedelta

import pytest

from kr_pipeline.common.thresholds import TRADE_HOLD_MIN_DAYS
from kr_pipeline.trade_management.held_climax import (
    HELD_CLIMAX_TRIGGERS, HeldClimaxDecision, evaluate_held_climax, gates_from_series,
    fetch_series, slice_upto,
)

ENTRY = date(2026, 1, 5)
LATE = ENTRY + timedelta(days=TRADE_HOLD_MIN_DAYS)          # 경계: 56일 = 미억제
EARLY = ENTRY + timedelta(days=TRADE_HOLD_MIN_DAYS - 1)     # 55일 = 억제


def _g(**over):
    g = {"left_censored": False, "no_transition": False, "quality_flag": False,
         "anchor_week": "2025-06-06", "weeks_since": 30,
         "maturity_ok": True, "p2_accel_ok": True, "scope_active": True,
         **{k: False for k in HELD_CLIMAX_TRIGGERS}}
    g.update(over)
    return g


# ---------- 결합식 각 항 ----------

def test_fires_when_all_terms_hold():
    d = evaluate_held_climax(_g(t2_max_volume_now=True), ENTRY, LATE)
    assert d.fired is True and d.triggers == ("t2_max_volume_now",) and d.mode == "anchored"


@pytest.mark.parametrize("miss", ["maturity_ok", "p2_accel_ok", "scope_active"])
def test_each_precondition_required(miss):
    d = evaluate_held_climax(_g(t1_max_spread_now=True, **{miss: False}), ENTRY, LATE)
    assert d.fired is False


def test_no_trigger_no_fire_and_any_trigger_fires():
    assert evaluate_held_climax(_g(), ENTRY, LATE).fired is False
    for k in HELD_CLIMAX_TRIGGERS:
        assert evaluate_held_climax(_g(**{k: True}), ENTRY, LATE).fired is True, k


def test_null_trigger_is_unevaluated_not_fired():
    # #157 규약: null 트리거는 미평가 — 나머지로만 OR
    d = evaluate_held_climax(_g(t5_daily_max_up_now=None, t6_daily_max_spread_now=None), ENTRY, LATE)
    assert d.fired is False and d.triggers == ()
    d2 = evaluate_held_climax(_g(t5_daily_max_up_now=None, t4_ok=True), ENTRY, LATE)
    assert d2.fired is True


# ---------- 8주 억제 경계 ----------

def test_hold_min_boundary():
    g = _g(t2_max_volume_now=True)
    early = evaluate_held_climax(g, ENTRY, EARLY)
    assert early.fired is False and early.suppressed is True and early.hold_days == TRADE_HOLD_MIN_DAYS - 1
    late = evaluate_held_climax(g, ENTRY, LATE)
    assert late.fired is True and late.suppressed is False and late.hold_days == TRADE_HOLD_MIN_DAYS


# ---------- 3모드 None ----------

@pytest.mark.parametrize("mode_kw,mode", [
    ({"left_censored": True, "maturity_ok": None, "p2_accel_ok": None, "scope_active": None}, "left_censored"),
    ({"no_transition": True, "anchor_week": None, "weeks_since": None}, "no_transition"),
    ({"quality_flag": True, "p2_accel_ok": None, "scope_active": None}, "quality"),
])
def test_missing_modes_yield_none(mode_kw, mode):
    d = evaluate_held_climax(_g(t2_max_volume_now=True, **mode_kw), ENTRY, LATE)
    assert d.fired is None and d.mode == mode


# ---------- replay(payload_builder 경로) ↔ production(gates_from_series) 일치 ----------

def _seed_stock(db, ticker):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, sector) VALUES (%s,'P','KOSPI','x') "
                    "ON CONFLICT DO NOTHING", (ticker,))
    db.commit()


def _drift(n, top, bot, vol=100_000):
    step = (top - bot) / max(n - 1, 1)
    return [(top - step * i, vol) for i in range(n)]


def _seed_weekly(db, ticker, rows, start):
    with db.cursor() as cur:
        for i, (p, v) in enumerate(rows):
            we = start + timedelta(weeks=i)
            cur.execute("""INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close,
                             adj_close, adj_high, adj_low, volume, value, trading_days)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,5) ON CONFLICT DO NOTHING""",
                        (ticker, we, p, p * 1.02, p * 0.98, p, p, p * 1.02, p * 0.98, v, v * p))
    db.commit()


def _seed_daily(db, ticker, rows):
    with db.cursor() as cur:
        for d, c in rows:
            cur.execute("""INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close,
                             adj_high, adj_low, volume, value)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (ticker, d, c, c * 1.01, c * 0.99, c, c, c * 1.01, c * 0.99, 100_000, 100_000 * c))
    db.commit()


def test_gates_from_series_matches_payload_builder_path(db):
    """production(fetch_series→gates_from_series) 과 replay(payload_builder 개별 조회) 가
    같은 symbol·date 에서 §6.1 전 필드 일치. anchored 픽스처(65주 드리프트+돌파+19주 상승)."""
    from api.services.payload_builder import (
        _anchor_baseline_start, _fetch_daily_ohlcv, _fetch_daily_since, _fetch_weekly_full,
    )
    from kr_pipeline.llm_runner.compute.climax_topping import (
        compute_climax_gates, compute_daily_extremes, find_anchor,
    )
    ticker = "HCLX1"
    _seed_stock(db, ticker)
    start = date(2018, 1, 5)
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] + [(1100.0 + 15 * i, 110_000) for i in range(1, 20)]
    _seed_weekly(db, ticker, rows, start)
    on_date = start + timedelta(weeks=len(rows) - 1)
    # 일봉: anchor 주 월요일 −7일 ~ on_date 연속(주말 포함), 완만 상승 + 오늘 +6%
    anchor_we = start + timedelta(weeks=65)
    monday = _anchor_baseline_start(anchor_we.isoformat())
    days = [monday - timedelta(days=k) for k in range(7, 0, -1)] + \
           [monday + timedelta(days=k) for k in range((on_date - monday).days + 1)]
    c, drows = 1000.0, []
    for i, d in enumerate(days):
        c *= 1.06 if d == on_date else (1.20 if d == monday else 1.002)
        drows.append((d, c))
    _seed_daily(db, ticker, drows)

    weekly, daily = fetch_series(db, ticker, on_date)
    prod = gates_from_series(weekly, daily)

    wk = _fetch_weekly_full(db, ticker, on_date)
    anchor = find_anchor(wk)
    replay = compute_climax_gates(wk, _fetch_daily_ohlcv(db, ticker, on_date, days=60)[-20:], anchor)
    bl = _anchor_baseline_start(anchor["anchor_week"])
    replay.update(compute_daily_extremes(_fetch_daily_since(db, ticker, bl, on_date), bl.isoformat(), anchor))
    assert anchor["anchor_week"] == anchor_we.isoformat() and prod["anchor_week"] == anchor["anchor_week"]
    for k in ("maturity_ok", "p2_accel_ok", "scope_active", *HELD_CLIMAX_TRIGGERS, "quality_flag"):
        assert prod[k] == replay[k], k
    # slice_upto 로 절단한 전 이력도 같은 결과(backtest 경로)
    wk_all, dl_all = fetch_series(db, ticker, on_date + timedelta(days=30))
    sl = gates_from_series(*slice_upto(wk_all, dl_all, on_date))
    for k in ("anchor_week", "maturity_ok", "p2_accel_ok", *HELD_CLIMAX_TRIGGERS):
        assert sl[k] == prod[k], k
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (ticker,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (ticker,))
    db.commit()


# ---------- 러너: 스탑 우선 · 발화 알림 · 멱등 ----------

def _fired(**over):
    base = dict(fired=True, suppressed=False, hold_days=70, triggers=("t2_max_volume_now",),
                mode="anchored", anchor_week="2025-06-06", weeks_since=30,
                maturity_ok=True, p2_accel_ok=True, scope_active=True)
    base.update(over)
    return HeldClimaxDecision(**base)


def _runner_seed(db, symbol, entry_price=10000.0):
    from kr_pipeline.trade_management.store import open_position
    with db.cursor() as cur:
        cur.execute("DELETE FROM position_climax_evaluations WHERE position_id IN "
                    "(SELECT id FROM positions WHERE symbol=%s)", (symbol,))
        cur.execute("DELETE FROM position_stop_evaluations WHERE position_id IN "
                    "(SELECT id FROM positions WHERE symbol=%s)", (symbol,))
        cur.execute("DELETE FROM positions WHERE symbol=%s", (symbol,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (symbol,))
        cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (symbol,))
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
                    (symbol, symbol))
    pid = open_position(db, symbol=symbol, entry_date=date(2026, 5, 1), entry_price=entry_price, quantity=10)
    db.commit()
    return pid


def _runner_cleanup(db, symbol):
    """테스트 간 오염 방지 — 러너는 open 포지션 전체를 평가하므로 남기면 다른 테스트의 카운트를 바꾼다."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM position_climax_evaluations WHERE position_id IN "
                    "(SELECT id FROM positions WHERE symbol=%s)", (symbol,))
        cur.execute("DELETE FROM position_stop_evaluations WHERE position_id IN "
                    "(SELECT id FROM positions WHERE symbol=%s)", (symbol,))
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


def test_runner_fires_notifies_and_is_idempotent(db, mocker):
    from kr_pipeline.trade_management import runner
    pid = _runner_seed(db, "HCLX2")
    mocker.patch.object(runner, "compute_held_climax", return_value=_fired())
    notify = mocker.patch.object(runner, "notify_sell_into_strength")
    mocker.patch.object(runner, "notify_stop_triggered")
    _bar(db, "HCLX2", date(2026, 7, 10), 15000.0)  # 스탑(9,200) 위 → not triggered
    r = runner.run_daily_eval(db, as_of=date(2026, 7, 10)); db.commit()
    assert r["triggered"] == 0 and r["climax_fired"] == 1
    notify.assert_called_once()
    assert notify.call_args.kwargs["triggers"] == ["t2_max_volume_now"]
    runner.run_daily_eval(db, as_of=date(2026, 7, 10)); db.commit()
    assert notify.call_count == 1  # 멱등 재실행 중복 알림 없음
    with db.cursor() as cur:
        cur.execute("SELECT fired, suppressed, mode, triggers FROM position_climax_evaluations "
                    "WHERE position_id=%s", (pid,))
        rows = cur.fetchall()
    assert len(rows) == 1 and rows[0][0] is True and rows[0][2] == "anchored" and rows[0][3] == ["t2_max_volume_now"]
    _runner_cleanup(db, "HCLX2")


def test_runner_stop_takes_precedence_over_climax(db, mocker):
    from kr_pipeline.trade_management import runner
    pid = _runner_seed(db, "HCLX3")
    hc = mocker.patch.object(runner, "compute_held_climax", return_value=_fired())
    notify = mocker.patch.object(runner, "notify_sell_into_strength")
    mocker.patch.object(runner, "notify_stop_triggered")
    _bar(db, "HCLX3", date(2026, 7, 10), 9000.0)  # < initial stop 9,200 → triggered
    r = runner.run_daily_eval(db, as_of=date(2026, 7, 10)); db.commit()
    assert r["triggered"] == 1 and r["climax_fired"] == 0
    hc.assert_not_called(); notify.assert_not_called()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM position_climax_evaluations WHERE position_id=%s", (pid,))
        assert cur.fetchone()[0] == 0
    _runner_cleanup(db, "HCLX3")


def test_runner_records_none_and_suppressed_without_notify(db, mocker):
    from kr_pipeline.trade_management import runner
    pid = _runner_seed(db, "HCLX4")
    mocker.patch.object(runner, "compute_held_climax",
                        return_value=_fired(fired=None, mode="no_transition", anchor_week=None, weeks_since=None))
    notify = mocker.patch.object(runner, "notify_sell_into_strength")
    mocker.patch.object(runner, "notify_stop_triggered")
    _bar(db, "HCLX4", date(2026, 7, 10), 15000.0)
    r = runner.run_daily_eval(db, as_of=date(2026, 7, 10)); db.commit()
    assert r["climax_fired"] == 0
    notify.assert_not_called()
    with db.cursor() as cur:
        cur.execute("SELECT fired, mode FROM position_climax_evaluations WHERE position_id=%s", (pid,))
        assert cur.fetchone() == (None, "no_transition")
    _runner_cleanup(db, "HCLX4")


# ---------- 백테스트: reason=climax · 억제 · 5B OFF 불변 ----------

def _bars(start, seq):
    from kr_pipeline.backtest.trigger_sim import DayBar
    out, prev, d = [], None, start
    for close, vol, sma in seq:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(DayBar(d=d, close=close, volume=vol, sma_50=sma, avg_volume_50d=100.0, prev_close=prev))
        prev = close
        d += timedelta(days=1)
    return out


def _tdata(bars, pivot=100.0):
    from kr_pipeline.backtest.portfolio import TickerData
    from kr_pipeline.backtest.trigger_sim import WatchRow
    wr = [WatchRow(ticker="T", sat=bars[0].d - timedelta(days=2), pivot_price=pivot, base_low=90.0,
                   watch_reason="valid_base_awaiting_breakout")]
    return TickerData(market="KOSPI", bars=bars, watch_rows=wr, rs_by_date={b.d: 80 for b in bars}, phase_by_date={})


def test_backtest_climax_exit_after_hold_min(mocker):
    """돌파(진입) 후 60거래일 상승 유지 → held_climax 발화일에 reason=climax 전량 청산.
    합성 데이터에는 주봉이 없어(left_censored) 판정 함수를 날짜 조건으로 대체 — 시뮬 배선 검증."""
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    seq = [(98, 200, 96), (104, 200, 97)] + [(104 + i * 0.5, 200, 97) for i in range(1, 90)]
    bars = _bars(start, seq)
    t1 = bars[1].d
    fire_day = next(b.d for b in bars if (b.d - t1).days >= TRADE_HOLD_MIN_DAYS)
    def fake_eval(gates, entry_date, as_of, hold_min_days):
        return _fired(fired=(as_of >= fire_day), suppressed=(as_of - entry_date).days < hold_min_days,
                      hold_days=(as_of - entry_date).days)
    mocker.patch.object(pf, "evaluate_held_climax", side_effect=fake_eval)
    r = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig())
    assert r["stats"]["exit_reasons"] == {"climax": 1}
    assert r["stats"]["exits"][0]["date"] == fire_day.isoformat()
    assert r["stats"]["n_half_sells"] == 0  # 5B OFF 불변
    # climax_sell=False 면 청산 없음(보유 유지)
    r2 = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig(climax_sell=False))
    assert r2["stats"]["exit_reasons"] == {}


def test_backtest_stop_precedes_climax_same_day(mocker):
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (104, 200, 97), (90, 200, 97)])  # 3일차 < stop 95.68
    mocker.patch.object(pf, "evaluate_held_climax", return_value=_fired())
    r = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig())
    assert r["stats"]["exit_reasons"] == {"stop8": 1}


def test_backtest_synthetic_without_weekly_never_fires():
    # 주봉 전 이력이 없는 합성 TickerData → left_censored → fired None → 기존 테스트 동작 불변
    import kr_pipeline.backtest.portfolio as pf
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (104, 200, 97)] + [(110, 200, 97)] * 70)
    r = pf.run_portfolio({"T": _tdata(bars)}, pf.PortfolioConfig())
    assert "climax" not in r["stats"]["exit_reasons"]
