"""평일 결정론 트리거 게이트 (LLM 호출 전 단계).

순수 함수. 입력값만 보고 'breakout' | 'breakout_from_watch' | 'invalidation'
| 'promotion' | None 반환.

설계 철학 (전문가 자문 2026-05-21):
    게이트는 싸고 느슨한 사전 필터 — 명백한 비후보만 제거.
    정밀 임계 (1.4~1.5× 표준, pocket pivot 예외, 일중 상단 1/3 등) 와
    예외 판단은 LLM 이 차트와 함께 수행. 게이트를 책 표준에 맞추면
    pocket pivot 같은 책의 정당한 예외가 사전 배제되는 false negative
    문제 (O'Neil 제자 책 *Trade Like an O'Neil Disciple* Ch.5 BIDU
    사례) 발생. drawdown 필터 제거 (2026-05-21) 와 같은 철학.

breakout_from_watch (watch 정당한 돌파 갭 해소):
    기존엔 watch 종목의 거래량 동반 pivot 돌파를 최대 promotion (go_now 금지)
    으로만 잡아, 시장 사유 등으로 entry 에서 강등됐던 (=pivot 유효) watch 의
    정당한 돌파를 토요일 weekend 재분류까지 체계적으로 놓쳤다. pivot 이 유효한
    watch 사유 (ALLOWED_WATCH_REASONS) 에 한해 LLM 정밀판정으로 넘긴다.
    책: O'Neil HMM 돌파일 pivot 근처 매수 'absolutely essential'.
"""
from typing import Literal

from kr_pipeline.common.thresholds import (
    GATE_BREAKOUT_VOL_MULT,
    GATE_PROMOTION_PRICE_RATIO,
)

TriggerType = (
    Literal["breakout", "breakout_from_watch", "invalidation", "promotion"] | None
)


# 호환성 별칭 — 실제 값은 SSOT (kr_pipeline/common/thresholds.py) 가 정의.
# 외부 import 가 있을 수 있어 같은 이름 유지.
BREAKOUT_VOLUME_MULTIPLIER = GATE_BREAKOUT_VOL_MULT

PROMOTION_THRESHOLD_RATIO = GATE_PROMOTION_PRICE_RATIO


# [design judgment] breakout_from_watch 대상 watch 사유.
# pivot 이 유효한 (=확정·완성) base 의 watch 만 정당한 돌파 후보. base_forming/
# extended 는 제외 (D2) — base 완성·신규 base 는 weekend 재분류가 pivot 재계산과
# 함께 처리. 추격 (>pivot+5%) 방지는 게이트가 아니라 calculate_entry_params 의
# 5% 룰 (extended_from_pivot_already) 이 담당 (loose gates, LLM/param precision).
ALLOWED_WATCH_REASONS = frozenset(
    {"unfavorable_market", "marginal_tt", "valid_base_awaiting_breakout"}
)


def evaluate(
    *,
    close: float,
    pivot_price: float,
    volume: int,
    avg_volume_50d: float,
    stop_loss: float | None,
    sma_50: float,
    classification: str,
    prev_close: float | None = None,
    watch_reason: str | None = None,
) -> TriggerType:
    """한 종목의 오늘 트리거 발동 여부 판정.

    Returns:
        "breakout"            — 상향 트리거 (entry 종목 pivot 돌파)
        "breakout_from_watch" — watch (pivot 유효 사유) 의 정당한 fresh 돌파
        "invalidation"        — 하향 트리거 (베이스 무효화 의심)
        "promotion"           — watch → entry 승격 후보 (LLM 평가 staging)
        None                  — 트리거 없음 (오늘 무시)

    평가 순서 (결정 2): invalidation → entry breakout → breakout_from_watch
    → promotion → None. close>pivot 인 날 breakout_from_watch 가 promotion 선점.
    """
    # 하향 트리거 우선 (베이스 깨짐이 더 critical)
    if stop_loss is not None and close < stop_loss:
        return "invalidation"
    if close < sma_50:
        return "invalidation"

    # 상향 트리거 (entry 분류 시) — pivot 돌파 + 거래량 죽지 않음.
    # entry 경로는 fresh_cross/watch_reason 무관 (기존 동작 보존).
    if classification == "entry":
        if close > pivot_price and volume >= avg_volume_50d * BREAKOUT_VOLUME_MULTIPLIER:
            return "breakout"

    if classification == "watch":
        # fresh cross: 어제는 pivot 이하, 오늘 pivot 돌파. extended 2차 차단 +
        # 매일 오발화 방지. prev_close 누락 시 보수적으로 False.
        fresh_cross = (
            prev_close is not None
            and prev_close <= pivot_price
            and close > pivot_price
        )
        # breakout_from_watch — promotion 보다 먼저 (close>pivot 인 날 선점)
        if (
            watch_reason in ALLOWED_WATCH_REASONS
            and fresh_cross
            and volume >= avg_volume_50d * BREAKOUT_VOLUME_MULTIPLIER
        ):
            return "breakout_from_watch"
        # watch 승격 staging — pivot 근접 (95%) + 거래량 죽지 않음
        if close >= pivot_price * PROMOTION_THRESHOLD_RATIO and volume >= avg_volume_50d:
            return "promotion"

    return None
