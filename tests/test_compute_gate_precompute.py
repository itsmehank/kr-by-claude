# tests/test_compute_gate_precompute.py
"""(#22) B 게이트 선계산 순수 함수 단위테스트.

프롬프트 §3.1/§3.2/§3.5 의 정량 게이트가 코드에서 결정론으로 재현되는지 검증.
null 규약: 입력 결측 → 해당 게이트 None (프롬프트: go_now 필요 게이트 None = go_now 금지).
"""
import pytest

from kr_pipeline.llm_runner.compute.gate_precompute import compute_gates


def _row(date, o, h, l, c, v, flag=False):
    return {
        "date": date, "open": o, "high": h, "low": l, "close": c,
        "volume": v, "distribution_day_flag": flag,
    }


def _rows(n=20, flag_last3=0, flag_days45=0):
    """단조 상승 20행. flag_last3: 마지막 3행 중 분배일 수, flag_days45: 그 이전(5일창 잔여) 분배일 수."""
    rows = []
    for i in range(n):
        base = 100.0 + i
        rows.append(_row(f"2026-07-{i+1:02d}", base, base + 2.0, base - 2.0, base + 1.0, 1000))
    for i in range(flag_last3):
        rows[-1 - i]["distribution_day_flag"] = True
    for i in range(flag_days45):
        rows[-4 - i]["distribution_day_flag"] = True
    return rows


def _metrics(close=125.0, volume=1500, avg=1000.0, sma_50=110.0, sma_21=118.0):
    return {
        "close": close, "volume": volume, "avg_volume_50d": avg,
        "volume_ratio": (volume / avg) if (volume and avg) else None,
        "sma_50": sma_50, "sma_21": sma_21,
    }


def _prior(pivot=120.0, base_low=100.0):
    return {"pivot_price": pivot, "base_low": base_low}


def _mkt(status="confirmed_uptrend", dist=2):
    return {
        "current_status": status,
        "distribution_day_count_last_25_sessions": dist,
    }


def _tt(passed=8, marginal=0, none_margin=0):
    """8조건 detail. passed 개수만 True, marginal 개수는 margin<3, none_margin 은 margin None."""
    out = {}
    for i in range(1, 9):
        key = f"c{i}"
        is_pass = i <= passed
        if i <= marginal:
            margin = 1.5
        elif i <= marginal + none_margin:
            margin = None
        else:
            margin = 10.0
        out[key] = {"passed": is_pass, "margin_pct": margin}
    return out


def _gates(**over):
    kw = dict(
        ohlcv_20d=_rows(),
        current_metrics=_metrics(),
        prior_analysis=_prior(),
        market_context=_mkt(),
        conditions_detail=_tt(),
    )
    kw.update(over)
    return compute_gates(**kw)


# ---- volume band ----

def test_volume_band_pass_above_floor():
    g = _gates(current_metrics=_metrics(volume=1500, avg=1000.0))  # 1.5x
    assert g["volume_band"] == "pass"


def test_volume_band_boundary_14_is_wait():
    g = _gates(current_metrics=_metrics(volume=1400, avg=1000.0))  # 정확히 1.4
    assert g["volume_band"] == "wait_band"


def test_volume_band_below_12():
    g = _gates(current_metrics=_metrics(volume=1100, avg=1000.0))
    assert g["volume_band"] == "below"


def test_volume_band_null_when_ratio_missing():
    m = _metrics()
    m["volume_ratio"] = None
    g = _gates(current_metrics=m)
    assert g["volume_band"] is None


# ---- price / range position ----

def test_price_above_pivot():
    assert _gates()["price_above_pivot"] is True
    assert _gates(current_metrics=_metrics(close=119.0))["price_above_pivot"] is False


def test_close_range_position_upper_third():
    # 마지막 행: high=121, low=117, close=120 → pos=0.75
    g = _gates()
    assert g["close_range_pos"] == pytest.approx(0.75)
    assert g["close_upper_third"] is True
    assert g["close_middle_third"] is False


def test_close_range_position_middle_third():
    rows = _rows()
    rows[-1]["close"] = rows[-1]["low"] + (rows[-1]["high"] - rows[-1]["low"]) * 0.5
    g = _gates(ohlcv_20d=rows)
    assert g["close_upper_third"] is False
    assert g["close_middle_third"] is True


def test_close_range_position_null_when_flat_bar():
    rows = _rows()
    rows[-1]["high"] = rows[-1]["low"] = rows[-1]["close"] = 100.0
    g = _gates(ohlcv_20d=rows)
    assert g["close_range_pos"] is None
    assert g["close_upper_third"] is None


# ---- spread ----

def test_spread_ratio_and_wide_loose():
    rows = _rows()
    # 직전 19행 range=4.0 고정, 오늘 range 를 7.0 으로 (ratio 1.75 > 1.5)
    rows[-1]["high"] = rows[-1]["low"] + 7.0
    g = _gates(ohlcv_20d=rows)
    assert g["spread_ratio_vs_avg"] == pytest.approx(7.0 / 4.0)
    assert g["spread_wide_loose"] is True


