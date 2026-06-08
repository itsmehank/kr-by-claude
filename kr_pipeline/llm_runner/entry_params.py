"""평일 (6) calculate_entry_params.

오늘 (5b) 결과 중 decision == 'go_now' 종목만 처리.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from psycopg import Connection

from kr_pipeline.llm_runner.compute.payload_lite import build_for_6
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.store import insert_entry_params, _normalize_entry_params


log = logging.getLogger("kr_pipeline.llm_runner.entry_params")


def _fetch_go_now_candidates(conn, as_of: date) -> list:
    """오늘 go_now breakout 신호 중 2E_tier2 차단 제외한 후보.

    breakout_from_watch (watch 정당한 돌파) 도 breakout 과 동일 취급 — go_now 면 매수 계획 대상.
    (게이트의 fresh_cross + §3.5 표준검증을 이미 통과; 추격은 본 단계 5% 룰이 거름.)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.symbol, t.evaluated_at, t.prior_classification_at
              FROM trigger_evaluation_log t
             WHERE (t.evaluated_at AT TIME ZONE 'UTC')::date = %s
               AND t.decision = 'go_now'
               AND t.trigger_type IN ('breakout', 'breakout_from_watch')
               AND NOT EXISTS (
                   SELECT 1 FROM weekly_classification wc
                    WHERE wc.symbol = t.symbol
                      AND wc.classified_at = (
                          SELECT MAX(classified_at) FROM weekly_classification
                           WHERE symbol = t.symbol
                      )
                      AND wc.triggered_rules ? '2E_tier2'
               )
             ORDER BY t.evaluated_at
            """,
            (as_of,),
        )
        return cur.fetchall()


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
) -> dict:
    if as_of is None:
        as_of = date.today()

    # 오늘 (5b) 결과 중 go_now 추출 — 2E_tier2 차단 종목 제외 (Phase 1 2-A).
    # 안전장치: promotion 트리거는 staging 신호 — close 가 pivot 미만일 수
    # 있어 매수 부적절. 만약 LLM 이 promotion 에 대해 go_now 결정해도
    # entry_params 단계로 진입 금지 (prompt §3.3 명시). 안전장치는 prompt
    # 위반 시에도 pivot 미만 매수 시그널이 생성되지 않도록 SQL 에서 강제.
    go_now = _fetch_go_now_candidates(conn, as_of)

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

    if dry_run:
        _normalize_entry_params(result)  # §9 정합 검증(드리프트 시 ValueError) — insert 는 skip
        log.info("dry-run: validated entry plan for %s (skipping DB insert)", symbol)
        return

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
