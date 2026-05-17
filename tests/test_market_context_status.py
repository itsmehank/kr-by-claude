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
