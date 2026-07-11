"""거래량 지표 (split-adjusted) 순수 함수.

모든 함수의 입력은 split-adjusted volume (adj_volume) 기준.
adj_volume 은 ingest 단계에서 daily_prices / weekly_prices 에 저장됨.
"""
import numpy as np
import pandas as pd

from kr_pipeline.common.thresholds import (
    PP_DOWN_VOL_LOOKBACK_DAYS,
    STOCK_DISTRIBUTION_PCT_DOWN,
    STOCK_DISTRIBUTION_VOL_MULT,
    VOLUME_DRY_UP_MULT,
)


def avg_volume(adj_volume: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    """rolling mean. min_periods 미지정 시 window(엄격).

    거래정지일 adj_volume 은 NULL(NaN) — rolling mean 은 NaN 제외 평균이므로 min_periods 만
    낮추면 고정 윈도우 유지하며 halt 거래일을 뺀 실평균. 일봉은 min_periods=40(≤10 halt 허용)."""
    mp = window if min_periods is None else min_periods
    return adj_volume.rolling(window=window, min_periods=mp).mean()


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


# 부동소수 경계 허용 오차 (% 포인트). 수정계수 곱해진 adj 가격의 정확 -0.2%
# 하락이 -0.19999999999998908 등으로 표현돼 경계 탈락하는 것 방지 (실측: 정확
# 경계 케이스의 ~25% miss, eps=1e-9 로 0 + 얕은 하락(-0.1999%) 오포함 없음).
_PCT_EPS = 1e-9


def distribution_day(
    daily_return_pct: pd.Series,
    adj_volume: pd.Series,
    avg_volume_series: pd.Series,
    threshold: float = STOCK_DISTRIBUTION_VOL_MULT,
    down_pct: float = STOCK_DISTRIBUTION_PCT_DOWN,
) -> pd.Series:
    """(daily_return_pct <= down_pct) AND adj_volume > avg_volume * threshold.

    2026-05-22 (P0-2): threshold default 1.25 → 1.0 정렬.
    2026-07-10 (#20): 하락 판정을 is_down_day(0% 컷) → 일간수익률 ≤ −0.2%
    (STOCK_DISTRIBUTION_PCT_DOWN) 로 교정 — prompt §6 정의 (close down ≥0.2%
    on volume > 1.0× of 50-day average) 와 정합. §6 이 flag 컬럼을
    authoritative 로 선언하므로 컷 불일치가 §6 카운트를 직접 왜곡했었다.
    up_down_volume_ratio 의 is_down(0% 컷) 은 A/D 의미론 (전체 하락일)
    대로 의도적으로 별개.

    halt 처리 (2026-07-11 #30 검증으로 정정): 정지일 adj_close 는 carry 로
    보존되므로(transform.nullify_halt_adj — production 실측 NULL 0건) 해제일
    return 은 carry 대비로 정상 계산되어 갭다운 분배가 탐지된다(최근 2년
    해제일 분배 후보 64건 전부 flag=True 실측). fill_method=None 의 NaN 전파는
    시계열에 NaN 이 실존할 때만 작동 — production adj_close 에는 해당 없음.
    """
    return (
        (daily_return_pct <= down_pct + _PCT_EPS)
        & (adj_volume > (avg_volume_series * threshold))
    ).fillna(False)
