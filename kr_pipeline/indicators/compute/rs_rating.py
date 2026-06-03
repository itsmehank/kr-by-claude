# kr_pipeline/indicators/compute/rs_rating.py
"""RS Rating: universe 단위 1년 수익률 백분위 (0~99)."""
import numpy as np
import pandas as pd


def compute_1y_return(adj_close: pd.Series, window: int = 252) -> pd.Series:
    """1년 수익률 = adj_close[t] / adj_close[t-window] - 1.

    window 미만은 NaN.
    """
    return adj_close.pct_change(periods=window)


def compute_ibd_strength_factor(
    adj_close: pd.Series,
    q1: int = 63, q2: int = 126, q3: int = 189, q4: int = 252,
) -> pd.Series:
    """IBD 가중 강도(StrengthFactor) = 가격비율 합산형, 최근 분기 2배 가중.

    SF = 2·(C/C[-q1]) + (C/C[-q2]) + (C/C[-q3]) + (C/C[-q4])
    일봉: q=63/126/189/252, 주봉: q=13/26/39/52.
    네 시점 중 하나라도 결측이면 NaN (보간 안 함 — 설계 §9.2).
    """
    c = adj_close
    sf = (
        2 * (c / c.shift(q1))
        + (c / c.shift(q2))
        + (c / c.shift(q3))
        + (c / c.shift(q4))
    )
    return sf


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
