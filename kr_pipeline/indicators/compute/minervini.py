# kr_pipeline/indicators/compute/minervini.py
"""미너비니 Trend Template 조건 c1-c7 계산 (c8 = rs_rating >= 70, pass = ALL 은 SQL 에서).

모든 입력은 수정종가 기준 컬럼이어야 함.
"""
import numpy as np
import pandas as pd


def compute_minervini_c1_to_c7(df: pd.DataFrame, sma_200_lookback: int = 22) -> pd.DataFrame:
    """
    입력 df 컬럼: adj_close, sma_50, sma_150, sma_200, w52_high, w52_low
    출력: minervini_c1 ~ minervini_c7 boolean 컬럼 (NaN 가능)

    NaN 입력 시 조건도 NaN (pandas 비교 의미).
    """
    out = pd.DataFrame(index=df.index)

    close = df["adj_close"]
    sma50 = df["sma_50"]
    sma150 = df["sma_150"]
    sma200 = df["sma_200"]
    w52h = df["w52_high"]
    w52l = df["w52_low"]

    # C1: close > sma_150 > sma_200
    out["minervini_c1"] = (close > sma150) & (sma150 > sma200)
    # C2: sma_150 > sma_200
    out["minervini_c2"] = sma150 > sma200
    # C3: sma_200(today) > sma_200(today - 22)
    sma200_lagged = sma200.shift(sma_200_lookback)
    out["minervini_c3"] = sma200 > sma200_lagged
    # C4: sma_50 > sma_150 > sma_200
    out["minervini_c4"] = (sma50 > sma150) & (sma150 > sma200)
    # C5: close > sma_50
    out["minervini_c5"] = close > sma50
    # C6: close >= w52_low * 1.25
    out["minervini_c6"] = close >= w52l * 1.25
    # C7: close >= w52_high * 0.75
    out["minervini_c7"] = close >= w52h * 0.75

    # NaN 보존: 입력 중 하나라도 NaN 이면 조건도 NaN (pandas 비교 결과는 False 이지만, 우리는 NaN 으로)
    for c, cols in [
        ("minervini_c1", [close, sma150, sma200]),
        ("minervini_c2", [sma150, sma200]),
        ("minervini_c3", [sma200, sma200_lagged]),
        ("minervini_c4", [sma50, sma150, sma200]),
        ("minervini_c5", [close, sma50]),
        ("minervini_c6", [close, w52l]),
        ("minervini_c7", [close, w52h]),
    ]:
        # 어느 입력이라도 NaN 인 행은 조건도 NaN (object dtype 으로 변환)
        nan_mask = pd.concat([col.isna() for col in cols], axis=1).any(axis=1)
        out[c] = out[c].astype(object)
        out.loc[nan_mask, c] = np.nan

    return out
