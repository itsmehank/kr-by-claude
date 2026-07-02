from datetime import date

from kr_pipeline.backtest.trigger_sim import WatchRow, DayBar, simulate


def _bars(seq):
    """seq: list of (day, close, volume, sma_50, avgvol, prev_close)"""
    return [DayBar(d=d, close=c, volume=v, sma_50=s, avg_volume_50d=a, prev_close=p)
            for (d, c, v, s, a, p) in seq]


def _watch(sat, pivot, base_low, reason):
    return WatchRow(ticker="T", sat=sat, pivot_price=pivot, base_low=base_low, watch_reason=reason)


def test_fresh_cross_with_volume_enters():
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),    # below pivot
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # fresh cross + vol>=avg
    ])
    trades, promo = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1
    assert trades[0].entry_date == date(2024, 1, 9)
    assert trades[0].entry_close == 105.0


def test_cross_without_volume_no_entry():
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 50, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 50, 95.0, 100.0, 98.0),    # vol < avg -> no breakout
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert trades == []


def test_extended_no_fresh_cross_no_entry():
    # production: extended reason not allowed -> never breakout_from_watch
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "extended")]
    bars = _bars([
        (date(2024, 1, 8), 110.0, 200, 95.0, 100.0, 108.0),  # already above pivot, no fresh cross
        (date(2024, 1, 9), 115.0, 200, 95.0, 100.0, 110.0),
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert trades == []
    # shadow: reason gate bypassed, but fresh_cross still false (already above) -> still no entry
    trades_s, _ = simulate("T", wr, bars, mode="shadow")
    assert trades_s == []


def test_exit_on_close_below_sma50():
    wr = [_watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # enter @105
        (date(2024, 1, 10), 94.0, 200, 95.0, 100.0, 105.0),  # close<sma50(95) -> exit, base_low=80 not hit
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1
    assert trades[0].exit_date == date(2024, 1, 10)
    assert trades[0].binding_exit == "sma_50"
    assert abs(trades[0].pnl_pct - ((94.0 / 105.0 - 1) * 100)) < 1e-6


def test_exit_on_close_below_base_low():
    wr = [_watch(date(2024, 1, 6), 100.0, 96.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 90.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 90.0, 100.0, 98.0),   # enter @105 (sma50=90)
        (date(2024, 1, 10), 95.0, 200, 90.0, 100.0, 105.0),  # close 95 < base_low 96, but > sma50 90 -> base_low binding
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1
    assert trades[0].binding_exit == "base_low"


def test_no_reentry_same_pivot():
    wr = [_watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # enter
        (date(2024, 1, 10), 94.0, 200, 95.0, 100.0, 105.0),  # exit (close<sma50)
        (date(2024, 1, 11), 98.0, 200, 95.0, 100.0, 94.0),   # below pivot again
        (date(2024, 1, 12), 106.0, 200, 95.0, 100.0, 98.0),  # fresh cross SAME pivot -> no re-entry
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1  # only the first


def test_reentry_after_pivot_update():
    wr = [
        _watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout"),
        _watch(date(2024, 1, 13), 100.0, 80.0, "valid_base_awaiting_breakout"),  # new Saturday -> pivot refreshed
    ]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # enter (pivot sat 1/6)
        (date(2024, 1, 10), 94.0, 200, 95.0, 100.0, 105.0),  # exit
        (date(2024, 1, 15), 98.0, 200, 95.0, 100.0, 94.0),   # after new sat 1/13
        (date(2024, 1, 16), 106.0, 200, 95.0, 100.0, 98.0),  # fresh cross under new pivot -> re-entry
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 2


def test_open_position_marked_to_last_bar():
    wr = [_watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # enter
        (date(2024, 1, 10), 120.0, 200, 95.0, 100.0, 105.0),  # never invalidated
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1
    assert trades[0].binding_exit == "open"
    assert trades[0].exit_date == date(2024, 1, 10)


def test_promotion_counted_not_entered():
    # close in [pivot*0.95, pivot] with volume -> promotion, no entry
    wr = [_watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 97.0, 200, 95.0, 100.0, 96.0),   # 0.95*100=95 <= 97 <=100 -> promotion
    ])
    trades, promo = simulate("T", wr, bars, mode="production")
    assert trades == []
    assert promo == 1


def test_shadow_bypasses_entry_gate_but_exit_unchanged():
    # 보완: shadow 치환(_SHADOW_REASON)은 *진입* 게이트만 우회. invalidation 은 watch_reason
    # 비의존이라 청산은 production 과 동일해야 한다.
    wr = [_watch(date(2024, 1, 6), 100.0, 80.0, "extended")]  # 비적격 reason
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # fresh cross
        (date(2024, 1, 10), 94.0, 200, 95.0, 100.0, 105.0),  # close<sma50 -> 청산
    ])
    # production: extended 비적격 -> 진입 없음
    assert simulate("T", wr, bars, mode="production")[0] == []
    # shadow: 이유 게이트 우회로 진입, 청산은 reason 비의존이라 sma_50 binding 동일
    st, promo_s = simulate("T", wr, bars, mode="shadow")
    assert len(st) == 1 and st[0].binding_exit == "sma_50"
    assert promo_s == 0


def test_invalid_mode_raises():
    import pytest
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "valid_base_awaiting_breakout")]
    with pytest.raises(ValueError):
        simulate("T", wr, [], mode="prod")


