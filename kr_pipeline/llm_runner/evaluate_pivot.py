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


def _already_evaluated_symbols(conn, as_of) -> set:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM trigger_evaluation_log "
            "WHERE COALESCE(analyzed_for_date, (evaluated_at AT TIME ZONE 'UTC')::date) = %s",
            (as_of,),
        )
        return {r[0] for r in cur.fetchall()}


def _aborted_since_classification(conn, active: list[dict]) -> set:
    """현재 분류(classified_at)에 대해 abort 판정난 종목 집합.

    abort 기록 시 store 가 prior_classification_at = 그 시점 classified_at 을 박아두므로,
    abort 행의 prior_classification_at == active 행의 현재 classified_at 이면 "현재 분류에
    대한 abort" 다. 재분류되면 classified_at 이 바뀌어 옛 abort 의 prior 와 불일치 → 자동 해제.
    """
    symbols = [a["symbol"] for a in active]
    if not symbols:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol, prior_classification_at "
            "FROM trigger_evaluation_log "
            "WHERE decision = 'abort' AND symbol = ANY(%s)",
            (symbols,),
        )
        abort_pairs = {(r[0], r[1]) for r in cur.fetchall()}
    result = set()
    for a in active:
        cls_at = a.get("classified_at")
        # classified_at None 이면 매칭 안 함(안전 기본값). abort prior 가 NULL 이면 (sym,NULL)
        # 쌍이 어떤 timestamp 와도 불일치 → 자연 skip-안함. .get() 必須(subscript 아님):
        # test_evaluate_pivot_guard 의 mock active 는 classified_at 키가 없어 KeyError 회피.
        if cls_at is not None and (a["symbol"], cls_at) in abort_pairs:
            result.add(a["symbol"])
    return result


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
    force: bool = False,
) -> dict:
    if as_of is None:
        as_of = date.today()

    if force and limit:
        raise ValueError("force=True 와 limit 동시 사용 금지: force 는 as_of 전체를 replace 하므로 limit 로 자르면 삭제된 행이 재생성되지 않는다")

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

    # force=replace(같은 as_of 행 삭제 후 재평가). dry_run 이면 삭제 안 함(무부작용 미리보기).
    # 기본(not force): 이미 as_of 로 평가된 종목 skip(멱등 재개).
    abort_skipped = 0
    if force and not dry_run:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trigger_evaluation_log "
                "WHERE COALESCE(analyzed_for_date, (evaluated_at AT TIME ZONE 'UTC')::date) = %s",
                (as_of,),
            )
        conn.commit()
    elif not force:
        done = _already_evaluated_symbols(conn, as_of)
        aborted = _aborted_since_classification(conn, active)
        abort_skipped = sum(1 for (a, _t) in triggered if a["symbol"] in aborted)
        triggered = [(a, t) for (a, t) in triggered if a["symbol"] not in (done | aborted)]

    if limit:
        triggered = triggered[:limit]

    log.info(
        "evaluate_pivot: %d triggered out of %d active (abort_skipped=%d)",
        len(triggered), len(active), abort_skipped,
    )

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
        "abort_skipped": abort_skipped,
    }


def _process_one(conn, active_row, trig_type, *, dry_run, as_of):
    symbol = active_row["symbol"]
    started = datetime.now(timezone.utc)

    payload = build_for_5b(conn, symbol, trigger_type=trig_type, as_of=as_of)
    llm_io: dict = {}
    result = call_claude(
        prompt_file="evaluate_pivot_trigger_v1.md",
        attachments=[],
        payload_inline=payload,
        dry_run=dry_run,
        meta_out=llm_io,
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
                  "input_tokens": llm_io.get("input_tokens"),
                  "output_tokens": llm_io.get("output_tokens"),
                  "model": llm_io.get("model")},
        analyzed_for_date=as_of,
    )
