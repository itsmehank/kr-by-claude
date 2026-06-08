"""주말 (5) analyze_chart_v3 batch.

결정론 필터 (minervini_pass) 통과 종목 전체를 LLM 분석.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.freeze_store import save_freeze
from api.services.zip_builder import build_analysis_zip
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, ClaudeCLIError
from kr_pipeline.llm_runner.load import get_qualifying_tickers
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


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
    ticker: str | None = None,
) -> dict:
    """주말 (5) batch 실행.

    Returns: {"processed": N, "failures": N, "tickers": [...]}
    """
    if as_of is None:
        as_of = date.today()

    if ticker:
        candidates = [{"symbol": ticker, "market": "KOSPI"}]
    else:
        candidates = get_qualifying_tickers(conn, as_of=as_of)

    if limit:
        candidates = candidates[:limit]

    log.info("weekend batch: %d candidates as_of=%s dry_run=%s",
             len(candidates), as_of, dry_run)

    processed = 0
    failures: list[tuple[str, str]] = []
    failed_tickers = []
    integrity_skipped: list[dict] = []

    from api.services.integrity_guard import DataIntegrityError

    for c in candidates:
        symbol = c["symbol"]
        market = c["market"]
        try:
            _process_one(conn, symbol, market, dry_run=dry_run, as_of=as_of)
            processed += 1
            conn.commit()
        except DataIntegrityError as e:
            log.warning("[INTEGRITY GUARD] %s skipped: %s", symbol, e)
            integrity_skipped.append({
                "symbol": symbol,
                "date": e.on_date.isoformat(),
                "column": e.column,
                "p_value": e.p_value,
                "i_value": e.i_value,
                "ratio": e.ratio,
            })
            conn.rollback()
        except Exception as e:
            log.warning("ticker %s failed: %s", symbol, e)
            failures.append((symbol, str(e)))
            failed_tickers.append(symbol)
            conn.rollback()

    # End-of-run retry 1회
    retry_failures = []
    for symbol in failed_tickers:
        try:
            market = next(c["market"] for c in candidates if c["symbol"] == symbol)
            _process_one(conn, symbol, market, dry_run=dry_run, as_of=as_of)
            processed += 1
            conn.commit()
        except DataIntegrityError as e:
            log.warning("[INTEGRITY GUARD] retry: %s skipped: %s", symbol, e)
            integrity_skipped.append({
                "symbol": symbol,
                "date": e.on_date.isoformat(),
                "column": e.column,
                "p_value": e.p_value,
                "i_value": e.i_value,
                "ratio": e.ratio,
            })
            conn.rollback()
        except Exception as e:
            retry_failures.append((symbol, str(e)))
            conn.rollback()

    if integrity_skipped:
        log.warning("[INTEGRITY GUARD] %d tickers skipped due to data integrity issues",
                    len(integrity_skipped))

    log.info("weekend batch done: processed=%d retry_failures=%d integrity_skipped=%d",
             processed, len(retry_failures), len(integrity_skipped))

    return {
        "processed": processed,
        "candidates": len(candidates),
        "failures": len(retry_failures),
        "failed_tickers": [t for t, _ in retry_failures],
        "integrity_skipped": integrity_skipped,
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

    # ZIP 빌드 (dry-run 도 가짜 bytes 받음)
    zip_bytes = build_analysis_zip(conn, symbol)

    # ZIP 을 임시 파일로 저장 (Claude CLI attach 용)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(zip_bytes)
        zip_path = f.name

    try:
        result = call_claude(
            prompt_file="analyze_chart_v3.md",
            attachments=[zip_path],
            dry_run=dry_run,
        )
    finally:
        Path(zip_path).unlink(missing_ok=True)

    finished = datetime.now(timezone.utc)
    duration_s = (finished - started).total_seconds()

    if dry_run:
        log.info("dry-run: skipping DB insert for %s (mock result %s)",
                 symbol, result.get("classification"))
        # dry_run 에서도 freeze 저장 — classification_id=None (분류 row 없음)
        save_freeze(
            conn,
            artifact_bytes=zip_bytes,
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
            "input_tokens": None,
            "output_tokens": None,
        },
        analyzed_for_date=as_of,
    )

    # 분류 row 저장 후 freeze — fail-soft, 반환값 무시
    # weekly_classification PK 는 composite (symbol, classified_at), BIGINT id 없어 classification_id=None
    save_freeze(
        conn,
        artifact_bytes=zip_bytes,
        content_type="application/zip",
        ticker=symbol,
        stage="weekend",
        classification_id=None,
    )
