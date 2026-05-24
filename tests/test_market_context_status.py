# tests/test_market_context_status.py
from datetime import date, timedelta
import pytest

from kr_pipeline.market_context.compute.status import determine_status


TODAY = date(2026, 5, 17)


def test_status_downtrend_basic():
    """close < sma_200 AND sma_50 < sma_200 AND off_high < -15% → downtrend."""
    result = determine_status(
        close=80.0, sma_50=90.0, sma_200=100.0,
        pct_off_yearly_high=-20.0,
        dist_count=0, last_ftd_date=None, today_date=TODAY,
    )
    assert result == "downtrend"


def test_status_correction_off_high():
    """off_high < -10% AND close < sma_50 → correction."""
    result = determine_status(
        close=85.0, sma_50=90.0, sma_200=88.0,
        pct_off_yearly_high=-12.0,
        dist_count=2, last_ftd_date=None, today_date=TODAY,
    )
    assert result == "correction"


def test_status_correction_dist_invalidates_ftd():
    """dist_count >= 6 AND FTD 10일 초과 → correction."""
    result = determine_status(
        close=95.0, sma_50=92.0, sma_200=88.0,
        pct_off_yearly_high=-5.0,
        dist_count=6, last_ftd_date=TODAY - timedelta(days=15), today_date=TODAY,
    )
    assert result == "correction"


def test_status_confirmed_uptrend():
    """FTD 90일 내 + close > sma_50 + dist < 6 → confirmed_uptrend."""
    result = determine_status(
        close=100.0, sma_50=95.0, sma_200=90.0,
        pct_off_yearly_high=-2.0,
        dist_count=2, last_ftd_date=TODAY - timedelta(days=30), today_date=TODAY,
    )
    assert result == "confirmed_uptrend"


def test_status_rally_attempt_no_ftd():
    """close > sma_50 + FTD 없음 → rally_attempt."""
    result = determine_status(
        close=100.0, sma_50=95.0, sma_200=90.0,
        pct_off_yearly_high=-5.0,
        dist_count=2, last_ftd_date=None, today_date=TODAY,
    )
    assert result == "rally_attempt"


def test_status_rally_attempt_old_ftd():
    """close > sma_50 + FTD 90일 초과 → rally_attempt."""
    result = determine_status(
        close=100.0, sma_50=95.0, sma_200=90.0,
        pct_off_yearly_high=-5.0,
        dist_count=2, last_ftd_date=TODAY - timedelta(days=120), today_date=TODAY,
    )
    assert result == "rally_attempt"


def test_status_fallback_below_sma50():
    """close < sma_50 fallback → correction."""
    result = determine_status(
        close=85.0, sma_50=90.0, sma_200=88.0,
        pct_off_yearly_high=-3.0,        # downtrend/correction off_high 조건 안 맞음
        dist_count=2, last_ftd_date=None, today_date=TODAY,
    )
    assert result == "correction"


# ===== P2-1a 통합 테스트 — σ 측정 → 보정 → status =====


def test_fallback_path_equals_pre_p2_1a_behavior():
    """fallback (σ=None) 경로 결과 == 보정 비활성 시 pre-P2-1a 동작.

    회귀 보장 — book_default_thresholds 의 ftd_pct=1.4, dist_pct=-0.2 가
    follow_through / distribution_day 의 default 와 일치 → 결과 같음.
    """
    from kr_pipeline.market_context.compute.volatility import book_default_thresholds
    from kr_pipeline.common.thresholds import FTD_PCT_BASE, DISTRIBUTION_PCT_BASE

    thresholds = book_default_thresholds(
        ftd_base=FTD_PCT_BASE, dist_base=DISTRIBUTION_PCT_BASE,
    )
    # ftd_pct/distribution_pct 가 follow_through/distribution_day 의 default 와 같음
    assert thresholds["ftd_pct"] == FTD_PCT_BASE  # = 1.4
    assert thresholds["distribution_pct"] == DISTRIBUTION_PCT_BASE  # = -0.2


