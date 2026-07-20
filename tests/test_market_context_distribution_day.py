# tests/test_market_context_distribution_day.py
import pandas as pd
import pytest

from kr_pipeline.market_context.compute.distribution_day import (
    is_distribution_day,
    is_stalling_day,
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


# ===== stalling/churning (이슈 #55 — HMMS p.209-210) =====


def test_is_stalling_day_basic():
    """소폭 상승(+0.1% ≤ |임계|) + vol up + 하단 절반 마감 → True."""
    assert is_stalling_day(
        today_close=100.1, today_volume=200, today_high=101.0, today_low=100.0,
        yesterday_close=100.0, yesterday_volume=100,
    ) == True


def test_is_stalling_day_upper_half_close_excluded():
    """상단 절반 마감(close_pos 0.75) → False (원전 예외)."""
    assert is_stalling_day(
        today_close=100.15, today_volume=200, today_high=100.2, today_low=100.0,
        yesterday_close=100.0, yesterday_volume=100,
    ) == False


def test_is_stalling_day_midpoint_boundary_counts():
    """정확히 중앙 마감(close_pos = 0.5) → 하단 절반 포함(≤) → True."""
    assert is_stalling_day(
        today_close=100.1, today_volume=200, today_high=100.2, today_low=100.0,
        yesterday_close=100.0, yesterday_volume=100,
    ) == True


def test_is_stalling_day_volume_not_up():
    """vol ≤ 전일 → False."""
    assert is_stalling_day(
        today_close=100.1, today_volume=100, today_high=101.0, today_low=100.0,
        yesterday_close=100.0, yesterday_volume=100,
    ) == False


def test_is_stalling_day_gain_above_band():
    """상승폭 +0.5% > |임계 -0.2| → 정체 아님 → False."""
    assert is_stalling_day(
        today_close=100.5, today_volume=200, today_high=101.5, today_low=100.4,
        yesterday_close=100.0, yesterday_volume=100,
    ) == False


def test_is_stalling_day_negative_change_not_stall():
    """하락일(-0.1%)은 stalling 아님 (classic 경로 소관) → False."""
    assert is_stalling_day(
        today_close=99.9, today_volume=200, today_high=100.5, today_low=99.8,
        yesterday_close=100.0, yesterday_volume=100,
    ) == False


def test_is_stalling_day_zero_range_false():
    """high == low (range 0) → 위치 판정 불가 → False."""
    assert is_stalling_day(
        today_close=100.0, today_volume=200, today_high=100.0, today_low=100.0,
        yesterday_close=100.0, yesterday_volume=100,
    ) == False


def test_is_stalling_day_sigma_scaled_band():
    """σ-보정 임계 미러: pct_threshold=-0.5 → +0.4% 도 정체 밴드 내 → True."""
    assert is_stalling_day(
        today_close=100.4, today_volume=200, today_high=101.4, today_low=100.3,
        yesterday_close=100.0, yesterday_volume=100,
        pct_threshold=-0.5,
    ) == True


def _mk_df(rows):
    for r in rows:
        r.setdefault("high", r["close"] + 0.5)
        r.setdefault("low", r["close"] - 0.5)
    return pd.DataFrame(rows)


def test_count_includes_stalling_days():
    """classic 1 + stalling 1 → 2. include_stalling=False → classic 1 만."""
    rows = [{"close": 100.0, "volume": 100} for _ in range(10)]
    # i=5: classic 분배일 (-0.5%, vol up)
    rows[5] = {"close": 99.5, "volume": 200}
    # i=6 전일(99.5) 대비 +0.1% (밴드 내), vol up, 하단 절반 마감
    rows[6] = {"close": 99.6, "volume": 300, "high": 100.6, "low": 99.5}
    # i=7: 99.6 → 100.0 (+0.4% — 밴드 밖 상승), vol down → 무관
    rows[7] = {"close": 100.0, "volume": 100}
    df = _mk_df(rows)
    assert count_distribution_days(df, end_idx=9, lookback=25) == 2
    assert count_distribution_days(df, end_idx=9, lookback=25, include_stalling=False) == 1


def test_count_stalling_upper_half_not_counted():
    """stalling 후보라도 상단 절반 마감이면 미계수."""
    rows = [{"close": 100.0, "volume": 100} for _ in range(10)]
    rows[6] = {"close": 100.1, "volume": 300, "high": 100.2, "low": 99.9}  # pos≈0.67
    df = _mk_df(rows)
    assert count_distribution_days(df, end_idx=9, lookback=25) == 0


def test_count_distribution_days_25_session():
    """25 세션 중 분포일 3개 → 3 반환."""
    rows = []
    for i in range(30):
        if i in (5, 10, 20):
            # 분포일: -0.5%, vol up
            rows.append({"close": 99.5, "volume": 200})
        else:
            rows.append({"close": 100.0, "volume": 100})
    df = _mk_df(rows)
    # 분포일 판정에는 전일 close 가 필요. df.iloc[i] 에 close, volume 만 있음 → 전일은 i-1
    count = count_distribution_days(df, end_idx=29, lookback=25)
    # end_idx=29 (마지막) 부터 직전 25 세션 (인덱스 5~29 포함) → 분포일 i=5, 10, 20 모두 포함
    # 단 i=5 의 전일은 i=4 (close=100), today i=5 close=99.5, vol=200>100 → distribution
    assert count == 3


def test_count_distribution_days_short_history():
    """lookback 보다 짧은 데이터 → 가능한 만큼만 카운트."""
    rows = [{"close": 100.0, "volume": 100}, {"close": 99.5, "volume": 200}]
    df = _mk_df(rows)
    count = count_distribution_days(df, end_idx=1, lookback=25)
    assert count == 1   # i=1 이 분포일
