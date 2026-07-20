# kr_pipeline/market_context/compute/status.py
"""current_status 결정 룰 (6 우선순위).

룰 (위에서 아래로 첫 매칭):
1. close < SMA200 AND SMA50 < SMA200 AND off_high < -15 → downtrend
2. off_high < -10 AND close < SMA50 → correction
3. dist_count >= 6 AND FTD 10일 초과 → correction (FTD 무효)
4. FTD 90일 내 AND close > SMA50 AND dist_count < 6 → confirmed_uptrend
5. close > SMA50 AND (FTD 없거나 90일 초과) → rally_attempt
6. fallback: rally_attempt if close > SMA50 else correction
"""
from datetime import date

from kr_pipeline.common.thresholds import (
    STATUS_CORRECTION_OFF_HIGH_PCT,
    STATUS_DOWNTREND_OFF_HIGH_PCT,
    STATUS_DIST_COUNT_FOR_FTD_INVALIDATION,
    STATUS_FTD_RECENT_DAYS,
    STATUS_FTD_INVALIDATION_DAYS,
)

# 기존 module-level 상수는 SSOT 로 이전. 호환성 별칭 유지.
CORRECTION_OFF_HIGH_PCT = STATUS_CORRECTION_OFF_HIGH_PCT
DOWNTREND_OFF_HIGH_PCT = STATUS_DOWNTREND_OFF_HIGH_PCT
DIST_COUNT_THRESHOLD_FOR_FTD_INVALIDATION = STATUS_DIST_COUNT_FOR_FTD_INVALIDATION
FTD_RECENT_DAYS = STATUS_FTD_RECENT_DAYS
FTD_INVALIDATION_DAYS = STATUS_FTD_INVALIDATION_DAYS


def determine_status(
    close: float,
    sma_50: float | None,
    sma_200: float | None,
    pct_off_yearly_high: float,
    dist_count: int,
    last_ftd_date: date | None,
    today_date: date,
    *,
    dist_count_for_ftd_invalidation: int = STATUS_DIST_COUNT_FOR_FTD_INVALIDATION,
) -> str:
    """4 enum 중 하나 반환.

    dist_count_for_ftd_invalidation: 룰 3(FTD 무효화)·룰 4(confirmed 차단) 공용
    임계. default = SSOT (동작 중립) — 리플레이 하네스(이슈 #55 6→5 재측정)만 주입.
    """
    days_since_ftd = (today_date - last_ftd_date).days if last_ftd_date else None

    # 1. downtrend
    if (sma_200 is not None and sma_50 is not None
        and close < sma_200 and sma_50 < sma_200
        and pct_off_yearly_high < DOWNTREND_OFF_HIGH_PCT):
        return "downtrend"

    # 2. correction (가격 기준)
    if (pct_off_yearly_high < CORRECTION_OFF_HIGH_PCT
        and sma_50 is not None and close < sma_50):
        return "correction"

    # 3. correction (FTD 무효화)
    if (dist_count >= dist_count_for_ftd_invalidation
        and last_ftd_date is not None and days_since_ftd > FTD_INVALIDATION_DAYS):
        return "correction"

    # 4. confirmed_uptrend
    if (last_ftd_date is not None and days_since_ftd is not None
        and days_since_ftd <= FTD_RECENT_DAYS
        and sma_50 is not None and close > sma_50
        and dist_count < dist_count_for_ftd_invalidation):
        return "confirmed_uptrend"

    # 5. rally_attempt (FTD 없거나 오래된)
    if (sma_50 is not None and close > sma_50
        and (last_ftd_date is None or days_since_ftd > FTD_RECENT_DAYS)):
        return "rally_attempt"

    # 6. fallback
    if sma_50 is not None and close > sma_50:
        return "rally_attempt"
    return "correction"
