# kr_pipeline/indicators/compute/rs_rating.py
"""RS Rating: universe 단위 1년 수익률 백분위 (0~99)."""
import numpy as np
import pandas as pd


def compute_1y_return(adj_close: pd.Series, window: int = 252) -> pd.Series:
    """1년 수익률 = adj_close[t] / adj_close[t-window] - 1.

    window 미만은 NaN.
    """
    return adj_close.pct_change(periods=window)


def assign_rs_rating_percentiles(returns: pd.Series) -> pd.Series:
    """universe 의 1년 수익률 → 백분위 (0~99) 매핑.

    NaN 입력 종목은 NaN 출력 (universe 에서 제외).
    동률은 평균 rank.
    공식: ((N - rank) / N) * 99 → 최고가 99, 최저가 0
    """
    valid_mask = returns.notna()
    valid = returns[valid_mask]
    n = len(valid)
    if n == 0:
        return pd.Series([np.nan] * len(returns), index=returns.index)

    # rank descending (1등이 가장 높은 수익률)
    ranks = valid.rank(ascending=False, method="average")
    # 백분위
    percentiles = ((n - ranks) / n) * 99
    # 0~99 정수로
    rs_rating = percentiles.round().astype(int)

    # 원 index 로 복원, NaN 종목은 NaN
    result = pd.Series([np.nan] * len(returns), index=returns.index)
    result.loc[valid_mask] = rs_rating
    return result
