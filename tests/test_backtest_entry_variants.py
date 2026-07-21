"""simulate entry_mode 변형 — 익일확인·눌림대기 (탐색용, 기본 모드 불변)."""
from datetime import date, timedelta

from kr_pipeline.backtest.trigger_sim import DayBar, WatchRow, simulate


def _bars(specs):
    """specs: [(close, low, volume)] — 2021-01-04 부터 연속 가정."""
    out = []
    d = date(2021, 1, 4)
    prev = None
    for close, low, vol in specs:
        out.append(DayBar(d=d, close=close, volume=vol, sma_50=50.0,
                          avg_volume_50d=1000, prev_close=prev, low=low))
        prev = close
        d += timedelta(days=1)
    return out


def _watch(pivot=100.0):
    # watch_reason 은 ALLOWED_WATCH_REASONS(trigger_gate.py) 소속이어야 돌파 발화
    return [WatchRow(ticker="T", sat=date(2021, 1, 2), pivot_price=pivot,
                     base_low=80.0, watch_reason="valid_base_awaiting_breakout")]


def test_default_mode_unchanged():
    """entry_mode 미지정 = 기존 동작(신호일 종가 진입)과 동일."""
    bars = _bars([(99, 95, 500), (105, 100, 2000), (110, 104, 900)])
    t_old, _ = simulate("T", _watch(), bars, mode="production")
    t_def, _ = simulate("T", _watch(), bars, mode="production", entry_mode="breakout")
    assert [(t.entry_date, t.entry_close) for t in t_old] == \
           [(t.entry_date, t.entry_close) for t in t_def]
    assert t_old and t_old[0].entry_date == bars[1].d          # 신호일 진입


def test_next_day_confirm_enters_on_confirmation():
    # 신호일(105) → 익일 106 >= 105 → 익일 종가 진입
    bars = _bars([(99, 95, 500), (105, 100, 2000), (106, 103, 900), (112, 105, 900)])
    tr, _ = simulate("T", _watch(), bars, mode="production", entry_mode="next_day_confirm")
    assert len(tr) == 1
    assert tr[0].entry_date == bars[2].d and tr[0].entry_close == 106


def test_next_day_confirm_signal_dies_without_confirmation():
    # 익일 104 < 105 → 소멸, 이후 재신호 없음(가격이 pivot 아래로)
    bars = _bars([(99, 95, 500), (105, 100, 2000), (104, 101, 900), (99, 95, 900)])
    tr, _ = simulate("T", _watch(), bars, mode="production", entry_mode="next_day_confirm")
    assert tr == []


def test_pullback_enters_on_dip_to_pivot():
    # 신호일(105) → 2일 뒤 low 100.5 <= 101(=pivot×1.01) → 그 날 종가 진입
    bars = _bars([(99, 95, 500), (105, 100, 2000), (107, 104, 900),
                  (103, 100.5, 900), (115, 102, 900)])
    tr, _ = simulate("T", _watch(), bars, mode="production", entry_mode="pullback")
    assert len(tr) == 1
    assert tr[0].entry_date == bars[3].d and tr[0].entry_close == 103


def test_pullback_expires_after_5_bars():
    # 5개 bar 내 눌림 없음 → 무거래
    specs = [(99, 95, 500), (105, 100, 2000)] + [(110 + i, 106, 900) for i in range(6)]
    tr, _ = simulate("T", _watch(), _bars(specs), mode="production", entry_mode="pullback")
    assert tr == []


def test_unknown_entry_mode_rejected():
    import pytest
    with pytest.raises(ValueError):
        simulate("T", _watch(), _bars([(99, 95, 500)]), mode="production", entry_mode="x")
