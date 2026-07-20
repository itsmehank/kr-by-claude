# kr_pipeline/market_context/compute/distribution_day.py
"""분포일 (Distribution Day) 계산 순수 함수.

정의 (O'Neil/Kacher):
1. classic — 종가가 전일 대비 -0.2% 이상 하락(σ-보정 임계) + 거래량이 전일보다 많음.
2. stalling/churning (이슈 #55, HMMS p.209-210) — 거래량은 전일보다 많은데 가격이
   정체(0 ≤ Δ% ≤ |σ-보정 임계| — classic 임계의 미러 밴드)하고 일중 range 하단 절반에
   마감한 날. 상단 절반 마감이면 미계수 (원전 예외). range 0 봉은 판정 불가 → 미계수.
"""
import pandas as pd

from kr_pipeline.common.thresholds import (
    DISTRIBUTION_PCT_BASE,
    MARKET_DISTRIBUTION_LOOKBACK_DAYS,
    MARKET_STALL_CLOSE_RANGE_POS_MAX,
)

# P2-1a: DISTRIBUTION_DAY_PCT_THRESHOLD 호환 별칭은 DISTRIBUTION_PCT_BASE 로
# 이전. 시장별 보정 임계는 pct_threshold 인자로 modes.py 가 주입.
DISTRIBUTION_DAY_PCT_THRESHOLD = DISTRIBUTION_PCT_BASE


def is_distribution_day(
    today_close: float,
    today_volume: float,
    yesterday_close: float,
    yesterday_volume: float,
    *,
    pct_threshold: float = DISTRIBUTION_PCT_BASE,
) -> bool:
    """오늘이 (classic) 분포일인지 판정."""
    if yesterday_close == 0:
        return False
    pct_change = (today_close - yesterday_close) / yesterday_close * 100
    return pct_change <= pct_threshold and today_volume > yesterday_volume


def is_stalling_day(
    today_close: float,
    today_volume: float,
    today_high: float,
    today_low: float,
    yesterday_close: float,
    yesterday_volume: float,
    *,
    pct_threshold: float = DISTRIBUTION_PCT_BASE,
) -> bool:
    """오늘이 stalling(churning) 분포일인지 판정 (이슈 #55, HMMS p.209-210).

    조건 (모두 충족):
    - 거래량 > 전일 (classic 과 동일 조건)
    - 가격 정체: 0 ≤ Δ% ≤ |pct_threshold| — classic 하락 임계의 미러 밴드
      (σ-보정 임계가 주입되면 밴드도 자동 σ-상속). 하락일은 classic 경로 소관.
    - 일중 range 하단 절반 마감: (close-low)/(high-low) ≤
      MARKET_STALL_CLOSE_RANGE_POS_MAX. 상단 절반 마감 = 미계수 (원전 예외).
    - range 0 봉 (high == low) 은 위치 판정 불가 → False (fail-safe).
    """
    if yesterday_close == 0:
        return False
    if today_volume <= yesterday_volume:
        return False
    pct_change = (today_close - yesterday_close) / yesterday_close * 100
    if not (0 <= pct_change <= -pct_threshold):
        return False
    day_range = today_high - today_low
    if day_range <= 0:
        return False
    close_pos = (today_close - today_low) / day_range
    return close_pos <= MARKET_STALL_CLOSE_RANGE_POS_MAX


def count_distribution_days(
    index_df: pd.DataFrame,
    end_idx: int,
    *,
    pct_threshold: float = DISTRIBUTION_PCT_BASE,
    lookback: int = MARKET_DISTRIBUTION_LOOKBACK_DAYS,
    include_stalling: bool = True,
) -> int:
    """end_idx 기준 직전 lookback 세션 내 분포일 카운트 (classic + stalling 합산).

    index_df 컬럼: close, volume (+ include_stalling 이면 high, low 필수 — 결측 시
    KeyError fail-loud). date 정렬 가정.
    end_idx 가 분포일이면 카운트에 포함.
    분포일 판정에 전일 데이터 필요하므로 i=0 은 카운트 불가.
    include_stalling=False 는 구정의(classic only) 재생용 — 리플레이/비교 하네스 전용,
    운영 경로(modes.py)는 default True.
    """
    if end_idx <= 0 or len(index_df) == 0:
        return 0

    start_idx = max(1, end_idx - lookback + 1)   # 최소 1 (i=0 은 전일 없음)
    count = 0
    for i in range(start_idx, end_idx + 1):
        if i >= len(index_df):
            break
        today = index_df.iloc[i]
        yesterday = index_df.iloc[i - 1]
        if is_distribution_day(
            today_close=float(today["close"]),
            today_volume=float(today["volume"]),
            yesterday_close=float(yesterday["close"]),
            yesterday_volume=float(yesterday["volume"]),
            pct_threshold=pct_threshold,
        ):
            count += 1
        elif include_stalling and is_stalling_day(
            today_close=float(today["close"]),
            today_volume=float(today["volume"]),
            today_high=float(today["high"]),
            today_low=float(today["low"]),
            yesterday_close=float(yesterday["close"]),
            yesterday_volume=float(yesterday["volume"]),
            pct_threshold=pct_threshold,
        ):
            count += 1
    return count
