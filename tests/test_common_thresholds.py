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


def test_volume_constants():
    assert thresholds.STOCK_DISTRIBUTION_VOL_MULT == 1.0
    assert thresholds.VOLUME_DRY_UP_MULT == 0.5


def test_market_distribution():
    assert thresholds.MARKET_DISTRIBUTION_PCT_THRESHOLD == -0.2
    assert thresholds.MARKET_DISTRIBUTION_LOOKBACK_DAYS == 25


def test_ftd_constants():
    assert thresholds.FTD_PCT_THRESHOLD == {"KOSPI": 1.4, "KOSDAQ": 1.4}
    assert thresholds.FTD_RALLY_WINDOW_MIN_DAYS == 3
    assert thresholds.FTD_RALLY_WINDOW_MAX_DAYS == 15
    assert thresholds.FTD_LOW_LOOKBACK_DAYS == 15


def test_status_constants():
    assert thresholds.STATUS_CORRECTION_OFF_HIGH_PCT == -10.0
    assert thresholds.STATUS_DOWNTREND_OFF_HIGH_PCT == -15.0
    assert thresholds.STATUS_DIST_COUNT_FOR_FTD_INVALIDATION == 6
    assert thresholds.STATUS_FTD_RECENT_DAYS == 90
    assert thresholds.STATUS_FTD_INVALIDATION_DAYS == 10
