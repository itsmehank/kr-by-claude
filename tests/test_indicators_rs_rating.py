# tests/test_indicators_rs_rating.py
import pandas as pd
import numpy as np
import pytest
from kr_pipeline.indicators.compute.rs_rating import (
    compute_1y_return,
    assign_rs_rating_percentiles,
    compute_ibd_strength_factor,
)


def test_1y_return_basic():
    """1년 수익률 = (close[t] / close[t-window]) - 1"""
    s = pd.Series([100.0, 110.0, 120.0, 130.0, 140.0])
    result = compute_1y_return(s, window=3)
    # index 3: close[3]/close[0] - 1 = 130/100 - 1 = 0.3
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[2])
    assert abs(result.iloc[3] - 0.3) < 0.001
    assert abs(result.iloc[4] - (140 / 110 - 1)) < 0.001  # 140/110-1 (window=3, so s[4]/s[1]-1)


def test_1y_return_insufficient_history():
    """history 부족 시 NaN"""
    s = pd.Series([100.0, 110.0])
    result = compute_1y_return(s, window=252)
    assert result.isna().all()


def test_assign_percentiles_basic():
    """3개 종목 1년 수익률: 30%, 10%, 50% → 백분위"""
    # ticker -> 1y_return
    returns = pd.Series([0.3, 0.1, 0.5], index=["A", "B", "C"])
    result = assign_rs_rating_percentiles(returns)
    # C (50%) 1등, A (30%) 2등, B (10%) 3등
    # N=3. rank 1 → ((3-1)/3)*99 = 66, rank 2 → ((3-2)/3)*99 = 33, rank 3 → 0
    # 또는 percentile rank: C=99, A=49, B=0 (정의에 따라 다름)
    # 우리 정의: ((N - rank) / N) * 99, rank 1-based
    assert result["C"] == 66  # ((3-1)/3)*99 = 66.0 → 66
    assert result["A"] == 33  # ((3-2)/3)*99 = 33.0 → 33
    assert result["B"] == 0   # ((3-3)/3)*99 = 0


def test_assign_percentiles_excludes_nan():
    """NaN 수익률 종목은 universe 에서 빠지고 결과도 NaN"""
    returns = pd.Series([0.3, np.nan, 0.5, 0.1], index=["A", "B", "C", "D"])
    result = assign_rs_rating_percentiles(returns)
    # B 는 NaN 입력 → NaN 출력
    assert pd.isna(result["B"])
    # 나머지 3개로 백분위: C=66, A=33, D=0
    assert result["C"] == 66
    assert result["A"] == 33
    assert result["D"] == 0


def test_assign_percentiles_handles_ties():
    """같은 수익률 → 같은 백분위 (평균 rank 사용)"""
    returns = pd.Series([0.3, 0.3, 0.1], index=["A", "B", "C"])
    result = assign_rs_rating_percentiles(returns)
    # A, B 동률 1.5등 → ((3-1.5)/3)*99 = 49.5 → 49 또는 50 (rounding 정책)
    # C 3등 → 0
    assert result["A"] == result["B"]
    assert result["C"] == 0
    assert result["A"] >= 49 and result["A"] <= 50


def test_ibd_sf_weights_recent_quarter_double():
    # 가격이 일정하면 모든 비율=1 → SF = 2+1+1+1 = 5
    c = pd.Series([100.0] * 260)
    sf = compute_ibd_strength_factor(c, 63, 126, 189, 252)
    assert sf.iloc[-1] == 5.0


def test_ibd_sf_nan_before_longest_lookback():
    c = pd.Series([100.0] * 260)
    sf = compute_ibd_strength_factor(c, 63, 126, 189, 252)
    assert pd.isna(sf.iloc[251])   # 252 미만 → NaN
    assert not pd.isna(sf.iloc[252])


def test_ibd_sf_nan_when_intermediate_gap():
    # 중간 lookback(126) 지점이 NaN 이면 SF NaN (보간 안 함)
    c = pd.Series([100.0] * 260)
    c.iloc[260 - 1 - 126] = np.nan
    sf = compute_ibd_strength_factor(c, 63, 126, 189, 252)
    assert pd.isna(sf.iloc[-1])


def test_ibd_sf_higher_recent_growth_ranks_higher():
    # 최근 분기 급등 종목이 SF 더 큼
    flat = pd.Series([100.0] * 260)
    recent_pop = flat.copy()
    recent_pop.iloc[-1] = 130.0      # 오늘만 +30%
    sf_flat = compute_ibd_strength_factor(flat, 63, 126, 189, 252).iloc[-1]
    sf_pop = compute_ibd_strength_factor(recent_pop, 63, 126, 189, 252).iloc[-1]
    assert sf_pop > sf_flat
