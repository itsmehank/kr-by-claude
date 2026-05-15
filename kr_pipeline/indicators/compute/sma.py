"""단순 이동 평균 (Simple Moving Average) 순수 함수."""
import pandas as pd


def sma(adj_close: pd.Series, window: int) -> pd.Series:
    """SMA(window). 수정종가 입력 필수.

    데이터가 window 일치 미만이면 NaN.
    window 안에 NaN 이 있으면 결과도 NaN (pandas 기본).
    """
    return adj_close.rolling(window=window, min_periods=window).mean()
