"""모드별 오케스트레이션."""
from __future__ import annotations

import logging
from datetime import date

from psycopg import Connection

from kr_pipeline.llm_runner import (
    weekend, daily_delta, disqualify, evaluate_pivot, entry_params, performance,
)
from kr_pipeline.llm_runner.slack import notify_weekend_digest


log = logging.getLogger("kr_pipeline.llm_runner.modes")


def run_full_daily(conn: Connection, *, dry_run: bool, as_of: date, limit: int | None) -> dict:
    """평일 통합: disqualify → daily_delta → evaluate → entry → performance."""
    r0 = disqualify.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r1 = daily_delta.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r2 = evaluate_pivot.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r3 = entry_params.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r4 = performance.run(conn, as_of=as_of)
    return {"disqualify": r0, "daily_delta": r1, "evaluate": r2, "entry": r3, "performance": r4}


def run_weekend(
    conn: Connection,
    *,
    dry_run: bool,
    as_of: date,
    limit: int | None,
    ticker: str | None = None,
) -> dict:
    """주말: (5) batch + digest. ticker 지정 시 단일 종목 디버깅 mode."""
    r = weekend.run(conn, dry_run=dry_run, as_of=as_of, limit=limit, ticker=ticker)
    # 분포 집계 (timezone-aware 비교)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT classification, COUNT(*) FROM weekly_classification
             WHERE (classified_at AT TIME ZONE 'UTC')::date = (
               SELECT MAX((classified_at AT TIME ZONE 'UTC')::date)
                 FROM weekly_classification WHERE source='weekend'
             )
               AND source = 'weekend'
             GROUP BY classification
            """
        )
        dist = dict(cur.fetchall())
    notify_weekend_digest(
        entry_count=dist.get("entry", 0),
        watch_count=dist.get("watch", 0),
        ignore_count=dist.get("ignore", 0),
    )
    return r
