"""평일 결정론 트리거 게이트 (LLM 호출 전 단계, spec §1.4.2).

순수 함수. 입력값만 보고 'breakout' | 'invalidation' | 'promotion' | None 반환.
"""
from typing import Literal


TriggerType = Literal["breakout", "invalidation", "promotion"] | None


# 책 근거: O'Neil HTMMIS Ch.2 "Volume Percent Change" — 1.4-1.5x avg
BREAKOUT_VOLUME_MULTIPLIER = 1.5

# watch → entry 승격 임계: pivot 의 95% 도달
PROMOTION_THRESHOLD_RATIO = 0.95


def evaluate(
    *,
    close: float,
    pivot_price: float,
    volume: int,
    avg_volume_50d: float,
    stop_loss: float,
    sma_50: float,
    classification: str,
) -> TriggerType:
    """한 종목의 오늘 트리거 발동 여부 판정.

    Returns:
        "breakout"     — 상향 트리거 (entry 종목 매수 신호)
        "invalidation" — 하향 트리거 (베이스 무효화 의심)
        "promotion"    — watch → entry 승격 후보
        None           — 트리거 없음 (오늘 무시)
    """
    # 하향 트리거 우선 (베이스 깨짐이 더 critical)
    if close < stop_loss:
        return "invalidation"
    if close < sma_50:
        return "invalidation"

    # 상향 트리거 (entry 분류 시)
    if classification == "entry":
        if close > pivot_price and volume >= avg_volume_50d * BREAKOUT_VOLUME_MULTIPLIER:
            return "breakout"

    # watch 승격
    if classification == "watch":
        if close >= pivot_price * PROMOTION_THRESHOLD_RATIO and volume >= avg_volume_50d:
            return "promotion"

    return None
