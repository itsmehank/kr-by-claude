# kr_pipeline/market_context/compute/distribution_day.py
"""분포일 (Distribution Day) 계산 순수 함수.

정의 (O'Neil/Kacher):
- 종가가 전일 대비 -0.2% 이상 하락
- 거래량이 전일보다 많음
"""
import pandas as pd


DISTRIBUTION_DAY_PCT_THRESHOLD = -0.2   # community standard, IBD


def is_distribution_day(
    today_close: float,
    today_volume: float,
    yesterday_close: float,
    yesterday_volume: float,
) -> bool:
    """오늘이 분포일인지 판정."""
    if yesterday_close == 0:
        return False
    pct_change = (today_close - yesterday_close) / yesterday_close * 100
    return pct_change <= DISTRIBUTION_DAY_PCT_THRESHOLD and today_volume > yesterday_volume


def count_distribution_days(index_df: pd.DataFrame, end_idx: int, lookback: int = 25) -> int:
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
        ):
            count += 1
    return count
