"""국면 라벨 — market_context_daily.current_status 를 (date 이하 최근) 으로 조회. 읽기전용."""
from __future__ import annotations

import bisect
from datetime import date

from psycopg import Connection

INDEX_OF = {"KOSPI": "1001", "KOSDAQ": "2001"}


def load_phase_map(conn: Connection, index_code: str) -> list[tuple[date, str]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, current_status FROM market_context_daily "
            "WHERE index_code = %s ORDER BY date",
            (index_code,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def phase_at(phase_map: list[tuple[date, str]], on: date) -> str | None:
    """on 이하 가장 최근 current_status. phase_map 은 date 오름차순."""
    dates = [d for d, _ in phase_map]
    i = bisect.bisect_right(dates, on) - 1
    return phase_map[i][1] if i >= 0 else None
