# tests/test_market_context_distribution_day.py
import pandas as pd
import pytest

from kr_pipeline.market_context.compute.distribution_day import (
    is_distribution_day,
    count_distribution_days,
)


def test_is_distribution_day_basic():
    """close -0.5% AND volume > 전일 → True."""
    # close 100 → 99.5 (-0.5%), volume 100 → 110 (up)
    assert is_distribution_day(today_close=99.5, today_volume=110, yesterday_close=100.0, yesterday_volume=100) == True


def test_is_distribution_day_marginal_pct():
    """close -0.19% → False (경계 -0.2% 직전)."""
    assert is_distribution_day(today_close=99.81, today_volume=110, yesterday_close=100.0, yesterday_volume=100) == False


def test_is_distribution_day_volume_equal_or_less():
    """vol <= 전일 → False."""
    assert is_distribution_day(today_close=99.0, today_volume=100, yesterday_close=100.0, yesterday_volume=100) == False
    assert is_distribution_day(today_close=99.0, today_volume=90, yesterday_close=100.0, yesterday_volume=100) == False


def test_is_distribution_day_up_day_false():
    """상승일 → False 무조건."""
    assert is_distribution_day(today_close=101.0, today_volume=200, yesterday_close=100.0, yesterday_volume=100) == False


def test_count_distribution_days_25_session():
    """25 세션 중 분포일 3개 → 3 반환."""
    rows = []
    for i in range(30):
        if i in (5, 10, 20):
            # 분포일: -0.5%, vol up
            rows.append({"close": 99.5, "volume": 200})
        else:
            rows.append({"close": 100.0, "volume": 100})
    df = pd.DataFrame(rows)
    # 분포일 판정에는 전일 close 가 필요. df.iloc[i] 에 close, volume 만 있음 → 전일은 i-1
    count = count_distribution_days(df, end_idx=29, lookback=25)
    # end_idx=29 (마지막) 부터 직전 25 세션 (인덱스 5~29 포함) → 분포일 i=5, 10, 20 모두 포함
    # 단 i=5 의 전일은 i=4 (close=100), today i=5 close=99.5, vol=200>100 → distribution
    assert count == 3


def test_count_distribution_days_short_history():
    """lookback 보다 짧은 데이터 → 가능한 만큼만 카운트."""
    rows = [{"close": 100.0, "volume": 100}, {"close": 99.5, "volume": 200}]
    df = pd.DataFrame(rows)
    count = count_distribution_days(df, end_idx=1, lookback=25)
    assert count == 1   # i=1 이 분포일