def test_market_relative_subtracts_index():
    from datetime import date
    from kr_pipeline.backtest.trigger_sim import Trade, market_relative
    t = Trade(ticker="T", watch_reason="x", pivot_sat=date(2024, 1, 6), pivot_price=100.0,
              base_low=90.0, entry_date=date(2024, 1, 9), entry_close=100.0,
              exit_date=date(2024, 1, 16), exit_close=110.0, pnl_pct=10.0, binding_exit="open")
    idx = {date(2024, 1, 9): 1000.0, date(2024, 1, 16): 1040.0}  # 시장 +4%
    # 종목 +10% - 시장 +4% = +6% 초과
    assert abs(market_relative(t, idx) - 6.0) < 1e-6


def test_loaders_smoke():
    """실 DB 에서 8종목 중 하나(가온칩스 399720)의 watch/일봉/지수 로드 동작."""
    from datetime import date
    from kr_pipeline.db.connection import connect
    from kr_pipeline.backtest.trigger_sim import (
        load_watchlist, load_daily_series, load_index_series, classify_rows,
    )
    with connect() as conn:
        wr = load_watchlist(conn, "399720", date(2024, 1, 6), date(2024, 12, 28))
        assert len(wr) >= 1
        bars = load_daily_series(conn, "399720", date(2024, 1, 1), date(2024, 12, 31))
        assert len(bars) > 200  # 2024 거래일
        idx = load_index_series(conn, "KOSDAQ", date(2024, 1, 1), date(2024, 12, 31))
        assert len(idx) > 200
        cls = classify_rows(wr)
        assert set(cls) == {"production", "shadow", "census"}
        assert sum(len(v) for v in cls.values()) == len(wr)  # rows conserved
        # adj-volume 일치 가드(raw 쓰면 기업행위 종목 오발화) — 101930 2024-06-13 adj=130800, raw=26160
        bars2 = load_daily_series(conn, "101930", date(2024, 1, 1), date(2024, 12, 31))
        bar_0613 = next(b for b in bars2 if str(b.d) == "2024-06-13")
        assert bar_0613.volume == 130800


def _bars_ohlc(seq):
    """seq: (day, close, volume, sma_50, avgvol, prev_close, open, high, low)"""
    return [DayBar(d=d, close=c, volume=v, sma_50=s, avg_volume_50d=a, prev_close=p,
                   open=o, high=h, low=lo)
            for (d, c, v, s, a, p, o, h, lo) in seq]


def test_chase_rule_blocks_entry_above_5pct():
    """prereg §2.1: fresh cross 여도 close > pivot×1.05 면 진입 안 함(신호 소멸).
    같은 pivot 의 이후 5% 이내 fresh cross 는 진입 가능(pivot 소멸 아님)."""
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 108.0, 200, 95.0, 100.0, 98.0),   # cross, but +8% > 5%
        (date(2024, 1, 10), 99.0, 200, 95.0, 100.0, 108.0),  # back below pivot
        (date(2024, 1, 11), 103.0, 200, 95.0, 100.0, 99.0),  # fresh cross, +3%
    ])
    trades, _ = simulate("T", wr, bars, mode="production", max_chase_pct=5.0)
    assert len(trades) == 1
    assert trades[0].entry_date == date(2024, 1, 11)
    assert trades[0].entry_close == 103.0
    # 기본(max_chase_pct=None)은 기존 동작: 1/9 에 진입
    trades0, _ = simulate("T", wr, bars, mode="production")
    assert trades0[0].entry_date == date(2024, 1, 9)


def test_optimistic_exit_at_stop_within_range():
    """prereg §2.3: 청산일 low ≤ stop ≤ high 면 낙관 체결가 = stop 레벨."""
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "valid_base_awaiting_breakout")]
    bars = _bars_ohlc([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0, 97.5, 99.0, 96.0),
        (date(2024, 1, 9), 103.0, 200, 95.0, 100.0, 98.0, 99.0, 104.0, 98.5),
        # sma_50=96 이탈 청산일: 종가 94, 장중 [93, 100] → stop(96) 체결 가능
        (date(2024, 1, 10), 94.0, 200, 96.0, 100.0, 103.0, 100.0, 100.0, 93.0),
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    t = trades[0]
    assert t.binding_exit == "sma_50"
    assert t.exit_close == 94.0                 # 하한(현행) = 종가
    assert t.exit_close_optimistic == 96.0      # 상한 = stop 레벨


def test_optimistic_exit_gap_down_uses_open():
    """prereg §2.3: 갭다운(high < stop)이면 낙관 체결가 = 시가."""
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "valid_base_awaiting_breakout")]
    bars = _bars_ohlc([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0, 97.5, 99.0, 96.0),
        (date(2024, 1, 9), 103.0, 200, 95.0, 100.0, 98.0, 99.0, 104.0, 98.5),
        # base_low=90 이탈, 갭다운: 시가 87, 고가 88 < stop(90) → 낙관 = 시가 87
        (date(2024, 1, 10), 85.0, 200, 95.0, 100.0, 103.0, 87.0, 88.0, 84.0),
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    t = trades[0]
    assert t.binding_exit == "base_low"
    assert t.exit_close == 85.0
    assert t.exit_close_optimistic == 87.0


def test_optimistic_exit_falls_back_to_close_without_ohlc():
    """OHLC 미제공(구형 DayBar) 시 낙관 체결가 = 종가(밴드 폭 0, 안전 폴백)."""
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 103.0, 200, 95.0, 100.0, 98.0),
        (date(2024, 1, 10), 94.0, 200, 96.0, 100.0, 103.0),
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert trades[0].exit_close_optimistic == 94.0
