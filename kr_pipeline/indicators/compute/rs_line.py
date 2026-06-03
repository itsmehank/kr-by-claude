# kr_pipeline/indicators/compute/rs_line.py
"""RS Line: 종목 수정종가 / 벤치마크 종가. 그리고 책 신호 booleans."""
from datetime import date as _date
import pandas as pd
import numpy as np


def compute_rs_line(adj_close_stock: pd.Series, close_index: pd.Series) -> pd.Series:
    """RS Line = adj_close_stock / close_index.

    종목은 수정종가, 지수는 close (지수는 수정 개념 없음 — 의도된 비대칭).
    """
    return adj_close_stock / close_index


def compute_rs_line_52w_high_and_date(
    rs_line: pd.Series,
    window: int = 252,
) -> tuple[pd.Series, pd.Series]:
    """RS Line 의 rolling max 와 그 max 가 된 날짜.

    index 는 날짜여야 함 (DatetimeIndex 또는 date 객체 리스트).
    """
    high = rs_line.rolling(window=window, min_periods=window).max()

    # argmax 위치 → 해당 날짜 (rolling apply 로 idx 추적)
    high_date = rs_line.rolling(window=window, min_periods=window).apply(
        lambda x: x.values.argmax(),
        raw=False,
    )
    # high_date 는 offset (0..window-1). 실제 날짜로 변환.
    n = len(rs_line)
    high_date_series = pd.Series([None] * n, index=rs_line.index, dtype=object)
    for i in range(window - 1, n):
        if pd.isna(high_date.iloc[i]):
            continue
        offset = int(high_date.iloc[i])
        window_start = i - window + 1
        high_date_series.iloc[i] = rs_line.index[window_start + offset]

    return high, high_date_series


def compute_rs_line_at_52w_high(rs_line: pd.Series, rs_line_52w_high: pd.Series) -> pd.Series:
    """오늘 RS Line 이 52주 신고가 (rolling max) 와 같은가."""
    return rs_line == rs_line_52w_high


def compute_rs_line_uptrend(rs_line: pd.Series, window: int) -> pd.Series:
    """[DEPRECATED 2026-06-03: 기울기/pure-declining 으로 교체. modes.py 호출부는 Task 8에서 제거.] rs_line > rolling_mean(window) → 우상향 판정.

    window 미만은 NaN.
    """
    rolling_mean = rs_line.rolling(window=window, min_periods=window).mean()
    result = rs_line > rolling_mean
    # window 미만 구간은 NaN (비교 결과 False 가 아닌 NaN)
    result = result.where(rolling_mean.notna())
    return result


def compute_rs_line_in_decline_7m(
    rs_line_52w_high_date: pd.Series,
    current_dates: pd.Series,
    threshold_days: int = 140,
) -> pd.Series:
    """[DEPRECATED 2026-06-03: 기울기/pure-declining 으로 교체. modes.py 호출부는 Task 8에서 제거.] rs_line_52w_high_date 가 current_date 로부터 threshold_days 이상 전 → True.

    7개월 ≈ 140 영업일.
    high_date 가 NaN 이면 결과 NaN.
    """
    result = pd.Series([None] * len(current_dates), index=current_dates.index, dtype=object)
    for i in range(len(current_dates)):
        hd = rs_line_52w_high_date.iloc[i]
        cd = current_dates.iloc[i]
        if pd.isna(hd) or pd.isna(cd):
            continue
        # date 객체로 변환
        if isinstance(hd, pd.Timestamp):
            hd = hd.date()
        if isinstance(cd, pd.Timestamp):
            cd = cd.date()
        diff_days = (cd - hd).days
        result.iloc[i] = diff_days >= threshold_days
    return result


def _rolling_slope(rs_line: pd.Series, window: int) -> pd.Series:
    """각 window 구간 선형회귀 기울기. window 미만/결측 포함 시 NaN."""
    x = np.arange(window, dtype=float)

    def _slope(y):
        if np.isnan(y).any():
            return np.nan
        return np.polyfit(x, y, 1)[0]

    return rs_line.rolling(window=window, min_periods=window).apply(_slope, raw=True)


def compute_rs_line_uptrend_slope(rs_line: pd.Series, window: int) -> pd.Series:
    """최근 window 구간 회귀 기울기 > 0 → True (D7). window 미만 NaN.

    '이동평균 위' 정의를 대체 — 평평/스파이크에 False 가 되어 실제 상향만 잡음.
    """
    slope = _rolling_slope(rs_line, window)
    result = slope > 1e-10   # epsilon: polyfit 평평 배열에 ~1e-17 잡음 → 0 초과 방지(평평=상향아님)
    return result.where(slope.notna())


def compute_rs_line_not_declining(rs_line: pd.Series, window: int) -> pd.Series:
    """NOT(기울기<0 AND 끝점<시작점) → True=건강 (D6, pure-declining). window 미만 NaN.

    횡보(기울기≈0)는 건강으로 보존, 실제 하락선만 False.
    끝점 비교는 같은 window 의 첫 점(rs_line.shift(window-1)) 기준.
    """
    slope = _rolling_slope(rs_line, window)
    endpoint_lower = rs_line < rs_line.shift(window - 1)
    declining = (slope < 0) & endpoint_lower
    result = ~declining
    return result.where(slope.notna())
