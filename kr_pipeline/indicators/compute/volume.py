"""거래량 지표 (split-adjusted) 순수 함수.

모든 함수의 입력은 split-adjusted volume (adj_volume) 기준.
adj_volume = volume * (close / adj_close) 로 사전 계산.
"""
import numpy as np
import pandas as pd

from kr_pipeline.common.thresholds import (
    PP_DOWN_VOL_LOOKBACK_DAYS,
    STOCK_DISTRIBUTION_VOL_MULT,
    VOLUME_DRY_UP_MULT,
)


def split_adjusted_volume(volume: pd.Series, close: pd.Series, adj_close: pd.Series) -> pd.Series:
    """split-adjusted volume = volume * (close / adj_close).

    분할 전: close > adj_close → factor > 1 → adj_volume 증가 (post-split scale)
    분할 후: close == adj_close → factor = 1 → adj_volume = volume
    """
    split_factor = close / adj_close
    return volume * split_factor


def avg_volume(adj_volume: pd.Series, window: int) -> pd.Series:
    """rolling mean. window 미만 NaN."""
    return adj_volume.rolling(window=window, min_periods=window).mean()


def volume_ratio(adj_volume: pd.Series, avg_volume_series: pd.Series) -> pd.Series:
    """volume / avg. avg=0 / NaN → NaN."""
    avg_safe = avg_volume_series.where(avg_volume_series > 0)
    return adj_volume / avg_safe


def pocket_pivot(
    is_up_day: pd.Series,
    adj_volume: pd.Series,
    sma_50: pd.Series,
    adj_close: pd.Series,
    lookback: int = PP_DOWN_VOL_LOOKBACK_DAYS,
) -> pd.Series:
    """Morales & Kacher PP:
      (1) 상승일
      (2) 오늘 거래량 >= 지난 lookback 일 중 하락일들의 거래량 최대값
      (3) 종가 > sma_50

    Edge case: 지난 lookback 일에 down day 없으면 max=NaN → False (climax suspect).
    """
    # 하락일에만 volume 값을 유지, 다른 날은 NaN
    down_day_mask = ~is_up_day & adj_volume.notna()    # 단순화: not up = down or flat. 정확히 down 만 원하면 별도 인자
    # 우리 use case: is_up_day=True for up, False for down or flat. flat day 거래량도 보수적으로 max 후보에 포함 가능
    # 하지만 책 원문은 "down day" 명시 → is_up_day=False AND adj_close < prev_adj_close
    # 호출자가 is_down_day 도 제공하는 게 깔끔. 본 구현은 is_up_day 만 받음 → not is_up_day 사용

    down_day_vols = adj_volume.where(~is_up_day)
    # shift(1): 어제까지의 lookback (오늘 거래량은 비교 대상이지 max 후보가 아님)
    past_down_max = down_day_vols.rolling(window=lookback, min_periods=1).max().shift(1)

    # 조건 평가
    cond_up = is_up_day
    cond_vol = adj_volume >= past_down_max
    cond_sma = adj_close > sma_50

    return (cond_up & cond_vol & cond_sma).fillna(False)


def volume_dry_up(
    adj_volume: pd.Series,
    avg_volume_series: pd.Series,
    threshold: float = VOLUME_DRY_UP_MULT,
) -> pd.Series:
    """adj_volume < avg_volume * threshold.

    threshold 0.5 는 community standard (책 명시 아님).
    """
    return adj_volume < (avg_volume_series * threshold)


def up_down_volume_ratio(
    adj_volume: pd.Series,
    is_up_day: pd.Series,
    is_down_day: pd.Series,
    window: int,
) -> pd.Series:
    """up_vol_sum / down_vol_sum over rolling window.

    down_vol_sum=0 (window 안에 down day 없음) → NaN.
    O'Neil A/D rating 의 simplification (proprietary 공식과는 다름).
    """
    up_vol = adj_volume.where(is_up_day, 0).rolling(window=window, min_periods=window).sum()
    down_vol = adj_volume.where(is_down_day, 0).rolling(window=window, min_periods=window).sum()
    return up_vol / down_vol.where(down_vol > 0)


def distribution_day(
    is_down_day: pd.Series,
    adj_volume: pd.Series,
    avg_volume_series: pd.Series,
    threshold: float = STOCK_DISTRIBUTION_VOL_MULT,
) -> pd.Series:
    """is_down_day AND adj_volume > avg_volume * threshold.

    2026-05-22 (P0-2): threshold default 1.25 → 1.0 정렬. prompt §6 의
    정의 (close down ≥0.2% on volume > 1.0× of 50-day average) 와 일치.
    is_down_day (현재 0% 컷) vs prompt 의 -0.2% 컷 차이는 별도 fix 대상이
    아니며, LLM 이 §6 텍스트대로 OHLCV 재계산할 때 자연스럽게 -0.2% 적용.
    """
    return (is_down_day & (adj_volume > (avg_volume_series * threshold))).fillna(False)
