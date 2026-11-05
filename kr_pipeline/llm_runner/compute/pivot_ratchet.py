"""(#253) 같은 베이스 pivot 하향 재판독 방향 한정 래칫 — 순수 함수.

스펙: docs/superpowers/specs/2026-11-05-issue253-pivot-ratchet-design.md §3.1.

주간 분류는 직전 판독을 LLM 에 보여주지 않는다(#1 anchoring 방지). 그 대가로 같은
베이스에서 pivot 이 낮게 재판독되면 "기준선이 내려와서" 돌파가 성립하는 경로가 열린다
(#129 실측: 049430 23,650 → 22,050 뒤 breakout_from_watch 3회, 전부 옛 pivot 아래).
이 함수는 저장 시 트리거가 쓸 pivot(effective_pivot)을 정한다. LLM 판독값(pivot_price)은
호출자가 그대로 저장한다.

책 근거 태그(전문가 사실 확인 2026-11-05, #253 코멘트):
- 상향 수용(accepted): PRESERVES — TTLC §7 "additional pivot points at progressively higher
  prices", TLSMW p.244.
- 원래 pivot 아래 매수 = 조기 매수: PRESERVES — HMMS 4판 p.118, TLSMW p.229.
- 하향 거부(kept) 자체: [design-judgment] — 책 명문 없음(HMMS p.116/118/140 과 충돌 없음).
- cheat_release: 3-C/low cheat 는 같은 컵 안의 정당한 더 낮은 pivot(TLSMW pp.243–245,
  TTLC §7). 현 파이프라인은 3c_cheat 를 식별하지 않아(저장 0행) 조건부 조항.
"""
from __future__ import annotations

import math

_CONTINUOUS = frozenset({"same", "near"})


def ratchet_pivot(
    new_pivot: float | None,
    prev_effective: float | None,
    continuity: str | None,
    new_pattern: str | None,
) -> tuple[float | None, str]:
    """(effective_pivot, reason). 조건은 위에서부터 먼저 맞는 것 하나.

    reason ∈ no_pivot | no_baseline | released | unknown | cheat_release | kept | accepted.
    continuity=None 은 직전 활성(entry/watch) 기준이 없다는 뜻(_pivot_continuity None).
    """
    if new_pivot is None or not math.isfinite(new_pivot):
        return None, "no_pivot"
    if continuity is None or prev_effective is None or not math.isfinite(prev_effective):
        return new_pivot, "no_baseline"
    if continuity == "different":
        return new_pivot, "released"
    if continuity not in _CONTINUOUS:
        return new_pivot, "unknown"
    if new_pattern == "3c_cheat":
        return new_pivot, "cheat_release"
    if new_pivot < prev_effective:
        return prev_effective, "kept"
    return new_pivot, "accepted"
