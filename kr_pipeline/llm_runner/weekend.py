"""주말 (5) analyze_chart_v3 batch.

결정론 필터 (minervini_pass) 통과 종목 전체를 LLM 분석.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
from psycopg import Connection

from api.services.freeze_store import save_freeze
from api.services.zip_builder import build_analysis_zip
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, ClaudeCLIError, UsageLimitError
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


def _write_heartbeat(dsn, run_id, progress: dict):
    payload = json.dumps({"weekend_progress": progress, "heartbeat_at": datetime.now(timezone.utc).isoformat()})
    hb = psycopg.connect(dsn)
    try:
        with hb.cursor() as cur:
            cur.execute("UPDATE pipeline_runs SET details = %s::jsonb WHERE id = %s", (payload, run_id))
        hb.commit()
    finally:
        hb.close()


_TRANSIENT_EXC = (subprocess.TimeoutExpired, ClaudeCLIError)


def _process_one_worker(dsn, symbol, market, *, dry_run, as_of, max_retries=2, abort=None):
    """자기 커넥션으로 한 종목 처리. 일시오류만 재시도. dict 반환.

    연결 실패도 종목별 실패로 흡수 — 한 워커의 connect 실패가 fut.result() 로 전파돼
    배치 전체를 중단시키지 않도록(이 기능의 resilience 목표).
    abort (threading.Event): 사용량 제한 등으로 배치 중단 결정 시 set —
    이후 시작되는 워커는 LLM 호출 없이 즉시 건너뜀(신규 헛호출 0 보장).
    """
    from api.services.integrity_guard import DataIntegrityError
    if abort is not None and abort.is_set():
        return {"status": "aborted", "symbol": symbol, "attempts": 0}
    try:
        wconn = psycopg.connect(dsn)
    except Exception as e:
        return {"status": "fail", "symbol": symbol, "attempts": 0, "error": f"connect failed: {e}"}
    last_err = None
    attempts = 0
    try:
        while attempts <= max_retries:
            attempts += 1
            try:
                _process_one(wconn, symbol, market, dry_run=dry_run, as_of=as_of)
                wconn.commit()
                return {"status": "ok", "symbol": symbol, "attempts": attempts}
            except DataIntegrityError as e:
                wconn.rollback()
                return {"status": "integrity", "symbol": symbol, "attempts": attempts,
                        "detail": {"symbol": symbol, "date": e.on_date.isoformat(), "column": e.column,
                                   "p_value": e.p_value, "i_value": e.i_value, "ratio": e.ratio}}
            except UsageLimitError as e:
                # 5시간 사용량 제한 — 재시도 무의미, 배치 전체 중단 신호.
                # abort 를 워커 안에서 set: 메인 스레드가 결과를 받기 전에
                # 다음 종목이 시작되는 레이스를 막는다 (신규 헛호출 0).
                wconn.rollback()
                if abort is not None:
                    abort.set()
                return {"status": "usage_limit", "symbol": symbol, "attempts": attempts, "error": str(e)}
            except _TRANSIENT_EXC as e:
                wconn.rollback(); last_err = str(e)
                if attempts <= max_retries:
                    time.sleep(min(2 * attempts, 5))
            except Exception as e:
                wconn.rollback()
                return {"status": "fail", "symbol": symbol, "attempts": attempts, "error": str(e)}
        return {"status": "fail", "symbol": symbol, "attempts": attempts,
                "error": f"transient retries exhausted: {last_err}"}
    finally:
        wconn.close()


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

    if ticker:
        candidates = [{"symbol": ticker, "market": "KOSPI"}]
    else:
        candidates = get_qualifying_tickers(conn, as_of=as_of)

    if limit:
        candidates = candidates[:limit]

    log.info("weekend batch: %d candidates as_of=%s dry_run=%s",
             len(candidates), as_of, dry_run)

    concurrency = concurrency or int(os.environ.get("WEEKEND_CONCURRENCY", "4"))
    processed = 0
    failed_tickers: list[dict] = []
    integrity_skipped: list[dict] = []
    # 워커별 독립 커넥션 재연결용 DSN. 주의: conn.info.dsn 은 비밀번호를 포함하지 않는다 —
    # 이 프로젝트 DB 는 passwordless localhost(DATABASE_URL=postgresql://localhost/...) 라 OK.
    # 비밀번호 인증 DB 로 옮기면 PGPASSWORD/.pgpass 또는 database_url 직접 전달이 필요.
    dsn = conn.info.dsn

    workers = max(1, min(concurrency, len(candidates)))

    # kill -9/크래시 박제 정리 (현재 실행 제외)
    if run_id is not None:
        try:
            reap_stale_weekend_runs(conn, current_run_id=run_id)
            conn.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("reaper failed (continuing): %s", e)
            conn.rollback()

    total = len(candidates)
    prog = {"done": 0, "total": total, "in_flight": 0, "failed": 0}
    prog_lock = threading.Lock()
    stop = threading.Event()

    def _heartbeat_loop():
        while True:
            with prog_lock:
                snap = dict(prog)
            try:
                _write_heartbeat(dsn, run_id, snap)
            except Exception as e:  # noqa: BLE001
                log.warning("heartbeat write failed: %s", e)
            log.info("weekend: %d/%d done, in-flight %d, failed %d",
                     snap["done"], snap["total"], snap["in_flight"], snap["failed"])
            if stop.wait(30):   # 30초 주기, stop 시 즉시 탈출
                return

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    if run_id is not None:
        with prog_lock:
            prog["in_flight"] = min(workers, total)
        _write_heartbeat(dsn, run_id, dict(prog))   # 초기 즉시 1회(첫 틱 전 kill 도 stale 추적 가능)
        hb_thread.start()
    usage_limit_error: str | None = None
    abort = threading.Event()
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_process_one_worker, dsn, c["symbol"], c["market"],
                              dry_run=dry_run, as_of=as_of, abort=abort): c["symbol"] for c in candidates}
            for fut in as_completed(futs):
                r = fut.result()
                if r["status"] == "ok":
                    processed += 1
                elif r["status"] == "integrity":
                    integrity_skipped.append(r["detail"])
                elif r["status"] == "aborted":
                    pass  # 중단 결정 후 시작된 워커 — 호출 없이 건너뜀 (집계 제외)
                elif r["status"] == "usage_limit":
                    # 사용량 제한 — 대기열 취소 후 즉시 중단 (남은 후보 헛호출 방지).
                    usage_limit_error = r.get("error", "usage limit")
                    log.warning("usage limit hit at %s — aborting batch (processed=%d/%d)",
                                r["symbol"], processed, total)
                    ex.shutdown(wait=False, cancel_futures=True)
                    break
                else:
                    failed_tickers.append({"symbol": r["symbol"], "error": r.get("error", ""), "attempts": r["attempts"]})
                with prog_lock:
                    prog["done"] += 1
                    prog["failed"] = len(failed_tickers)
                    prog["in_flight"] = min(workers, total - prog["done"])  # 남은 미완료 중 동시 한도(근사·표시용)
    finally:
        stop.set()
        if run_id is not None and hb_thread.is_alive():
            hb_thread.join(timeout=5)

    if usage_limit_error is not None:
        # 예외 전파 → run_tracking 이 failed 로 기록 → 같은 as_of 재실행이
        # 중복 가드(success+as_of)에 막히지 않는다. 기적재분은 각 워커가
        # 이미 commit 했으므로 보존된다.
        raise UsageLimitError(
            f"usage limit — batch aborted: processed={processed}/{total}, "
            f"reason={usage_limit_error}"
        )

    log.info("weekend batch done: processed=%d failed=%d integrity_skipped=%d",
             processed, len(failed_tickers), len(integrity_skipped))
    return {
        "processed": processed,
        "candidates": len(candidates),
        "failures": len(failed_tickers),
        "failed_tickers": failed_tickers,           # [{symbol,error,attempts}]
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

    # ZIP 빌드 (dry-run 도 가짜 bytes 받음).
    # include_prior_analysis=False: 신규 분석에 직전 분류가 첨부되면 LLM 이
    # 과거 판정에 anchoring 됨. on_date=as_of: --date 과거 재실행 look-ahead 방지.
    zip_bytes = build_analysis_zip(conn, symbol, on_date=as_of, include_prior_analysis=False)

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
