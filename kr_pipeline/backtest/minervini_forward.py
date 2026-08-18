"""#111 — 미너비니 전환일 forward return 결정론 검증. 읽기전용.

사전등록(LOCKED 2026-08-18):
docs/superpowers/specs/2026-08-18-issue111-minervini-forward-return-design.md
"""
from __future__ import annotations

import random
from datetime import date
from itertools import groupby
from typing import Iterator

from psycopg import Connection

SEED = 20260721
BOOT_B = 10_000
HORIZONS = (20, 40, 65)   # 4주(주 판정)·8주·13주 — 스펙 §2.2·§3
PRIMARY_H = 20

Row = tuple[date, float, bool | None, int | None]


def extract_transitions(rows: list[Row]) -> list[int]:
    """전환일 인덱스 — 직전 행 False AND 당일 True (스펙 §2.1)."""
    return [i for i in range(1, len(rows))
            if rows[i][2] is True and rows[i - 1][2] is False]


def forward_excess(rows: list[Row], i: int, horizon: int,
                   index_close: dict[date, float]) -> float | None:
    """행 i 기준 T+1 close → T+1+horizon 관측행 close 초과수익(%p). 결손 → None."""
    j, k = i + 1, i + 1 + horizon
    if k >= len(rows):
        return None
    d1, p1 = rows[j][0], rows[j][1]
    d2, p2 = rows[k][0], rows[k][1]
    i1, i2 = index_close.get(d1), index_close.get(d2)
    if i1 is None or i2 is None:
        return None
    return (p2 / p1 - 1) * 100 - (i2 / i1 - 1) * 100


def verdict_of(lo: float, hi: float) -> str:
    """스펙 §2.4 3분류."""
    if lo > 0:
        return "유효"
    if hi < 0:
        return "역효과"
    return "미입증"
