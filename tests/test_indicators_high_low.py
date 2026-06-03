import pandas as pd
import pytest
from kr_pipeline.indicators.compute.high_low import w52_high_low, pct_from_high_low


def test_w52_high_is_max_of_adj_high_low_is_min_of_adj_low():
    high_s = pd.Series([10.0, 20.0, 30.0, 25.0, 15.0])
    low_s  = pd.Series([8.0, 18.0, 28.0, 23.0, 13.0])
    h, l = w52_high_low(high_s, low_s, window=3)
    assert pd.isna(h.iloc[0]) and pd.isna(l.iloc[0])
    assert h.iloc[2] == 30.0   # max(10,20,30)
    assert l.iloc[2] == 8.0    # min(8,18,28)
    assert h.iloc[4] == 30.0   # max(30,25,15)
    assert l.iloc[4] == 13.0   # min(28,23,13)


def test_w52_high_low_window_252_default():
    high_s = pd.Series(range(300), dtype=float)
    low_s = pd.Series(range(300), dtype=float)
    h, l = w52_high_low(high_s, low_s)
    assert h.isna().iloc[:251].all()
    assert h.iloc[251] == 251.0
    assert l.iloc[251] == 0.0


def test_w52_high_low_insufficient_history():
    s = pd.Series([10.0, 20.0])
    h, l = w52_high_low(s, s, window=5)
    assert h.isna().all() and l.isna().all()


def test_w52_high_low_preserves_index():
    idx = pd.date_range("2026-01-01", periods=5)
    high_s = pd.Series([10.0, 20.0, 30.0, 25.0, 15.0], index=idx)
    low_s = pd.Series([8.0, 18.0, 28.0, 23.0, 13.0], index=idx)
    h, l = w52_high_low(high_s, low_s, window=3)
    assert list(h.index) == list(idx) and list(l.index) == list(idx)


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
