"""평일 결정론 트리거 게이트 (LLM 호출 전 단계).

순수 함수. 입력값만 보고 'breakout' | 'invalidation' | 'promotion' | None 반환.

설계 철학 (전문가 자문 2026-05-21):
    게이트는 싸고 느슨한 사전 필터 — 명백한 비후보만 제거.
    정밀 임계 (1.4~1.5× 표준, pocket pivot 예외, 일중 상단 1/3 등) 와
    예외 판단은 LLM 이 차트와 함께 수행. 게이트를 책 표준에 맞추면
    pocket pivot 같은 책의 정당한 예외가 사전 배제되는 false negative
    문제 (O'Neil 제자 책 *Trade Like an O'Neil Disciple* Ch.5 BIDU
    사례) 발생. drawdown 필터 제거 (2026-05-21) 와 같은 철학.
"""
from typing import Literal

from kr_pipeline.common.thresholds import (
    GATE_BREAKOUT_VOL_MULT,
    GATE_PROMOTION_PRICE_RATIO,
)

TriggerType = Literal["breakout", "invalidation", "promotion"] | None


# 호환성 별칭 — 실제 값은 SSOT (kr_pipeline/common/thresholds.py) 가 정의.
# 외부 import 가 있을 수 있어 같은 이름 유지.
BREAKOUT_VOLUME_MULTIPLIER = GATE_BREAKOUT_VOL_MULT

PROMOTION_THRESHOLD_RATIO = GATE_PROMOTION_PRICE_RATIO


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
        "breakout"     — 상향 트리거 (entry 종목 pivot 돌파)
        "invalidation" — 하향 트리거 (베이스 무효화 의심)
        "promotion"    — watch → entry 승격 후보 (LLM 평가 staging)
        None           — 트리거 없음 (오늘 무시)
    """
    # 하향 트리거 우선 (베이스 깨짐이 더 critical)
    if close < stop_loss:
        return "invalidation"
    if close < sma_50:
        return "invalidation"

    # 상향 트리거 (entry 분류 시) — pivot 돌파 + 거래량 죽지 않음
    if classification == "entry":
        if close > pivot_price and volume >= avg_volume_50d * BREAKOUT_VOLUME_MULTIPLIER:
            return "breakout"

    # watch 승격 staging — pivot 근접 (95%) + 거래량 죽지 않음
    if classification == "watch":
        if close >= pivot_price * PROMOTION_THRESHOLD_RATIO and volume >= avg_volume_50d:
            return "promotion"

    return None
