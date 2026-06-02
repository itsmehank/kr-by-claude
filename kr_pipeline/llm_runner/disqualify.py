"""평일 강등 점검 — 최신 분류 종목이 minervini 미통과로 떨어지면 disqualified 기록.

결정론·LLM 미호출. run_full_daily 맨 앞에서 실행. 멱등(이미 disqualified 는 대상 밖).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from psycopg import Connection

from kr_pipeline.llm_runner.load import get_classified_losing_minervini
from kr_pipeline.llm_runner.store import insert_disqualification

log = logging.getLogger("kr_pipeline.llm_runner.disqualify")


def run(conn: Connection, *, dry_run: bool = False, as_of: date | None = None,
        limit: int | None = None) -> dict:
    if as_of is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
            row = cur.fetchone()
        as_of = row[0] if row and row[0] else date.today()

    losers = get_classified_losing_minervini(conn, as_of)
    if limit:
        losers = losers[:limit]
    log.info("disqualify: %d candidate(s) losing minervini as_of=%s", len(losers), as_of)

    classified_at = datetime.now(timezone.utc)
    count = 0
    for x in losers:
        if dry_run:
            continue
        try:
            insert_disqualification(conn, symbol=x["symbol"], classified_at=classified_at,
                                    market=x["market"], analyzed_for_date=as_of)
            conn.commit()
            count += 1
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            log.warning("disqualify failed symbol=%s: %s", x["symbol"], e)

    return {"disqualified": count, "candidates": len(losers), "as_of": str(as_of)}
