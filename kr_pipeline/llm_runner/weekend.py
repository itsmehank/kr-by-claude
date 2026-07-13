"""주말 (5) analyze_chart_v3 batch.

결정론 필터 (minervini_pass) 통과 종목 전체를 LLM 분석.
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.freeze_store import save_freeze
from api.services.inline_builder import build_analysis_inline
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError
from kr_pipeline.llm_runner.load import get_qualifying_tickers
from kr_pipeline.llm_runner.parallel import run_parallel_batch
from kr_pipeline.llm_runner.store import insert_classification


log = logging.getLogger("kr_pipeline.llm_runner.weekend")


def reap_stale_weekend_runs(conn, *, current_run_id, stale_seconds: int = 90) -> int:
    """오래 멈춰있는 'llm_weekend' running 행을 'failed' 로 정리(kill -9/크래시 박제 복구).

    age 기준 = COALESCE(heartbeat_at, started_at). heartbeat 가 아직 없는 행(예: weekend.run
    전 disqualify 스윕 구간에서 SIGKILL 당한 run)도 started_at 이 오래되면 정리된다.
    현재 실행(current_run_id)은 제외 → 정상 진행 중인 run 오정리 방지. 정리한 행 수 반환.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pipeline_runs
               SET status = 'failed', finished_at = NOW(),
                   error = 'stale heartbeat — process likely killed'
             WHERE pipeline = 'llm_weekend' AND status = 'running'
               AND id <> %s
               AND COALESCE((details ->> 'heartbeat_at')::timestamptz, started_at)
                     < NOW() - make_interval(secs => %s)
            """,
            (current_run_id if current_run_id is not None else -1, stale_seconds),
        )
        return cur.rowcount


def _already_classified(conn: Connection, as_of: date) -> set[str]:
    """같은 analyzed_for_date 의 *weekend* 기적재 종목 — 재실행 시 후보 제외 (이어하기).

    사용량 제한/중단으로 잘린 배치를 재실행할 때 기적재분의 중복 LLM 호출을
    막는다 (backfill._already_backfilled 와 동일 패턴).

    source='weekend' 한정 이유: 평일 daily_delta 분류는 그 주 주봉이 집계되기
    *전*(주봉은 토 03:00 data-weekly 가 생성)의 분석이라, 같은 as_of(금요일)라도
    토요일 weekend 는 완성된 주봉을 포함한 다른 입력을 본다 — daily_delta 행이
    weekend 재분석(갱신)을 막으면 주봉-불완전 분석이 그 주의 최신으로 박제된다.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol FROM weekly_classification "
            " WHERE analyzed_for_date = %s AND source = 'weekend'",
            (as_of,),
        )
        return {r[0] for r in cur.fetchall()}


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
    ticker: str | None = None,
    concurrency: int | None = None,
    run_id: int | None = None,
) -> dict:
    """주말 (5) batch 실행 (ThreadPoolExecutor 병렬, 일시오류 재시도, run_id 있으면 하트비트).

    Returns: {"processed": N, "candidates": N, "failures": N,
              "failed_tickers": [{"symbol","error","attempts"}], "integrity_skipped": [...]}
    """
    if as_of is None:
        as_of = date.today()

    skipped_existing = 0
    if ticker:
        candidates = [{"symbol": ticker, "market": "KOSPI"}]
    else:
        candidates = get_qualifying_tickers(conn, as_of=as_of)
        # 이어하기: 같은 analyzed_for_date 기적재 종목 제외 (단일 종목 디버그는
        # 의도적 재분석이므로 제외하지 않음)
        done = _already_classified(conn, as_of)
        if done:
            before = len(candidates)
            candidates = [c for c in candidates if c["symbol"] not in done]
            skipped_existing = before - len(candidates)
            if skipped_existing:
                log.info("weekend resume: %d already classified for %s — skipped",
                         skipped_existing, as_of)

    if limit:
        candidates = candidates[:limit]

    log.info("weekend batch: %d candidates as_of=%s dry_run=%s (skipped_existing=%d)",
             len(candidates), as_of, dry_run, skipped_existing)

    concurrency = concurrency or int(os.environ.get("WEEKEND_CONCURRENCY", "4"))

    # 워커별 독립 커넥션 재연결용 DSN. conn.info.dsn 은 비밀번호 미포함 — passwordless localhost 라 OK.
    dsn = conn.info.dsn

    # kill -9/크래시 박제 정리 (현재 실행 제외)
    if run_id is not None:
        try:
            reap_stale_weekend_runs(conn, current_run_id=run_id)
            conn.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("reaper failed (continuing): %s", e)
            conn.rollback()

    r = run_parallel_batch(
        dsn=dsn, candidates=candidates, process_fn=_process_one,
        concurrency=concurrency, dry_run=dry_run, as_of=as_of, run_id=run_id,
    )

    if r["usage_limited"]:
        # 예외 전파 → run_tracking 이 failed 기록 → 같은 as_of 재실행이 중복 가드에 안 막힘.
        # 기적재분은 각 워커가 이미 commit 했으므로 보존된다.
        raise UsageLimitError(
            f"usage limit — batch aborted: processed={r['processed']}/{len(candidates)}, "
            f"reason={r['usage_error']}"
        )

    log.info("weekend batch done: processed=%d failed=%d integrity_skipped=%d",
             r["processed"], len(r["failed_tickers"]), len(r["integrity_skipped"]))
    return {
        "processed": r["processed"],
        "candidates": len(candidates),
        "skipped_existing": skipped_existing,
        "failures": len(r["failed_tickers"]),
        "failed_tickers": r["failed_tickers"],
        "integrity_skipped": r["integrity_skipped"],
    }


