"""52주 high/low 및 현재가 위치 백분율 순수 함수."""
import pandas as pd


def w52_high_low(
    adj_high: pd.Series,
    adj_low: pd.Series,
    window: int = 252,
    min_periods: int | None = None,
) -> tuple[pd.Series, pd.Series]:
    """52주(기본 252영업일) 수정 고가 rolling max / 수정 저가 rolling min.

    min_periods 미지정 시 window(엄격). 거래정지일은 adj_high/adj_low 가 NULL(NaN)이며
    pandas rolling 은 NaN 을 *제외* 하고 min/max 계산(min_periods 는 유효개수 판정)하므로,
    min_periods<window 면 고정 252행 윈도우를 유지하면서 halt 거래일만 건너뛴 실값을 얻는다.
    일봉은 min_periods=240(≤12 halt 허용 → 고립 halt 통과, 장기정지는 유효일<240 → NaN →
    제외). 신규상장(거래일<240)도 NaN(히스토리 부족 보존). dropna 금지(달력 윈도우 왜곡)."""
    mp = window if min_periods is None else min_periods
    high = adj_high.rolling(window=window, min_periods=mp).max()
    low = adj_low.rolling(window=window, min_periods=mp).min()
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


