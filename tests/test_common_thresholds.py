"""SSOT thresholds 모듈의 import + 값 sanity test.

이 테스트는 SSOT 가 *현재 시스템 동작*과 일치하는 값을 가지는지 확인.
값 변경 (예: P0-2 의 1.25 → 1.0) 시 이 테스트를 함께 갱신해야 함.
"""
from kr_pipeline.common import thresholds


def test_gate_constants():
    assert thresholds.GATE_BREAKOUT_VOL_MULT == 1.0
    assert thresholds.GATE_PROMOTION_PRICE_RATIO == 0.95


def test_recent_window():
    assert thresholds.RECENT_CLASSIFICATION_WINDOW_DAYS == 7


def test_minervini_constants():
    assert thresholds.C3_SMA200_LOOKBACK_DAYS == 22
    assert thresholds.C6_W52LOW_MULT == 1.25
    assert thresholds.C7_W52HIGH_MULT == 0.75
    assert thresholds.C8_RS_RATING_MIN == 70


def test_pocket_pivot():
    assert thresholds.PP_DOWN_VOL_LOOKBACK_DAYS == 10


def test_breakout_volume_constants():
    assert thresholds.BREAKOUT_VOL_FLOOR == 1.4
    assert thresholds.BREAKOUT_VOL_PREFERRED == 1.5


def test_volume_constants():
    assert thresholds.STOCK_DISTRIBUTION_VOL_MULT == 1.0
    assert thresholds.VOLUME_DRY_UP_MULT == 0.5


def test_market_distribution():
    assert thresholds.MARKET_DISTRIBUTION_PCT_THRESHOLD == -0.2
    assert thresholds.MARKET_DISTRIBUTION_LOOKBACK_DAYS == 25


def test_ftd_constants():
    assert thresholds.FTD_RALLY_WINDOW_MIN_DAYS == 3
    assert thresholds.FTD_RALLY_WINDOW_MAX_DAYS == 15
    assert thresholds.FTD_LOW_LOOKBACK_DAYS == 15


def test_p2_1a_constants():
    """P2-1a 한국시장 보정 SSOT 상수 7개."""
    assert thresholds.NASDAQ_REFERENCE_SIGMA == 1.0
    assert thresholds.FTD_PCT_BASE == 1.4
    assert thresholds.DISTRIBUTION_PCT_BASE == -0.2
    assert thresholds.SIGMA_WINDOW_DAYS == 252
    assert abs(thresholds.SIGMA_MIN_DATA_RATIO - 200 / 252) < 1e-9
    assert thresholds.KOREAN_SIGMA_RATIO_FLOOR == 1.0
    assert thresholds.KOREAN_SIGMA_RATIO_CEILING == 2.5


def test_market_distribution_pct_threshold_aliased():
    """호환 별칭이 DISTRIBUTION_PCT_BASE 와 동일 값."""
    assert thresholds.MARKET_DISTRIBUTION_PCT_THRESHOLD == thresholds.DISTRIBUTION_PCT_BASE


def test_status_constants():
    assert thresholds.STATUS_CORRECTION_OFF_HIGH_PCT == -10.0
    assert thresholds.STATUS_DOWNTREND_OFF_HIGH_PCT == -15.0
    assert thresholds.STATUS_DIST_COUNT_FOR_FTD_INVALIDATION == 6
    assert thresholds.STATUS_FTD_RECENT_DAYS == 90
    assert thresholds.STATUS_FTD_INVALIDATION_DAYS == 10


def test_phase2i_cup_shape_constants():
    # book-anchor (변경 금지)
    assert thresholds.CUP_DEPTH_MAX_NORMAL_PCT == 33.0
    assert thresholds.CUP_DEPTH_MAX_BEAR_RECOVERY_PCT == 50.0
    assert thresholds.CUP_PRIOR_UPTREND_MIN_PCT == 30.0
    assert thresholds.HANDLE_DEPTH_BULL_MIN_PCT == 8.0
    assert thresholds.HANDLE_DEPTH_BULL_MAX_PCT == 12.0
    assert thresholds.HANDLE_LEGIT_MIN_DAYS == 5          # book-anchor 길이 게이트 (≠ HANDLE_MIN_DAYS heuristic)
    assert thresholds.MIN_BASE_WEEKS == {
        "cup_with_handle": 7, "flat_base": 5, "double_bottom": 7, "vcp": 5,
    }
    # 향후 다패턴 트리용 (i) 미소비 — 값 drift 잠금
    assert thresholds.FLAT_BASE_DEPTH_MAX_PCT == 15.0
    assert thresholds.FLAT_BASE_PRIOR_UPTREND_MIN_PCT == 20.0


def test_phase2i_handle_heuristic_constants():
    # heuristic (튜닝 가능)
    assert thresholds.HANDLE_DEEP_RATIO == 0.33
    assert thresholds.HANDLE_VOLUME_NOT_CONTRACTING_RATIO == 0.80
    assert thresholds.HANDLE_MIN_DAYS == 3
    assert thresholds.BASE_MIN_DAYS == 5
    assert thresholds.HANDLE_POSITION_LOW_RATIO == 0.33


def test_phase2i_failed_breakout_and_band():
    assert thresholds.FAILED_BREAKOUT_K_DAYS == 5
    assert thresholds.FAILED_BREAKOUT_CONSECUTIVE_BELOW == 2
    assert thresholds.MEASUREMENT_TOLERANCE_PCT == 5.0


def test_rs_line_window_constants():
    from kr_pipeline.common import thresholds as t
    assert t.RS_LINE_UPTREND_SHORT_WEEKS == 6
    assert t.RS_LINE_UPTREND_LONG_WEEKS == 13
    assert t.RS_LINE_DECLINE_GATE_WEEKS == 30
