"""(#166 2026-09-08) 이익목표 절반매도(5B) — backtest·production 공용 순수 판정 함수.

로직 = backtest portfolio.py 5B 그대로(파리티 이식):
  +20%(SELL_HALF_GAIN_PCT) 최초 도달일 t:
    (t − entry_date) > EARLY_GAIN_DAYS(21)  → 즉시 절반매도(권고)          [reason "immediate"]
    ≤ 21                                   → half_pending: entry + TRADE_HOLD_MIN_DAYS(56) 후
                                             첫 평가일에 close ≥ entry×(1+gain) 이면 권고  [reason "week8"]
                                             미만이면 소멸(half_expired)
  발화는 포지션당 1회(fired 후 상태 불변). 플래그(SELL_HALF_ENABLED) 판정은 호출자 몫 —
  이 함수는 hit20_date(8주 면제 판정에도 쓰임)를 항상 갱신한다.

book-permitted(의무 아님): HMMS 20~25% 일부 실현 + 1~3주 예외 + 8주 규칙 / TTLC 절반매도.
production 은 권고만(수량 변경 없음, 전량 모델 유지 — 손절 계산은 수량 비참조).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kr_pipeline.common.thresholds import EARLY_GAIN_DAYS, SELL_HALF_GAIN_PCT, TRADE_HOLD_MIN_DAYS


@dataclass(frozen=True)
class SellHalfState:
    hit20_date: date | None = None
    half_pending: bool = False
    fired: bool = False          # 절반매도 발화됨(포지션당 1회)
    half_expired: bool = False


@dataclass(frozen=True)
class SellHalfDecision:
    fire: bool                   # 이번 평가에서 절반매도 권고(백테스트: 절반 매도 집행)
    reason: str | None           # "immediate" | "week8" | None
    hit20_new: bool              # 이번 평가에서 +20% 최초 도달
    within_early: bool | None    # hit20_new 일 때 (t − entry) ≤ EARLY_GAIN_DAYS 인가
    state: SellHalfState         # 갱신된 상태(호출자가 영속)


def evaluate_sell_half(*, entry_date: date, entry_price: float, close: float, as_of: date,
                       state: SellHalfState, early_gain_days: int = EARLY_GAIN_DAYS,
                       hold_min_days: int = TRADE_HOLD_MIN_DAYS,
                       gain_pct: float = SELL_HALF_GAIN_PCT) -> SellHalfDecision:
    target = entry_price * (1 + gain_pct)
    hold = (as_of - entry_date).days
    if state.fired or state.half_expired:
        return SellHalfDecision(False, None, False, None, state)
    # ① +20% 최초 도달
    if state.hit20_date is None:
        if close >= target:
            within = hold <= early_gain_days
            if within:
                return SellHalfDecision(False, None, True, True,
                                        SellHalfState(as_of, True, False, False))
            return SellHalfDecision(True, "immediate", True, False,
                                    SellHalfState(as_of, False, True, False))
        return SellHalfDecision(False, None, False, None, state)
    # ② 8주차 처분(21일 내 도달 → 진입+56일 후 첫 평가일)
    if state.half_pending and hold > hold_min_days:
        if close >= target:
            return SellHalfDecision(True, "week8", False, None,
                                    SellHalfState(state.hit20_date, False, True, False))
        return SellHalfDecision(False, None, False, None,
                                SellHalfState(state.hit20_date, False, False, True))
    return SellHalfDecision(False, None, False, None, state)
