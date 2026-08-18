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


def load_index_closes(conn: Connection) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT index_code, date, close FROM index_daily")
        for code, d, c in cur.fetchall():
            out.setdefault(code, {})[d] = float(c)
    return out


def load_markets(conn: Connection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, market FROM stocks")
        return dict(cur.fetchall())


def iter_ticker_rows(conn: Connection) -> Iterator[tuple[str, list[Row]]]:
    """종목별 date 오름차순 행 — 서버측 커서 스트리밍(532만 행 메모리 회피)."""
    with conn.cursor(name="minervini_forward_rows") as cur:
        cur.itersize = 50_000
        cur.execute(
            "SELECT ticker, date, adj_close, minervini_pass, "
            "(minervini_c1::int + minervini_c2::int + minervini_c3::int"
            " + minervini_c4::int + minervini_c5::int + minervini_c6::int"
            " + minervini_c7::int + minervini_c8::int) "
            "FROM daily_indicators ORDER BY ticker, date")
        for ticker, grp in groupby(cur, key=lambda r: r[0]):
            yield ticker, [(d, float(a), p, cc) for _, d, a, p, cc in grp]


def transition_events(conn: Connection) -> tuple[list[dict], dict[int, int]]:
    """전 종목 전환 이벤트 + horizon 별 제외 건수 (스펙 §2.1~§2.3·§3)."""
    from kr_pipeline.backtest.phases import INDEX_OF
    idx = load_index_closes(conn)
    markets = load_markets(conn)
    events: list[dict] = []
    excluded = {h: 0 for h in HORIZONS}
    for ticker, rows in iter_ticker_rows(conn):
        iclose = idx.get(INDEX_OF.get(markets.get(ticker, ""), "1001"), {})
        for i in extract_transitions(rows):
            ev: dict = {"ticker": ticker, "date": rows[i][0].isoformat()}
            for h in HORIZONS:
                x = forward_excess(rows, i, h, iclose)
                if x is None:
                    excluded[h] += 1
                else:
                    ev[f"excess_{h}"] = round(x, 4)
            events.append(ev)
    return events, excluded
