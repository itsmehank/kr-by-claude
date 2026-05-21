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


TriggerType = Literal["breakout", "invalidation", "promotion"] | None


# Breakout 게이트의 거래량 하한: 평균 거래량 이상 (1.0×).
# 책 표준 (1.4-1.5×, O'Neil HMMS Ch.2) 의 정밀 판정은 LLM 에 위임.
# 게이트 = "거래량 죽지 않은 정도" 만 확인 (저거래량 헛돌파 차단).
BREAKOUT_VOLUME_MULTIPLIER = 1.0

# Watch → entry 승격 staging 임계: pivot 의 95% 도달.
# 책 근거 없음 — 시스템 자체 설계 (LLM 평가 시작 트리거).
# 실제 매수는 별도 breakout 게이트 (close > pivot) 를 다시 통과해야 함.
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
