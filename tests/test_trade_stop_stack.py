# tests/test_trade_stop_stack.py
"""(#3 이슈4) 3층 손절 스택 순수 함수 — 백테스트 검증 규칙의 production 이식.

의미론은 kr_pipeline/backtest/stop_variant_sim.py 의 시뮬 루프와 동일해야 한다:
max(initial, [breakeven if armed], [sma50]) = 유효 손절선, 종가 < 손절선 → 매도 신호.
래치는 당일 종가로 먼저 판정(당일 +20% 도달 시 당일부터 본전 바닥).
"""
import pytest

from kr_pipeline.trade_management.stop_stack import evaluate_stop


def test_initial_stop_binding_and_trigger():
    d = evaluate_stop(entry_price=10000, close=9100, sma_50=8000,
                      breakeven_armed=False)
    assert d.effective_stop == pytest.approx(9200.0)  # 10000 × 0.92
    assert d.binding == "initial_stop"
    assert d.triggered is True  # 9100 < 9200
    assert d.breakeven_armed is False


def test_no_trigger_when_close_at_or_above_stop():
    d = evaluate_stop(entry_price=10000, close=9200, sma_50=None,
                      breakeven_armed=False)
    assert d.triggered is False  # 경계(==)는 미발동 — 시뮬의 `close < stop` 동일


def test_breakeven_latch_arms_same_day():
    """당일 종가가 +20% 도달 → 당일부터 본전이 바닥 (시뮬 순서 동일)."""
    d = evaluate_stop(entry_price=10000, close=12000, sma_50=9000,
                      breakeven_armed=False)
    assert d.breakeven_armed is True
    assert d.effective_stop == pytest.approx(10000.0)
    assert d.binding == "breakeven"
    assert d.triggered is False


def test_breakeven_latch_persists_after_pullback():
    """래치는 해제 없음 — 이후 되밀림에도 본전 바닥 유지, 이탈 시 발동."""
    d = evaluate_stop(entry_price=10000, close=9900, sma_50=9000,
                      breakeven_armed=True)
    assert d.effective_stop == pytest.approx(10000.0)
    assert d.binding == "breakeven"
    assert d.triggered is True  # 9900 < 10000


def test_sma50_trail_overtakes():
    d = evaluate_stop(entry_price=10000, close=11000, sma_50=10500,
                      breakeven_armed=True)
    assert d.effective_stop == pytest.approx(10500.0)
    assert d.binding == "sma50_trail"
    assert d.triggered is False


def test_sma50_missing_excluded():
    d = evaluate_stop(entry_price=10000, close=10100, sma_50=None,
                      breakeven_armed=True)
    assert d.effective_stop == pytest.approx(10000.0)
    assert d.binding == "breakeven"


def test_uncle_point_guard():
    """initial_stop_pct 는 절대 상한(uncle point 10%) 초과 금지 — fail-closed."""
    with pytest.raises(ValueError, match="uncle"):
        evaluate_stop(entry_price=10000, close=9000, sma_50=None,
                      breakeven_armed=False, initial_stop_pct=0.12)


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        evaluate_stop(entry_price=0, close=9000, sma_50=None,
                      breakeven_armed=False)
    with pytest.raises(ValueError):
        evaluate_stop(entry_price=10000, close=-1, sma_50=None,
                      breakeven_armed=False)


def test_multi_day_walkthrough_matches_sim_semantics():
    """시뮬 시나리오 재현: 진입 → 상승(+20% 래치) → 50일선 추월 → 이탈 매도."""
    entry = 10000.0
    days = [
        # (close, sma50, expect_stop, expect_triggered)
        (10500, 9000, 9200.0, False),    # initial 만
        (12100, 9500, 10000.0, False),   # +21% → 래치, 본전 바닥
        (12500, 10800, 10800.0, False),  # 50일선이 본전 추월
        (10700, 10900, 10900.0, True),   # 50일선 이탈 → 매도
    ]
    armed = False
    for close, sma, want_stop, want_trig in days:
        d = evaluate_stop(entry_price=entry, close=close, sma_50=sma,
                          breakeven_armed=armed)
        armed = d.breakeven_armed
        assert d.effective_stop == pytest.approx(want_stop), (close, sma)
        assert d.triggered is want_trig, (close, sma)
    assert armed is True
