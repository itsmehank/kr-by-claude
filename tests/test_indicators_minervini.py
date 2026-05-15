# tests/test_indicators_minervini.py
import pandas as pd
import numpy as np
import pytest
from kr_pipeline.indicators.compute.minervini import (
    compute_minervini_c1_to_c7,
)


def _input_df(close, sma50, sma150, sma200, w52h, w52l):
    """테스트 입력 DataFrame 생성."""
    return pd.DataFrame({
        "adj_close": close,
        "sma_50": sma50,
        "sma_150": sma150,
        "sma_200": sma200,
        "w52_high": w52h,
        "w52_low": w52l,
    })


def test_c1_close_above_sma150_above_sma200():
    """C1: adj_close > sma_150 > sma_200"""
    df = _input_df(
        close=[100.0], sma50=[90.0], sma150=[95.0], sma200=[90.0],
        w52h=[120.0], w52l=[60.0],
    )
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 100 > 95 > 90 → True
    assert result["minervini_c1"].iloc[0] == True


def test_c1_fails_when_close_below_sma150():
    """close < sma_150 → C1 = False"""
    df = _input_df(close=[80.0], sma50=[90.0], sma150=[95.0], sma200=[90.0], w52h=[120.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    assert result["minervini_c1"].iloc[0] == False


def test_c2_sma150_above_sma200():
    df = _input_df(close=[100.0], sma50=[90.0], sma150=[95.0], sma200=[90.0], w52h=[120.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    assert result["minervini_c2"].iloc[0] == True


def test_c3_sma200_rising_over_22_days():
    """C3: sma_200(today) > sma_200(today - 22 days)

    24 영업일 시계열로 검증 (window=22).
    """
    n = 30
    sma200_series = pd.Series([100.0 + i for i in range(n)])  # 우상향
    df = pd.DataFrame({
        "adj_close": [120.0] * n,
        "sma_50": [110.0] * n,
        "sma_150": [105.0] * n,
        "sma_200": sma200_series,
        "w52_high": [150.0] * n,
        "w52_low": [80.0] * n,
    })
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # index 22 부터: sma_200[22]=122, sma_200[0]=100 → 122 > 100 → True
    assert pd.isna(result["minervini_c3"].iloc[21])  # lookback 부족
    assert result["minervini_c3"].iloc[22] == True
    assert result["minervini_c3"].iloc[29] == True


def test_c3_sma200_declining():
    n = 30
    sma200_series = pd.Series([100.0 - i for i in range(n)])  # 우하향
    df = pd.DataFrame({
        "adj_close": [120.0] * n,
        "sma_50": [110.0] * n,
        "sma_150": [105.0] * n,
        "sma_200": sma200_series,
        "w52_high": [150.0] * n,
        "w52_low": [80.0] * n,
    })
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # sma_200[22]=78, sma_200[0]=100 → 78 < 100 → False
    assert result["minervini_c3"].iloc[22] == False


def test_c4_sma50_above_sma150_above_sma200():
    df = _input_df(close=[120.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    assert result["minervini_c4"].iloc[0] == True


def test_c5_close_above_sma50():
    df = _input_df(close=[120.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    assert result["minervini_c5"].iloc[0] == True


def test_c6_close_25pct_above_52w_low():
    """close >= w52_low * 1.25"""
    df = _input_df(close=[125.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[100.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 125 >= 100 * 1.25 (=125) → True
    assert result["minervini_c6"].iloc[0] == True


def test_c6_fails_when_too_close_to_52w_low():
    df = _input_df(close=[120.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[100.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 120 < 125 → False
    assert result["minervini_c6"].iloc[0] == False


def test_c7_close_within_25pct_of_52w_high():
    """close >= w52_high * 0.75"""
    df = _input_df(close=[120.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 120 >= 150 * 0.75 (=112.5) → True
    assert result["minervini_c7"].iloc[0] == True


def test_c7_fails_when_too_far_from_52w_high():
    df = _input_df(close=[100.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 100 < 112.5 → False
    assert result["minervini_c7"].iloc[0] == False


def test_null_input_produces_null_condition():
    """SMA 가 NaN 이면 관련 조건도 NaN (NULL)"""
    df = _input_df(
        close=[100.0], sma50=[np.nan], sma150=[95.0], sma200=[90.0],
        w52h=[120.0], w52l=[60.0],
    )
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # c5 = close > sma_50; sma_50=NaN → c5 = NaN
    assert pd.isna(result["minervini_c5"].iloc[0])
