# kr_pipeline/trade_management/stop_stack.py
"""(#3 이슈4) manage_active_trade 코어 — 3층 손절 스택 결정론 평가.

백테스트 검증 규칙(docs/trading-rules-book-verified.md §2 = v2.1, 스택 준거 구현
kr_pipeline/backtest/portfolio.py)의 production 이식. 순수 함수 —
포지션 상태(래치)는 호출자가 운반한다. 파이프라인 wiring(포지션 소스·일일
평가 러너)은 실전 전환 결정 후 별도 착수:
docs/superpowers/specs/2026-07-13-manage-active-trade.md.

불변 계약 (스펙 §3):
- anchor(entry_price = 평균매입가)는 매수 시점 값으로 고정 — 보유 중 주간
  재분류가 갱신하는 pivot/base_low 유입 금지 (#1 재판독 절연).
- 워치리스트 재검토용 base_low 정의(load.get_active_with_current)를 포지션
  손절로 재사용 금지 (이슈 #3 이슈3 — 무클램프 구조적 스톱).
"""
from __future__ import annotations

from dataclasses import dataclass

from kr_pipeline.common.thresholds import (
    TRADE_BREAKEVEN_TRIGGER_PCT,
    TRADE_STOP_INITIAL_PCT,
    TRADE_STOP_MAX_PCT,
)


@dataclass(frozen=True)
class StopDecision:
    """하루치 손절 평가 결과."""

    effective_stop: float
    binding: str  # 'initial_stop' | 'breakeven' | 'sma50_trail'
    breakeven_armed: bool  # 갱신된 래치 (호출자가 다음 날로 운반)
    triggered: bool  # close < effective_stop → 매도 신호


def evaluate_stop(
    *,
    entry_price: float,
    close: float,
    sma_50: float | None,
    breakeven_armed: bool,
    initial_stop_pct: float = TRADE_STOP_INITIAL_PCT,
) -> StopDecision:
    """당일 유효 손절선 산출 — max(initial, [breakeven], [sma50]) (시뮬 의미론 동일).

    - 래치(장전식)는 당일 종가로 먼저 판정: close >= entry × (1 + min(3R, 20%))
      도달 시 당일부터 본전(entry)이 바닥, 이후 해제 없음 (R = initial_stop_pct —
      책-검증 대장 §2 ② '장전식 = min(3R, +20%)', portfolio.py v2.1 동일.
      기본 8% 스톱에서는 min(24%, 20%) = 20% 로 단순 +20% 와 동치).
    - sma_50 은 **Breakeven or Better**: sma_50 >= entry 인 날부터만 플로어 후보
      (책-검증 대장 §2 ③, portfolio.py:161 동일 — 미장전 구간에서 본전 미만의
      sma50 이 스톱을 끌어올리는 것 방지). None(미산출) → 제외.
    - triggered 는 `close < effective_stop` (경계 == 는 미발동).
    - initial_stop_pct 는 (0, uncle point 10%] 범위 강제 — fail-closed.
    - close 는 양수 필수 — halt 센티널(0-바)·결측 봉은 평가 대상이 아니며
      호출자(향후 wiring 러너)가 사전에 걸러야 한다.
    """
    if entry_price is None or not (entry_price > 0):
        raise ValueError(f"entry_price must be positive: {entry_price}")
    if close is None or not (close > 0):
        raise ValueError(
            f"close must be positive (halt/결측 봉은 평가 불가): {close}"
        )
    if not (0 < initial_stop_pct <= TRADE_STOP_MAX_PCT):
        raise ValueError(
            f"initial_stop_pct={initial_stop_pct} not in (0, uncle point "
            f"TRADE_STOP_MAX_PCT={TRADE_STOP_MAX_PCT}]"
        )

    # DB 유래 truthy(int/str)를 bool 로 정규화 — 반환 스키마 안정 (#40 재리뷰)
    breakeven_armed = bool(breakeven_armed)
    arming_pct = min(3 * initial_stop_pct, TRADE_BREAKEVEN_TRIGGER_PCT)
    if not breakeven_armed and close >= entry_price * (1 + arming_pct):
        breakeven_armed = True

    candidates: list[tuple[str, float]] = [
        ("initial_stop", entry_price * (1 - initial_stop_pct))
    ]
    if breakeven_armed:
        candidates.append(("breakeven", entry_price))
    if sma_50 is not None and float(sma_50) >= entry_price:
        candidates.append(("sma50_trail", float(sma_50)))

    # 동률 tie-break 는 준거(portfolio.py 의 (값, 라벨) 튜플 비교 — 사전순 최대)와
    # 동일: sma50 == entry(장전 상태) 동률에서 라벨 'sma50_trail' (#40 재리뷰 🟡7).
    binding, effective_stop = max(candidates, key=lambda x: (x[1], x[0]))
    return StopDecision(
        effective_stop=effective_stop,
        binding=binding,
        breakeven_armed=breakeven_armed,
        triggered=close < effective_stop,
    )
