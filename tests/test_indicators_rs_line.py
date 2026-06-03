# tests/test_indicators_rs_line.py
from datetime import date
import pandas as pd
import numpy as np
import pytest
from kr_pipeline.indicators.compute.rs_line import (
    compute_rs_line,
    compute_rs_line_52w_high_and_date,
    compute_rs_line_at_52w_high,
    compute_rs_line_uptrend_slope,
    compute_rs_line_not_declining,
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


def test_uptrend_slope_true_when_rising():
    rs = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
    result = compute_rs_line_uptrend_slope(rs, window=3)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == True   # 0.1,0.2,0.3 기울기>0
    assert result.iloc[4] == True


def test_uptrend_slope_false_when_falling():
    rs = pd.Series([0.5, 0.4, 0.3, 0.2, 0.1])
    result = compute_rs_line_uptrend_slope(rs, window=3)
    assert result.iloc[2] == False


def test_uptrend_slope_false_when_flat():
    # 평평하면 기울기 0 → > 0 아님 → False (MA위 정의와 달라지는 핵심)
    rs = pd.Series([0.5, 0.5, 0.5, 0.5])
    result = compute_rs_line_uptrend_slope(rs, window=3)
    assert result.iloc[2] == False


def test_not_declining_true_for_sideways():
    # 횡보(평평): 하락 아님 → 건강(True). pure-declining 의 핵심.
    rs = pd.Series([0.5] * 6)
    result = compute_rs_line_not_declining(rs, window=4)
    assert result.iloc[5] == True


def test_not_declining_false_for_real_decline():
    # 기울기<0 AND 끝점<시작점 → declining → False
    rs = pd.Series([0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
    result = compute_rs_line_not_declining(rs, window=4)
    assert result.iloc[5] == False


def test_not_declining_nan_before_window():
    rs = pd.Series([0.5, 0.6])
    result = compute_rs_line_not_declining(rs, window=4)
    assert pd.isna(result.iloc[1])
