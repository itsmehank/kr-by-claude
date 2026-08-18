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


def agg_bootstrap_ci(by_ticker: dict[str, tuple[float, int]], *, b: int = BOOT_B,
                     seed: int = SEED) -> tuple[float, float]:
    """cluster_bootstrap_ci 등가 — 같은 rng 시퀀스, (합, 개수) 집계 (스펙 §2.5)."""
    keys = sorted(by_ticker)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(b):
        s, c = 0.0, 0
        for _ in range(len(keys)):
            ts, tc = by_ticker[rng.choice(keys)]
            s += ts
            c += tc
        means.append(s / c)
    means.sort()
    lo = means[int(0.025 * b)]
    hi = means[min(int(0.975 * b), b - 1)]
    return (round(lo, 3), round(hi, 3))


def horizon_stats(events: list[dict], h: int) -> dict:
    """horizon 별 표본·평균·중앙값·클러스터 CI. 결손(키 부재) 이벤트는 제외."""
    key = f"excess_{h}"
    by_ticker: dict[str, tuple[float, int]] = {}
    vals: list[float] = []
    for e in events:
        v = e.get(key)
        if v is None:
            continue
        vals.append(v)
        s, c = by_ticker.get(e["ticker"], (0.0, 0))
        by_ticker[e["ticker"]] = (s + v, c + 1)
    if not vals:
        return {"n": 0}
    vs = sorted(vals)
    n = len(vs)
    median = vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2
    lo, hi = agg_bootstrap_ci(by_ticker)
    return {"n": n, "tickers": len(by_ticker), "mean": round(sum(vals) / n, 3),
            "median": round(median, 3), "ci95": [lo, hi]}
