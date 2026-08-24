"""recent_transition_count_63d — A(analyze_chart) payload 자문 입력.

#118 12차 채택·13차 변경 지점 맵 승인(docs/superpowers/specs/
2026-08-24-rtc63d-advisory-input-map.md). 태그: design-judgment +
**예측력 미확증(탐색 유래)** — 하드 게이트 승격 재논의 시 순환성 가드 병기.

정의 계보(13차 확인 ①): F→T 전환 = kr_pipeline.backtest.minervini_forward.
extract_transitions 의 #111/#117 이벤트 정의 자구 그대로 — "직전 행 False
AND 당일 True"(스펙 §2.1). 복제 금지 관례에 따라 그 함수를 직접 재사용해
자구 동일을 코드로 보장한다.
"""
from __future__ import annotations

from typing import Sequence

from kr_pipeline.backtest.minervini_forward import extract_transitions

# §0 정의 상수 — thresholds.py 무접촉(맵 §2: 신규 SSOT 상수 아님, 지역 정의).
WINDOW_ROWS = 63


def recent_transition_count_63d(passes: Sequence[bool | None]) -> int | None:
    """기준일(마지막 행) 포함 직전 63거래일 내 minervini_pass F→T 전환 횟수.

    - 관측창 <63거래일 → **None (0 금지)** — 신규 상장이 '전환 0회 = 안정
      통과'로 위장되는 것 방지(13차 확인 ②, #125 가설(d) 접점).
    - 결측(None) 행은 True/False 어느 쪽도 아님 → 해당 행 전환 판정 불성립
      (#117 자구의 is True / is False 그대로 — 인접성 재접합 없음).
    - look-ahead 금지: 호출자는 기준일 이후 행을 전달하지 않는다. 창 시작
      행의 전환 판정을 위해 직전 1행까지만 추가 관측(총 64행 소비).
    """
    if len(passes) < WINDOW_ROWS:
        return None
    tail = passes[-(WINDOW_ROWS + 1):]
    rows = [(None, None, p, None) for p in tail]
    return len(extract_transitions(rows))
