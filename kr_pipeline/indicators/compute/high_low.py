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
    w52_high: pd.Series,
    w52_low: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """현재 수정종가의 52주 수정 고가 / 저가 대비 위치 (백분율).

    인자 w52_high·w52_low 는 w52_high_low() 가 만든 52주 수정 고가/저가.
    분모가 0 이면 (정지·무거래 종목의 0 가격) NaN — 0-나눗셈 inf 방지.
    """
    pct_h = (adj_close - w52_high) / w52_high.where(w52_high != 0) * 100
    pct_l = (adj_close - w52_low) / w52_low.where(w52_low != 0) * 100
    return pct_h, pct_l


