"""수익성·강건성 백테스트 표집 — 결정론 무작위(시드 고정). 읽기전용."""
from __future__ import annotations

import random
from datetime import date

from psycopg import Connection

DEFAULT_SEED = 20260623


def build_frame(conn: Connection, start: date, end: date) -> list[str]:
    """기간 내 production 주말 필터(get_qualifying_tickers 와 동일 조건)를 한 번이라도
    통과한 종목 집합. 금요일 기준(주간 cadence)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT i.ticker
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date BETWEEN %s AND %s
               AND EXTRACT(DOW FROM i.date) = 5
               AND i.minervini_pass = TRUE
               AND i.rs_line_not_declining_7m = TRUE
               AND s.delisted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM daily_prices p
                    WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL
               )
             ORDER BY i.ticker
            """,
            (start, end),
        )
        return [r[0] for r in cur.fetchall()]


def draw_sample(frame: list[str], n: int = 100, seed: int = DEFAULT_SEED) -> list[str]:
    """결정론 단순무작위 추출. 입력 순서 무관(내부 정렬), 결과 정렬 반환."""
    pool = sorted(set(frame))
    if len(pool) <= n:
        return pool
    return sorted(random.Random(seed).sample(pool, n))


def sample_composition(conn: Connection, tickers: list[str]) -> dict:
    if not tickers:
        return {"n": 0, "by_market": {}, "by_sector": {}}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT market, COALESCE(sector,'(none)') FROM stocks WHERE ticker = ANY(%s)",
            (tickers,),
        )
        rows = cur.fetchall()
    by_market: dict[str, int] = {}
    by_sector: dict[str, int] = {}
    for market, sector in rows:
        by_market[market] = by_market.get(market, 0) + 1
        by_sector[sector] = by_sector.get(sector, 0) + 1
    return {"n": len(tickers), "by_market": by_market, "by_sector": by_sector}