def test_spread_not_wide_when_normal():
    g = _gates()
    assert g["spread_ratio_vs_avg"] == pytest.approx(1.0)
    assert g["spread_wide_loose"] is False


def test_spread_null_when_too_few_rows():
    g = _gates(ohlcv_20d=_rows(n=4))
    assert g["spread_ratio_vs_avg"] is None
    assert g["spread_wide_loose"] is None


# ---- distribution windows ----

def test_dist_counts_clean():
    g = _gates()
    assert g["dist_days_last_3"] == 0
    assert g["no_dist_3d"] is True
    assert g["dist_days_last_5"] == 0
    assert g["dist_3plus_5d"] is False


def test_dist_counts_abort_pattern():
    g = _gates(ohlcv_20d=_rows(flag_last3=2, flag_days45=1))
    assert g["dist_days_last_3"] == 2
    assert g["no_dist_3d"] is False
    assert g["dist_days_last_5"] == 3
    assert g["dist_3plus_5d"] is True


def test_dist_null_flag_not_counted():
    rows = _rows()
    rows[-1]["distribution_day_flag"] = None  # 미산출 = 미계수 (기존 규약)
    g = _gates(ohlcv_20d=rows)
    assert g["dist_days_last_3"] == 0
    assert g["no_dist_3d"] is True


# ---- abort inputs ----

def test_low_below_base_low():
    rows = _rows()
    rows[-1]["low"] = 99.0
    assert _gates(ohlcv_20d=rows)["low_below_base_low"] is True
    assert _gates()["low_below_base_low"] is False


def test_sma_breaches():
    g = _gates(current_metrics=_metrics(close=107.0, sma_50=110.0, sma_21=118.0))
    assert g["close_below_sma50_breach"] is True  # 107 < 110*0.98=107.8
    assert g["close_below_sma21"] is True
    g2 = _gates(current_metrics=_metrics(close=108.0, sma_50=110.0, sma_21=107.0))
    assert g2["close_below_sma50_breach"] is False  # 108 > 107.8
    assert g2["close_below_sma21"] is False


# ---- §3.5 사유-독립 회복 게이트 ----

def test_market_recovery_ok():
    assert _gates()["market_recovery_ok"] is True


def test_market_recovery_blocked_by_status():
    g = _gates(market_context=_mkt(status="rally_attempt", dist=0))
    assert g["market_recovery_ok"] is False


def test_market_recovery_blocked_at_demotion_count():
    g = _gates(market_context=_mkt(status="confirmed_uptrend", dist=5))
    assert g["market_recovery_ok"] is False
    g2 = _gates(market_context=_mkt(status="confirmed_uptrend", dist=4))
    assert g2["market_recovery_ok"] is True


def test_market_recovery_null_when_context_missing():
    g = _gates(market_context={"current_status": None,
                               "distribution_day_count_last_25_sessions": None})
    assert g["market_recovery_ok"] is None


def test_tt_recovery_ok_with_two_marginal():
    g = _gates(conditions_detail=_tt(passed=8, marginal=2))
    assert g["tt_all_passed"] is True
    assert g["tt_marginal_count"] == 2
    assert g["tt_recovery_ok"] is True


def test_tt_recovery_blocked_at_three_marginal():
    g = _gates(conditions_detail=_tt(passed=8, marginal=3))
    assert g["tt_recovery_ok"] is False


def test_tt_recovery_blocked_when_condition_failed():
    g = _gates(conditions_detail=_tt(passed=7))
    assert g["tt_all_passed"] is False
    assert g["tt_recovery_ok"] is False


def test_tt_none_margin_counts_as_marginal():
    g = _gates(conditions_detail=_tt(passed=8, marginal=2, none_margin=1))
    assert g["tt_marginal_count"] == 3
    assert g["tt_recovery_ok"] is False


def test_tt_null_when_detail_empty():
    g = _gates(conditions_detail={})
    assert g["tt_all_passed"] is None
    assert g["tt_recovery_ok"] is None


# ---- null 전파 ----

def test_null_propagation_when_metrics_missing():
    g = _gates(current_metrics={})
    assert g["price_above_pivot"] is None
    assert g["volume_band"] is None
    assert g["close_below_sma50_breach"] is None
    assert g["close_below_sma21"] is None


def test_null_when_no_ohlcv():
    g = _gates(ohlcv_20d=[])
    assert g["ohlcv_last_date"] is None
    assert g["close_range_pos"] is None
    assert g["dist_days_last_3"] is None
    assert g["low_below_base_low"] is None


def test_ohlcv_last_date_exposed():
    assert _gates()["ohlcv_last_date"] == "2026-07-20"
