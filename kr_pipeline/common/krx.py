"""KRX 시장 규칙 유틸 — 호가 단위(tick size).

2023-01-25 호가 단위 개편 이후 KOSPI/KOSDAQ 공통 단일 체계.
소비처: store §4.7 pivot 사후검증 (§7 'base high + 1 tick' 관례 판정, #38 재리뷰).
"""
from __future__ import annotations

# (하한, tick) — 가격이 하한 이상이면 해당 tick. 내림차순 탐색.
_TICK_BANDS = (
    (500_000, 1_000),
    (200_000, 500),
    (50_000, 100),
    (20_000, 50),
    (5_000, 10),
    (2_000, 5),
    (0, 1),
)


def krx_tick_size(price: float) -> int:
    """해당 가격대의 KRX 호가 단위(원). price ≤ 0 은 최소 tick(1원)로 처리."""
    for floor, tick in _TICK_BANDS:
        if price >= floor:
            return tick
    return 1
