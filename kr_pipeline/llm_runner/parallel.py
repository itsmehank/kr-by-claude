"""LLM 배치 병렬 실행 공용 헬퍼 — weekend / backfill 공유.

워커마다 자기 DB 커넥션을 열고, 일시오류(TimeoutExpired)만 재시도하며,
사용량 한도(UsageLimitError)·인터럽트는 abort 로 남은 호출을 차단한다.
heartbeat 는 run_id 가 주어질 때만(weekend) 30초 주기로 구동.
각 모드의 '종목 1개 처리'는 process_fn(conn, symbol, market, *, dry_run, as_of) 로 주입받는다.
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import psycopg

from kr_pipeline.llm_runner.llm.claude_cli import UsageLimitError

log = logging.getLogger("kr_pipeline.llm_runner.parallel")

# 워커 재시도 대상은 TimeoutExpired 만 — CLI 내부 4회 재시도를 우회하는 유일 경로라
# 워커가 보완. ClaudeCLIError 는 내부 4회를 이미 소진한 최종 실패라 재시도 제외.
_TRANSIENT_EXC = (subprocess.TimeoutExpired,)


def _write_heartbeat(dsn, run_id, progress: dict):
    # 키 "weekend_progress" 는 web/src/lib/runDetails.ts 와 test 가 소비 — 유지 필수.
    payload = json.dumps({"weekend_progress": progress,
                          "heartbeat_at": datetime.now(timezone.utc).isoformat()})
    hb = psycopg.connect(dsn)
    try:
        with hb.cursor() as cur:
            cur.execute("UPDATE pipeline_runs SET details = %s::jsonb WHERE id = %s", (payload, run_id))
        hb.commit()
    finally:
        hb.close()


def _process_one_worker(dsn, symbol, market, process_fn, *, dry_run, as_of, max_retries=2, abort=None):
    """자기 커넥션으로 한 종목 처리. 일시오류만 재시도. dict 반환.

    연결 실패도 종목별 실패로 흡수 — 한 워커의 connect 실패가 배치 전체를 중단시키지 않게.
    abort(threading.Event): 사용량 제한/인터럽트 시 set → 이후 시작 워커는 호출 없이 즉시 건너뜀.
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
                process_fn(wconn, symbol, market, dry_run=dry_run, as_of=as_of)
                wconn.commit()
                return {"status": "ok", "symbol": symbol, "attempts": attempts}
            except DataIntegrityError as e:
                wconn.rollback()
                return {"status": "integrity", "symbol": symbol, "attempts": attempts,
                        "detail": {"symbol": symbol, "date": e.on_date.isoformat(), "column": e.column,
                                   "p_value": e.p_value, "i_value": e.i_value, "ratio": e.ratio}}
            except UsageLimitError as e:
                # 5시간 사용량 제한 — 재시도 무의미, 배치 전체 중단 신호. 워커 안에서 abort set:
                # 메인 스레드가 결과 받기 전 다음 종목이 시작되는 레이스 차단(신규 헛호출 0).
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
            except BaseException:
                # KeyboardInterrupt(SIGTERM 전환)/SystemExit — abort set 후 전파.
                if abort is not None:
                    abort.set()
                raise
        return {"status": "fail", "symbol": symbol, "attempts": attempts,
                "error": f"transient retries exhausted: {last_err}"}
    finally:
        wconn.close()


def run_parallel_batch(*, dsn, candidates, process_fn, concurrency, dry_run, as_of,
                       run_id=None, abort=None):
    """후보 리스트를 ThreadPoolExecutor 로 병렬 처리. 집계 dict 반환(예외는 caller 가 판단).

    Returns: {"processed", "failed_tickers", "integrity_skipped", "usage_limited", "usage_error"}
    """
    total = len(candidates)
    if total == 0:
        return {"processed": 0, "failed_tickers": [], "integrity_skipped": [],
                "usage_limited": False, "usage_error": None}

    workers = max(1, min(concurrency, total))
    if abort is None:
        abort = threading.Event()

    processed = 0
    failed_tickers: list[dict] = []
    integrity_skipped: list[dict] = []
    usage_limited = False
    usage_error = None

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
            log.info("batch: %d/%d done, in-flight %d, failed %d",
                     snap["done"], snap["total"], snap["in_flight"], snap["failed"])
            if stop.wait(30):
                return

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    if run_id is not None:
        with prog_lock:
            prog["in_flight"] = min(workers, total)
        _write_heartbeat(dsn, run_id, dict(prog))   # 초기 즉시 1회
        hb_thread.start()

    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_process_one_worker, dsn, c["symbol"], c["market"], process_fn,
                              dry_run=dry_run, as_of=as_of, abort=abort): c["symbol"] for c in candidates}
            try:
                for fut in as_completed(futs):
                    r = fut.result()
                    if r["status"] == "ok":
                        processed += 1
                    elif r["status"] == "integrity":
                        integrity_skipped.append(r["detail"])
                    elif r["status"] == "aborted":
                        pass
                    elif r["status"] == "usage_limit":
                        usage_limited = True
                        usage_error = r.get("error", "usage limit")
                        log.warning("usage limit hit at %s — aborting batch (processed=%d/%d)",
                                    r["symbol"], processed, total)
                        ex.shutdown(wait=False, cancel_futures=True)
                        break
                    else:
                        failed_tickers.append({"symbol": r["symbol"], "error": r.get("error", ""),
                                               "attempts": r["attempts"]})
                    with prog_lock:
                        prog["done"] += 1
                        prog["failed"] = len(failed_tickers)
                        prog["in_flight"] = min(workers, total - prog["done"])
            except (KeyboardInterrupt, SystemExit):
                abort.set()
                ex.shutdown(wait=False, cancel_futures=True)
                raise
    finally:
        stop.set()
        if run_id is not None and hb_thread.is_alive():
            hb_thread.join(timeout=5)

    return {"processed": processed, "failed_tickers": failed_tickers,
            "integrity_skipped": integrity_skipped,
            "usage_limited": usage_limited, "usage_error": usage_error}
