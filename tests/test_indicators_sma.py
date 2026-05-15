import pandas as pd
import pytest
from kr_pipeline.indicators.compute.sma import sma


def test_sma_basic_5_day():
    """5일 SMA: 마지막 5개 평균."""
    s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0])
    result = sma(s, window=5)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[3])
    assert result.iloc[4] == 30.0
    assert result.iloc[5] == 40.0
    assert result.iloc[6] == 50.0


def test_sma_insufficient_history_returns_nan():
    s = pd.Series([10.0, 20.0])
    result = sma(s, window=5)
    assert result.isna().all()


def test_sma_handles_nan_in_input():
    import numpy as np
    s = pd.Series([10.0, 20.0, np.nan, 40.0, 50.0, 60.0])
    result = sma(s, window=3)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])
    assert pd.isna(result.iloc[3])
    assert pd.isna(result.iloc[4])
    assert result.iloc[5] == 50.0


def test_sma_preserves_index():
    s = pd.Series([10.0, 20.0, 30.0], index=pd.date_range("2026-01-01", periods=3))
    result = sma(s, window=2)
    assert list(result.index) == list(s.index)
