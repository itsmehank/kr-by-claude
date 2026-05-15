import pandas as pd
import pytest
from kr_pipeline.indicators.compute.high_low import w52_high_low, pct_from_high_low


def test_high_low_basic():
    s = pd.Series([10.0, 20.0, 30.0, 25.0, 15.0])
    h, l = w52_high_low(s, window=3)
    assert pd.isna(h.iloc[0])
    assert pd.isna(l.iloc[0])
    assert h.iloc[2] == 30.0 and l.iloc[2] == 10.0
    assert h.iloc[3] == 30.0 and l.iloc[3] == 20.0
    assert h.iloc[4] == 30.0 and l.iloc[4] == 15.0


def test_high_low_window_size_252_default():
    s = pd.Series(range(300), dtype=float)
    h, l = w52_high_low(s)
    assert h.isna().iloc[:251].all()
    assert h.iloc[251] == 251.0
    assert l.iloc[251] == 0.0


def test_high_low_insufficient_history():
    s = pd.Series([10.0, 20.0])
    h, l = w52_high_low(s, window=5)
    assert h.isna().all()
    assert l.isna().all()


def test_pct_from_high_low_basic():
    close = pd.Series([100.0, 110.0, 120.0])
    high = pd.Series([130.0, 130.0, 130.0])
    low = pd.Series([80.0, 80.0, 80.0])
    pct_h, pct_l = pct_from_high_low(close, high, low)
    assert abs(pct_h.iloc[0] - (-23.076923)) < 0.001
    assert pct_l.iloc[0] == 25.0


def test_pct_from_high_low_handles_nan():
    import numpy as np
    close = pd.Series([100.0, 110.0])
    high = pd.Series([np.nan, 130.0])
    low = pd.Series([80.0, np.nan])
    pct_h, pct_l = pct_from_high_low(close, high, low)
    assert pd.isna(pct_h.iloc[0])
    assert pd.isna(pct_l.iloc[1])


def test_high_low_preserves_index():
    idx = pd.date_range("2026-01-01", periods=5)
    s = pd.Series([10.0, 20.0, 30.0, 25.0, 15.0], index=idx)
    h, l = w52_high_low(s, window=3)
    assert list(h.index) == list(idx)
    assert list(l.index) == list(idx)