def test_p2_1a_boundary_does_not_touch_stock_distribution():
    """P2-1a 시장 보정이 종목 레벨 distribution (P0-2 / volume.py) 에 안 닿음.

    경계 박스 (spec Section 9) — 종목 distribution 은 prompt §6 가 LLM 에
    직접 정의 안내. P2-1a 의 pct_threshold 변경은 volume.py 와 무관.
    """
    # volume.py 의 distribution_day default (STOCK_DISTRIBUTION_VOL_MULT) 가
    # 변경 안 됨을 확인 — P0-2 의 1.0 유지
    from kr_pipeline.common.thresholds import STOCK_DISTRIBUTION_VOL_MULT
    assert STOCK_DISTRIBUTION_VOL_MULT == 1.0  # P0-2 후 정정 값

    # 또한 volume.py 의 distribution_day 함수 시그니처가 P2-1a 변경에 영향
    # 안 받음을 import 가능성으로 sanity check
    from kr_pipeline.indicators.compute.volume import distribution_day
    assert callable(distribution_day)


def test_derive_thresholds_with_korean_kospi_sigma():
    """spec §1 의 관찰값 (KOSPI σ ≈ 2.34) 으로 derive 검증."""
    from kr_pipeline.market_context.compute.volatility import derive_market_thresholds
    from kr_pipeline.common.thresholds import (
        NASDAQ_REFERENCE_SIGMA, FTD_PCT_BASE, DISTRIBUTION_PCT_BASE,
        KOREAN_SIGMA_RATIO_FLOOR, KOREAN_SIGMA_RATIO_CEILING,
    )

    thresholds = derive_market_thresholds(
        sigma_pct=2.34,
        anchor_sigma=NASDAQ_REFERENCE_SIGMA,
        ftd_base=FTD_PCT_BASE,
        dist_base=DISTRIBUTION_PCT_BASE,
        clamp_floor=KOREAN_SIGMA_RATIO_FLOOR,
        clamp_ceiling=KOREAN_SIGMA_RATIO_CEILING,
    )
    # raw_ratio = 2.34, clamp [1.0, 2.5] → 2.34 (clamp 안 걸림)
    assert thresholds["raw_ratio"] == 2.34
    assert thresholds["ratio_applied"] == 2.34
    assert thresholds["clamped"] is False
    # FTD: 1.4 × 2.34 = 3.276
    assert thresholds["ftd_pct"] == pytest.approx(1.4 * 2.34)
    # distribution: -0.2 × 2.34 = -0.468
    assert thresholds["distribution_pct"] == pytest.approx(-0.2 * 2.34)


def test_panic_sigma_triggers_ceiling_clamp():
    """패닉기 σ 5-6% 시 ceiling 2.5 clamp 작동 — FTD 임계 폭주 차단."""
    from kr_pipeline.market_context.compute.volatility import derive_market_thresholds
    from kr_pipeline.common.thresholds import (
        NASDAQ_REFERENCE_SIGMA, FTD_PCT_BASE, DISTRIBUTION_PCT_BASE,
        KOREAN_SIGMA_RATIO_FLOOR, KOREAN_SIGMA_RATIO_CEILING,
    )

    thresholds = derive_market_thresholds(
        sigma_pct=5.5,
        anchor_sigma=NASDAQ_REFERENCE_SIGMA,
        ftd_base=FTD_PCT_BASE,
        dist_base=DISTRIBUTION_PCT_BASE,
        clamp_floor=KOREAN_SIGMA_RATIO_FLOOR,
        clamp_ceiling=KOREAN_SIGMA_RATIO_CEILING,
    )
    assert thresholds["raw_ratio"] == 5.5
    assert thresholds["ratio_applied"] == 2.5  # ceiling
    assert thresholds["clamped"] is True
    # FTD 임계가 1.4 × 2.5 = 3.5% 로 제한 (7.7% 가 아님)
    assert thresholds["ftd_pct"] == pytest.approx(3.5)
