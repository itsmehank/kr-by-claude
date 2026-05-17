"""평일 (6) calculate_entry_params.

오늘 (5b) 결과 중 decision == 'go_now' 종목만 처리.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from psycopg import Connection

from kr_pipeline.llm_runner.compute.payload_lite import build_for_6
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.store import insert_entry_params


log = logging.getLogger("kr_pipeline.llm_runner.entry_params")


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
) -> dict:
    if as_of is None:
        as_of = date.today()

    # 오늘 (5b) 결과 중 go_now 추출 (UTC 기준 날짜 비교)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, evaluated_at, prior_classification_at
              FROM trigger_evaluation_log
             WHERE (evaluated_at AT TIME ZONE 'UTC')::date = %s
               AND decision = 'go_now'
             ORDER BY evaluated_at
            """,
            (as_of,),
        )
        go_now = cur.fetchall()

    if limit:
        go_now = go_now[:limit]

    log.info("entry_params: %d go_now signals", len(go_now))

    processed = 0
    failed = []
    for symbol, eval_at, prior_at in go_now:
        try:
            _process_one(conn, symbol, eval_at, prior_at, dry_run=dry_run)
            processed += 1
            conn.commit()
        except Exception as e:
            log.warning("entry_params %s failed: %s", symbol, e)
            failed.append(symbol)
            conn.rollback()

    return {"processed": processed, "failures": len(failed)}


def _process_one(conn, symbol, eval_at, prior_at, *, dry_run):
    started = datetime.now(timezone.utc)
    payload = build_for_6(conn, symbol, evaluation_at=eval_at)
    result = call_claude(
        prompt_file="calculate_entry_params_v2_0.md",
        attachments=[],
        payload_inline=payload,
        dry_run=dry_run,
    )
    finished = datetime.now(timezone.utc)
    insert_entry_params(
        conn,
        symbol=symbol,
        signal_at=finished,
        result=result,
        trigger_evaluation_at=eval_at,
        prior_classification_at=prior_at,
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": None, "output_tokens": None},
    )
