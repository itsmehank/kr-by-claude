# kr_pipeline/market_context/compute/distribution_day.py
"""분포일 (Distribution Day) 계산 순수 함수.

정의 (O'Neil/Kacher):
- 종가가 전일 대비 -0.2% 이상 하락
- 거래량이 전일보다 많음
"""
import pandas as pd

from kr_pipeline.common.thresholds import (
    DISTRIBUTION_PCT_BASE,
    MARKET_DISTRIBUTION_LOOKBACK_DAYS,
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
    """오늘이 분포일인지 판정."""
    if yesterday_close == 0:
        return False
    pct_change = (today_close - yesterday_close) / yesterday_close * 100
    return pct_change <= pct_threshold and today_volume > yesterday_volume


def count_distribution_days(
    index_df: pd.DataFrame,
    end_idx: int,
    *,
    pct_threshold: float = DISTRIBUTION_PCT_BASE,
    lookback: int = MARKET_DISTRIBUTION_LOOKBACK_DAYS,
) -> int:
    """end_idx 기준 직전 lookback 세션 내 분포일 카운트.

    index_df 컬럼: close, volume. date 정렬 가정.
    end_idx 가 분포일이면 카운트에 포함.
    분포일 판정에 전일 데이터 필요하므로 i=0 은 카운트 불가.
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
    return count
