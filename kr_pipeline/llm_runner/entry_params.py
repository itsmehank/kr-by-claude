"""평일 (6) calculate_entry_params.

오늘 (5b) 결과 중 decision == 'go_now' 종목만 처리.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from psycopg import Connection

from kr_pipeline.llm_runner.compute.payload_lite import build_for_6
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError
from kr_pipeline.llm_runner.slack import notify_signal
from kr_pipeline.llm_runner.store import insert_entry_params, _normalize_entry_params


log = logging.getLogger("kr_pipeline.llm_runner.entry_params")


def _fetch_go_now_candidates(conn, as_of: date, force: bool = False) -> list:
    """as_of go_now breakout(+from_watch) 후보. 2E_tier2 제외.

    force=False 면 이미 entry_params(같은 as_of) 있는 종목 skip(멱등 재개).
    같은 as_of·종목 trigger 행이 둘 이상이어도 DISTINCT ON 으로 1건만.
    """
    skip_clause = "" if force else """
               AND NOT EXISTS (
                   SELECT 1 FROM entry_params ep
                    WHERE ep.symbol = t.symbol
                      AND COALESCE(ep.analyzed_for_date, (ep.signal_at AT TIME ZONE 'UTC')::date) = %(as_of)s
               )"""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT ON (t.symbol) t.symbol, t.evaluated_at, t.prior_classification_at
              FROM trigger_evaluation_log t
             WHERE COALESCE(t.analyzed_for_date, (t.evaluated_at AT TIME ZONE 'UTC')::date) = %(as_of)s
               AND t.decision = 'go_now'
               AND t.trigger_type IN ('breakout', 'breakout_from_watch')
               AND NOT EXISTS (
                   SELECT 1 FROM weekly_classification wc
                    WHERE wc.symbol = t.symbol
                      AND wc.classified_at = (
                          SELECT MAX(classified_at) FROM weekly_classification WHERE symbol = t.symbol
                      )
                      AND wc.triggered_rules ? '2E_tier2'
               ){skip_clause}
             ORDER BY t.symbol, t.evaluated_at DESC
            """,
            {"as_of": as_of},
        )
        return cur.fetchall()


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

    # 오늘 (5b) 결과 중 go_now 추출 — 2E_tier2 차단 종목 제외 (Phase 1 2-A).
    # 안전장치: promotion 트리거는 staging 신호 — close 가 pivot 미만일 수
    # 있어 매수 부적절. 만약 LLM 이 promotion 에 대해 go_now 결정해도
    # entry_params 단계로 진입 금지 (prompt §3.3 명시). 안전장치는 prompt
    # 위반 시에도 pivot 미만 매수 시그널이 생성되지 않도록 SQL 에서 강제.
    if force and not dry_run:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM entry_params "
                "WHERE COALESCE(analyzed_for_date, (signal_at AT TIME ZONE 'UTC')::date) = %s",
                (as_of,),
            )
        conn.commit()
    go_now = _fetch_go_now_candidates(conn, as_of, force=force)

    if limit:
        go_now = go_now[:limit]

    log.info("entry_params: %d go_now signals", len(go_now))

    processed = 0
    failed = []
    for symbol, eval_at, prior_at in go_now:
        try:
            _process_one(conn, symbol, eval_at, prior_at, dry_run=dry_run, as_of=as_of)
            processed += 1
            conn.commit()
        except UsageLimitError:
            # 사용량 제한 — 남은 종목 순회가 전부 헛호출이므로 즉시 중단.
            # 예외 전파 → run_tracking failed → 재실행 계기 확보. 기처리분은 commit 완료 +
            # _fetch_go_now_candidates 의 NOT EXISTS 가드가 재실행 시 이어하기.
            conn.rollback()
            log.warning("entry_params usage limit at %s — aborting (processed=%d/%d)",
                        symbol, processed, len(go_now))
            raise
        except Exception as e:
            log.warning("entry_params %s failed: %s", symbol, e)
            failed.append(symbol)
            conn.rollback()

    return {"processed": processed, "failures": len(failed)}


def _process_one(conn, symbol, eval_at, prior_at, *, dry_run, as_of):
    started = datetime.now(timezone.utc)
    payload = build_for_6(conn, symbol, evaluation_at=eval_at)
    llm_io: dict = {}
    result = call_claude(
        prompt_file="calculate_entry_params_v2_0.md",
        attachments=[],
        payload_inline=payload,
        dry_run=dry_run,
        meta_out=llm_io,
    )
    finished = datetime.now(timezone.utc)

    if dry_run:
        _normalize_entry_params(result)  # §9 정합 검증(드리프트 시 ValueError) — insert 는 skip
        log.info("dry-run: validated entry plan for %s (skipping DB insert)", symbol)
        return

    # 알림용 값은 insert 전에 캡처 — _normalize 가 §9 키를 리네임할 수 있음
    _ntf_entry = float(result["trigger_price"])
    _ntf_stop = float(result["stop_loss_price"])

    insert_entry_params(
        conn,
        symbol=symbol,
        signal_at=finished,
        result=result,
        trigger_evaluation_at=eval_at,
        prior_classification_at=prior_at,
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": llm_io.get("input_tokens"),
                  "output_tokens": llm_io.get("output_tokens"),
                  "model": llm_io.get("model")},
        analyzed_for_date=as_of,
    )

    # 매수 시그널 Slack 알림 — 적재 성공 시에만(dry-run 은 위에서 return).
    # _post 가 webhook 미설정/실패를 자체 흡수하므로 fail-soft.
    notify_signal(
        symbol=symbol,
        name=payload.get("name") or symbol,
        entry_price=_ntf_entry,
        stop_loss=_ntf_stop,
    )
