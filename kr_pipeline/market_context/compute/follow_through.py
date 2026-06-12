# kr_pipeline/market_context/compute/follow_through.py
"""Follow-Through Day (FTD) 감지 순수 함수.

정의 (Morales/Kacher 갱신):
- 지수 상승 +1.4% 이상 (O'Neil 원래 1.0%, 변동성 증가로 상향)
- 거래량이 전일보다 많음
- 직전 15 세션 내 저점 이후 3-15 세션 사이 발생 (rally attempt 기간)
"""
from datetime import date
import pandas as pd

from kr_pipeline.common.thresholds import (
    STATUS_FTD_RECENT_DAYS,
    FTD_PCT_BASE,
    FTD_RALLY_WINDOW_MIN_DAYS,
    FTD_RALLY_WINDOW_MAX_DAYS,
    FTD_LOW_LOOKBACK_DAYS,
)

# P2-1a: FTD_PCT_THRESHOLD 호환 별칭 제거. pct_threshold 가 detect_last_ftd
# 의 인자로 이전 — 시장별 보정 임계를 호출단 (modes.py) 이 주입.
# Window / lookback 별칭만 유지 (보정 제외 — 책 그대로).
FTD_RALLY_WINDOW_MIN = FTD_RALLY_WINDOW_MIN_DAYS
FTD_RALLY_WINDOW_MAX = FTD_RALLY_WINDOW_MAX_DAYS
FTD_LOW_LOOKBACK = FTD_LOW_LOOKBACK_DAYS


def detect_last_ftd(
    index_df: pd.DataFrame,
    end_idx: int,
    *,
    pct_threshold: float = FTD_PCT_BASE,
    lookback_days: int = STATUS_FTD_RECENT_DAYS,
) -> date | None:
    """end_idx 기준 직전 lookback_days 세션 내 가장 최근 유효 FTD 날짜 반환.

    index_df 컬럼: date, close, volume, low. date 정렬 가정.

    유효 FTD 조건:
    1. (today.close / yesterday.close - 1) * 100 >= FTD_PCT_THRESHOLD
    2. today.volume > yesterday.volume
    3. 직전 FTD_LOW_LOOKBACK 세션 내 저점이 존재
    4. 그 저점 이후 FTD_RALLY_WINDOW_MIN..FTD_RALLY_WINDOW_MAX 세션 사이에 위치
    """
    if end_idx <= 0 or len(index_df) == 0:
        return None

    start_idx = max(1, end_idx - lookback_days + 1)

    # 최신 → 과거 순회 (가장 최근 유효 FTD 가 첫 발견되면 반환)
    for i in range(end_idx, start_idx - 1, -1):
        if i >= len(index_df):
            continue
        if i < 1:
            break
        today = index_df.iloc[i]
        yesterday = index_df.iloc[i - 1]
        if yesterday["close"] == 0:
            continue
        pct = (today["close"] - yesterday["close"]) / yesterday["close"] * 100
        if pct < pct_threshold:
            continue
        if today["volume"] <= yesterday["volume"]:
            continue

        # 직전 FTD_LOW_LOOKBACK 세션 내 저점 찾기
        lookback_start = max(0, i - FTD_LOW_LOOKBACK)
        window = index_df.iloc[lookback_start:i]
        if len(window) < FTD_RALLY_WINDOW_MIN:
            continue
        low_pos_in_window = window["low"].astype(float).idxmin()
        low_idx = int(low_pos_in_window) if isinstance(low_pos_in_window, (int, pd.Int64Dtype)) else window.index.get_loc(low_pos_in_window)
        # idxmin 은 원본 인덱스 라벨. iloc 위치로 변환.
        # 단순화: window 가 reset_index 안 됐다면 idxmin 은 그대로 원본 라벨.
        # 우리 케이스는 index_df 가 0..N-1 정수 인덱스라 가정.
        try:
            low_idx_int = int(low_pos_in_window)
        except (TypeError, ValueError):
            continue

        days_from_low = i - low_idx_int
        if FTD_RALLY_WINDOW_MIN <= days_from_low <= FTD_RALLY_WINDOW_MAX:
            return today["date"] if isinstance(today["date"], date) else today["date"]

    return None
