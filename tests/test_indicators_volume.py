# tests/test_indicators_volume.py
import pandas as pd
import numpy as np
import pytest
from kr_pipeline.indicators.compute.volume import (
    split_adjusted_volume,
    avg_volume,
    volume_ratio,
    pocket_pivot,
    volume_dry_up,
    up_down_volume_ratio,
    distribution_day,
)


# split-adjusted volume
def test_split_adjusted_volume_basic():
    """split_factor = close / adj_close"""
    close = pd.Series([100.0, 100.0, 50.0])    # 2:1 분할 후 50
    adj_close = pd.Series([50.0, 50.0, 50.0])  # back-adjusted (all 50)
    volume = pd.Series([1000.0, 1000.0, 2000.0])
    result = split_adjusted_volume(volume, close, adj_close)
    # 분할 전: split_factor=2 → adj_vol = 1000*2 = 2000
    # 분할 후: split_factor=1 → adj_vol = 2000*1 = 2000
    assert result.iloc[0] == 2000.0
    assert result.iloc[1] == 2000.0
    assert result.iloc[2] == 2000.0   # 연속


def test_split_adjusted_volume_no_split():
    """close == adj_close → split_factor=1, adj_vol = volume"""
    close = pd.Series([100.0, 110.0, 120.0])
    adj_close = pd.Series([100.0, 110.0, 120.0])
    volume = pd.Series([1000.0, 1100.0, 1200.0])
    result = split_adjusted_volume(volume, close, adj_close)
    assert list(result) == [1000.0, 1100.0, 1200.0]


# avg_volume / volume_ratio
def test_avg_volume_basic():
    """50일 rolling mean"""
    v = pd.Series([100.0] * 60)
    result = avg_volume(v, window=50)
    assert pd.isna(result.iloc[48])
    assert result.iloc[49] == 100.0
    assert result.iloc[59] == 100.0


def test_avg_volume_insufficient_history_returns_nan():
    v = pd.Series([100.0] * 30)
    result = avg_volume(v, window=50)
    assert result.isna().all()


def test_volume_ratio_basic():
    """ratio = volume / avg"""
    v = pd.Series([100.0, 200.0, 300.0])
    avg = pd.Series([100.0, 100.0, 100.0])
    result = volume_ratio(v, avg)
    assert list(result) == [1.0, 2.0, 3.0]


# pocket pivot
def test_pocket_pivot_basic():
    """is_up_day AND vol >= max(past 10 down vol) AND close > sma_50"""
    # 3일: 모두 상승, sma_50 < close, volume 충분
    adj_close = pd.Series([100.0, 110.0, 120.0])
    is_up_day = pd.Series([True, True, True])
    sma_50 = pd.Series([90.0, 90.0, 90.0])     # 모두 close 보다 낮음
    adj_volume = pd.Series([1500.0, 1500.0, 1500.0])
    # 지난 10일 down day 없음 → max=NaN → False (climax suspect)
    result = pocket_pivot(is_up_day, adj_volume, sma_50, adj_close, lookback=10)
    # 모두 NaN (down max = NaN → comparison = NaN → 우리 정의에서 False)
    # 함수는 NaN 또는 False 반환 (구현 정책)
    for r in result:
        assert r != True


def test_pocket_pivot_with_prior_down_day():
    """down day 가 있는 경우 정상 동작"""
    # 6 days: down, up, up, up, down, up
    # idx 5 (up day): past 10 down vol max = max(vol[0]=1000, vol[4]=800) = 1000
    # adj_volume[5] = 1500 → 1500 >= 1000 → True (다른 조건 OK 가정)
    adj_close = pd.Series([100.0, 105.0, 110.0, 115.0, 110.0, 115.0])
    is_up_day = pd.Series([False, True, True, True, False, True])
    sma_50 = pd.Series([90.0] * 6)
    adj_volume = pd.Series([1000.0, 1100.0, 1200.0, 1300.0, 800.0, 1500.0])
    result = pocket_pivot(is_up_day, adj_volume, sma_50, adj_close, lookback=10)
    assert result.iloc[5] == True


