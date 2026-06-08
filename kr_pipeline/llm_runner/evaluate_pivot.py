"""평일 (5b) evaluate_pivot_trigger.

결정론 트리거 게이트 통과 종목만 LLM 호출.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from psycopg import Connection

from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as evaluate_gate
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.load import get_active_with_current
from kr_pipeline.llm_runner.store import insert_trigger_log


log = logging.getLogger("kr_pipeline.llm_runner.evaluate_pivot")


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
) -> dict:
    if as_of is None:
        as_of = date.today()

    active = get_active_with_current(conn, as_of=as_of)

    # 결정론 트리거 게이트 통과 종목 추출
    triggered: list[tuple[dict, str]] = []
    for a in active:
        if not all(
            a.get(k) is not None
            for k in ("close", "pivot_price", "volume", "avg_volume_50d", "sma_50")
        ):
            continue
        trig = evaluate_gate(
            close=a["close"],
            pivot_price=a["pivot_price"],
            volume=a["volume"],
            avg_volume_50d=a["avg_volume_50d"],
            stop_loss=a["stop_loss"],
            sma_50=a["sma_50"],
            classification=a["classification"],
            prev_close=a.get("prev_close"),
            watch_reason=a.get("watch_reason"),
        )
        if trig is not None:
            triggered.append((a, trig))

    if limit:
        triggered = triggered[:limit]

    log.info("evaluate_pivot: %d triggered out of %d active", len(triggered), len(active))

    evaluated = 0
    failed = []
    for a, trig in triggered:
        try:
            _process_one(conn, a, trig, dry_run=dry_run, as_of=as_of)
            evaluated += 1
            conn.commit()
        except Exception as e:
            log.warning("evaluate %s failed: %s", a["symbol"], e)
            failed.append(a["symbol"])
            conn.rollback()

    return {
        "evaluated": evaluated,
        "failures": len(failed),
        "active": len(active),
        "triggered": len(triggered),
    }


def _process_one(conn, active_row, trig_type, *, dry_run, as_of):
    symbol = active_row["symbol"]
    started = datetime.now(timezone.utc)

    payload = build_for_5b(conn, symbol, trigger_type=trig_type, as_of=as_of)
    result = call_claude(
        prompt_file="evaluate_pivot_trigger_v1.md",
        attachments=[],
        payload_inline=payload,
        dry_run=dry_run,
    )

    finished = datetime.now(timezone.utc)

    if dry_run:
        log.info("dry-run: skipping DB insert for %s (mock decision %s)",
                 symbol, result.get("decision"))
        return

    insert_trigger_log(
        conn,
        symbol=symbol,
        evaluated_at=finished,
        trigger_type=trig_type,
        close=active_row["close"],
        volume=active_row["volume"],
        pivot_price=active_row["pivot_price"],
        result=result,
        prior_classification_at=active_row["classified_at"],
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": None, "output_tokens": None},
    )
