"""52주 high/low 및 현재가 위치 백분율 순수 함수."""
import pandas as pd


def w52_high_low(adj_close: pd.Series, window: int = 252) -> tuple[pd.Series, pd.Series]:
    """52주(기본 252영업일) rolling max/min."""
    high = adj_close.rolling(window=window, min_periods=window).max()
    low = adj_close.rolling(window=window, min_periods=window).min()
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


def compute_drawdown(
    w52_high: float | None,
    w52_low: float | None,
) -> tuple[float | None, bool | None]:
    """52주 high-low 스프레드 % + 50% 임계 boolean.

    공식: (w52_high - w52_low) / w52_high × 100

    주의: 시간 순서를 무시한 rolling spread 라 진짜 MDD 가 아님. 강한 상승
    종목 (저점 대비 100~300% 상승) 도 큰 값을 가짐. LLM 게이트는 2026-05-21
    제거됨 — 두 번째 반환값은 정보 보존 목적이지 매수 필터 아님.

    Returns:
        (drawdown_pct, drawdown_pct <= 50%) — w52 가 None 이면 둘 다 None
    """
    if w52_high is None or w52_low is None or w52_high <= 0:
        return None, None
    drawdown_pct = (w52_high - w52_low) / w52_high * 100
    return round(drawdown_pct, 2), drawdown_pct <= 50.0