def test_pocket_pivot_fails_below_sma_50():
    """close <= sma_50 → False (책 필수 조건)"""
    adj_close = pd.Series([100.0, 105.0, 110.0, 95.0])
    is_up_day = pd.Series([False, True, True, False])    # idx 3 down day
    sma_50 = pd.Series([100.0, 100.0, 100.0, 100.0])     # all = 100
    adj_volume = pd.Series([1000.0, 500.0, 500.0, 800.0])
    # idx 1 up day, adj_close=105 > sma_50=100 → 통과
    # idx 2 up day, adj_close=110 > sma_50=100 → 통과
    # 다만 down vol max 가 idx 0 (1000) → 500 >= 1000 False
    result = pocket_pivot(is_up_day, adj_volume, sma_50, adj_close, lookback=10)
    # 별 의미 없음, 다음 테스트로

    # 명확한 below-sma case
    adj_close2 = pd.Series([95.0, 92.0, 96.0, 98.0])
    is_up_day2 = pd.Series([False, False, True, True])   # idx 2,3 up
    sma_50_2 = pd.Series([100.0] * 4)                    # 모두 close 보다 위
    adj_volume2 = pd.Series([1500.0, 1500.0, 1500.0, 1500.0])
    result2 = pocket_pivot(is_up_day2, adj_volume2, sma_50_2, adj_close2, lookback=10)
    # idx 2: adj_close=96, sma_50=100 → close<sma → False (regardless of volume)
    assert result2.iloc[2] != True
    assert result2.iloc[3] != True


def test_pocket_pivot_uses_gte_not_gt():
    """vol == max → True (>=, per book 원문)"""
    # idx 4: down vol max = 1000 (from idx 0). adj_volume[4] = 1000 정확히 같음
    adj_close = pd.Series([100.0, 105.0, 110.0, 115.0, 120.0])
    is_up_day = pd.Series([False, True, True, True, True])
    sma_50 = pd.Series([90.0] * 5)
    adj_volume = pd.Series([1000.0, 500.0, 500.0, 500.0, 1000.0])
    result = pocket_pivot(is_up_day, adj_volume, sma_50, adj_close, lookback=10)
    # idx 4: vol=1000, down max=1000 → True (>=)
    assert result.iloc[4] == True


# volume dry up
def test_volume_dry_up_threshold_50pct():
    """adj_volume < avg_volume * 0.5"""
    adj_volume = pd.Series([400.0, 500.0, 600.0])
    avg_volume_50 = pd.Series([1000.0, 1000.0, 1000.0])
    result = volume_dry_up(adj_volume, avg_volume_50, threshold=0.5)
    assert result.iloc[0] == True   # 400 < 500
    assert result.iloc[1] == False  # 500 not < 500
    assert result.iloc[2] == False  # 600 > 500


# up/down volume ratio
def test_up_down_volume_ratio_basic():
    """5 days, 3 up (vol 100+200+300=600), 2 down (vol 50+150=200) → 600/200=3.0"""
    adj_volume = pd.Series([100.0, 50.0, 200.0, 150.0, 300.0])
    is_up_day = pd.Series([True, False, True, False, True])
    is_down_day = pd.Series([False, True, False, True, False])
    result = up_down_volume_ratio(adj_volume, is_up_day, is_down_day, window=5)
    assert pd.isna(result.iloc[3])
    assert result.iloc[4] == 3.0


def test_up_down_volume_ratio_zero_division():
    """모두 up → down_vol=0 → NaN"""
    adj_volume = pd.Series([100.0] * 5)
    is_up_day = pd.Series([True] * 5)
    is_down_day = pd.Series([False] * 5)
    result = up_down_volume_ratio(adj_volume, is_up_day, is_down_day, window=5)
    assert pd.isna(result.iloc[4])


# distribution day
def test_distribution_day_basic():
    """is_down_day AND adj_volume > avg * 1.25"""
    is_down_day = pd.Series([False, True, True, False])
    adj_volume = pd.Series([1000.0, 1300.0, 1100.0, 1500.0])
    avg_volume_50 = pd.Series([1000.0] * 4)
    result = distribution_day(is_down_day, adj_volume, avg_volume_50, threshold=1.25)
    assert result.iloc[0] == False   # not down day
    assert result.iloc[1] == True    # down + 1300 > 1250
    assert result.iloc[2] == False   # down + 1100 not > 1250
    assert result.iloc[3] == False   # not down


def test_distribution_day_threshold_1_25x():
    """경계 case: vol == 1.25x → False (> not >=)"""
    is_down_day = pd.Series([True, True])
    adj_volume = pd.Series([1250.0, 1250.001])
    avg_volume_50 = pd.Series([1000.0, 1000.0])
    result = distribution_day(is_down_day, adj_volume, avg_volume_50, threshold=1.25)
    assert result.iloc[0] == False    # exactly 1.25x → not >
    assert result.iloc[1] == True     # slightly above