def _process_one(
    conn: Connection,
    symbol: str,
    market: str,
    *,
    dry_run: bool,
    as_of: date,
) -> None:
    """단일 종목 (5) 호출 + INSERT."""
    started = datetime.now(timezone.utc)

    # 인라인 입력 빌드 (ZIP→텍스트 인라인 + 차트 PNG). dry-run 도 실제 빌드.
    # 신규 분석은 직전 분류를 첨부하지 않음(anchoring 방지) — inline_builder 는
    # 항상 fresh. 대가 = 같은 베이스도 pivot 이 주 단위 재판독됨(#1) —
    # 트레이드오프 상세·관측 로그: docs/pivot-reanalysis-tradeoff.md.
    # on_date=as_of: --date 과거 재실행 look-ahead 방지.
    # freeze_bytes = 감사·재현용 ZIP(inline_input.md + 차트 2장).
    inline_text, png_paths, freeze_bytes = build_analysis_inline(conn, symbol, on_date=as_of)
    png_dir = str(Path(png_paths[0]).parent)
    llm_io: dict = {}
    try:
        result = call_claude(
            prompt_file="analyze_chart_v3.md",
            attachments=png_paths,
            payload_inline=inline_text,
            dry_run=dry_run,
            meta_out=llm_io,
        )
    finally:
        shutil.rmtree(png_dir, ignore_errors=True)

    finished = datetime.now(timezone.utc)
    duration_s = (finished - started).total_seconds()

    if dry_run:
        log.info("dry-run: skipping DB insert for %s (mock result %s)",
                 symbol, result.get("classification"))
        # dry_run 에서도 freeze 저장 — classification_id=None (분류 row 없음)
        save_freeze(
            conn,
            artifact_bytes=freeze_bytes,
            content_type="application/zip",
            ticker=symbol,
            stage="weekend",
            classification_id=None,
        )
        return

    insert_classification(
        conn,
        symbol=symbol,
        classified_at=finished,
        market=market,
        result=result,
        source="weekend",
        llm_meta={
            "duration_s": duration_s,
            "input_tokens": llm_io.get("input_tokens"),
            "output_tokens": llm_io.get("output_tokens"),
            "model": llm_io.get("model"),
        },
        analyzed_for_date=as_of,
    )

    # 분류 row 저장 후 freeze — fail-soft, 반환값 무시
    # weekly_classification PK 는 composite (symbol, classified_at), BIGINT id 없어 classification_id=None
    save_freeze(
        conn,
        artifact_bytes=freeze_bytes,
        content_type="application/zip",
        ticker=symbol,
        stage="weekend",
        classification_id=None,
    )
