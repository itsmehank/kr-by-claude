"""52주 high/low 및 현재가 위치 백분율 순수 함수."""
import pandas as pd


def w52_high_low(
    adj_high: pd.Series,
    adj_low: pd.Series,
    window: int = 252,
) -> tuple[pd.Series, pd.Series]:
    """52주(기본 252영업일) 수정 고가 rolling max / 수정 저가 rolling min."""
    high = adj_high.rolling(window=window, min_periods=window).max()
    low = adj_low.rolling(window=window, min_periods=window).min()
    return high, low


def pct_from_high_low(
    adj_close: pd.Series,
    high: pd.Series,
    low: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """현재가의 52주 high / low 대비 위치 (백분율)."""
    pct_h = (adj_close - high) / high * 100
    pct_l = (adj_close - low) / low * 100
    return pct_h, pct_l


