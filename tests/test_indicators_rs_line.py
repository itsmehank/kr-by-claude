# tests/test_indicators_rs_line.py
from datetime import date
import pandas as pd
import numpy as np
import pytest
from kr_pipeline.indicators.compute.rs_line import (
    compute_rs_line,
    compute_rs_line_52w_high_and_date,
    compute_rs_line_at_52w_high,
    compute_rs_line_uptrend,
    compute_rs_line_in_decline_7m,
)


def test_rs_line_basic_ratio():
    """rs_line = adj_close_stock / close_index"""
    stock = pd.Series([1000.0, 1100.0, 1200.0])
    index_close = pd.Series([2500.0, 2500.0, 2400.0])
    result = compute_rs_line(stock, index_close)
    assert result.iloc[0] == 0.4         # 1000/2500
    assert result.iloc[1] == 0.44        # 1100/2500
    assert result.iloc[2] == 0.5         # 1200/2400


def test_rs_line_nan_when_either_missing():
    """둘 중 하나 NaN 이면 결과 NaN"""
    stock = pd.Series([1000.0, np.nan, 1200.0])
    index_close = pd.Series([2500.0, 2500.0, np.nan])
    result = compute_rs_line(stock, index_close)
    assert result.iloc[0] == 0.4
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])


def test_rs_line_52w_high_and_date_tracked():
    """52주(252영업일) rolling 신고가 및 해당 날짜 기록."""
    idx = pd.date_range("2026-01-01", periods=10, freq="D").date
    rs = pd.Series([0.3, 0.5, 0.4, 0.6, 0.55, 0.7, 0.65, 0.6, 0.55, 0.5], index=idx)
    high, high_date = compute_rs_line_52w_high_and_date(rs, window=3)
    # window=3 (테스트용으로 짧게): 처음 2개는 NaN
    assert pd.isna(high.iloc[0])
    assert pd.isna(high_date.iloc[0])
    # index 2: max(0.3, 0.5, 0.4) = 0.5 → idx[1]
    assert high.iloc[2] == 0.5
    assert high_date.iloc[2] == idx[1]
    # index 5: max(0.6, 0.55, 0.7) = 0.7 → idx[5]
    assert high.iloc[5] == 0.7
    assert high_date.iloc[5] == idx[5]


def test_rs_line_at_52w_high_today():
    """오늘 RS Line == 52주 max → True"""
    rs = pd.Series([0.5, 0.6, 0.7])
    high = pd.Series([0.7, 0.7, 0.7])
    result = compute_rs_line_at_52w_high(rs, high)
    assert result.iloc[2] == True   # rs[2]==high[2]
    assert result.iloc[0] == False  # rs[0]<high[0]


def test_rs_line_uptrend_when_above_rolling_mean():
    """rs_line > rolling_mean → True (spec 정의)"""
    # rs increasing → rs > rolling_mean
    rs = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    result = compute_rs_line_uptrend(rs, window=3)
    # rolling mean at index 2 = (0.1+0.2+0.3)/3 = 0.2; rs=0.3 > 0.2 → True
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == True
    assert result.iloc[6] == True


def test_rs_line_uptrend_false_when_below():
    """rs_line < rolling_mean → False"""
    rs = pd.Series([0.7, 0.6, 0.5, 0.4, 0.3])
    result = compute_rs_line_uptrend(rs, window=3)
    # mean(0.7, 0.6, 0.5) = 0.6, rs[2]=0.5 < 0.6 → False
    assert result.iloc[2] == False


def test_rs_line_in_decline_7m_when_high_was_long_ago():
    """rs_line_52w_high_date 가 140 영업일 이상 전 → True"""
    idx = pd.date_range("2026-01-01", periods=300, freq="D").date
    # high_date: 모두 idx[10] (오래 전)
    high_date = pd.Series([idx[10]] * 300, index=idx)
    # current_date 는 인덱스가 곧 날짜
    current_dates = pd.Series(idx, index=idx)
    result = compute_rs_line_in_decline_7m(high_date, current_dates, threshold_days=140)
    # idx[10] = 2026-01-11, idx[10+140] = ~ 2026-05-31
    # 0~149번 index: 차이 < 140
    # 150번 index 이후: 차이 >= 140
    assert result.iloc[10] == False    # 같은 날
    assert result.iloc[100] == False   # 90일 차이
    assert result.iloc[150] == True    # 140일 차이
    assert result.iloc[200] == True


def test_rs_line_in_decline_handles_nan_high_date():
    """high_date 가 NaN 이면 결과 NaN"""
    idx = pd.date_range("2026-01-01", periods=3).date
    high_date = pd.Series([pd.NaT, idx[0], idx[0]], index=idx)
    current_dates = pd.Series(idx, index=idx)
    result = compute_rs_line_in_decline_7m(high_date, current_dates, threshold_days=140)
    assert pd.isna(result.iloc[0])


def test_rs_line_insufficient_history_returns_null():
    """충분한 lookback 없으면 NaN"""
    rs = pd.Series([0.5, 0.6])
    high, _ = compute_rs_line_52w_high_and_date(rs, window=5)
    assert high.isna().all()


def test_rs_line_preserves_index():
    """index 유지"""
    idx = pd.date_range("2026-01-01", periods=3)
    stock = pd.Series([1000.0, 1100.0, 1200.0], index=idx)
    index_close = pd.Series([2500.0, 2500.0, 2400.0], index=idx)
    result = compute_rs_line(stock, index_close)
    assert list(result.index) == list(idx)
