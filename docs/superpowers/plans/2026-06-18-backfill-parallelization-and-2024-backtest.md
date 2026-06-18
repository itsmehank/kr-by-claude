# 백필 병렬화 + 2024 주말분류 백테스트 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** weekend의 검증된 병렬 실행 로직을 공용 모듈로 추출해 backfill도 병렬 실행하게 만들고, 그 병렬 백필로 2024년 유형별 대표 8종목을 주 단위 분류해 forward-return과 대조 평가한다.

**Architecture:** weekend.py의 워커(`_process_one_worker`) + 실행루프 + heartbeat를 신규 `kr_pipeline/llm_runner/parallel.py`의 `run_parallel_batch()`로 옮긴다. 각 모드의 "종목 1개 처리"는 `process_fn`으로 주입한다(weekend=freeze 저장, backfill=미저장). weekend는 reaper/UsageLimitError raise만 자기 쪽에 남기고, backfill은 토요일 루프 + 단일 abort + 반환 dict 매핑을 자기 쪽에서 처리한다.

**Tech Stack:** Python 3 (psycopg, ThreadPoolExecutor), pytest/pytest-mock, PostgreSQL, Claude CLI.

## Global Constraints

- 커밋 메시지에 `Co-Authored-By: Claude` 류 트레일러 금지(전역 규칙).
- 테스트 회귀 판정은 base↔HEAD 실패 수 비교. 사전 baseline 실패 ~31개 존재(늘리지 말 것).
- `thresholds.py` 상수/소비처는 본 작업 비대상 → threshold-change-checklist 트리거 안 됨.
- DB: `DATABASE_URL=postgresql://localhost/kr_pipeline`, 테스트 `TEST_DATABASE_URL=postgresql://localhost/kr_test`(passwordless localhost).
- weekend 동작 **변화 0** 목표. 기존 `tests/test_llm_weekend.py` 11개 전부 green 유지가 동작 보존 증명.
- 작업 시작 시 main에서 작업 브랜치 분기(`git switch -c feat/backfill-parallelization`).

---

## File Structure

- **Create** `kr_pipeline/llm_runner/parallel.py` — 공용 `run_parallel_batch()` + 워커 + heartbeat.
- **Modify** `kr_pipeline/llm_runner/weekend.py` — 워커/heartbeat 제거, `run_parallel_batch` 호출.
- **Modify** `kr_pipeline/llm_runner/backfill.py` — `run_parallel_batch` 사용, 단일 abort, 반환 매핑, 토요일별 main commit, `--concurrency`.
- **Modify** `kr_pipeline/llm_runner/__main__.py` — `--concurrency` 인자 추가·전달.
- **Modify** `tests/test_llm_weekend.py` — connect-failure 테스트 패치 대상을 `parallel`로(동작 동일, 위치만 이동).
- **Modify** `tests/test_llm_backfill.py` — 병렬 케이스 추가(재시도/connect 흡수/integrity skip/반환 키).
- **Create** `scripts/backtest_2024_analysis.sql` — classification_backfill × forward-return 분석 쿼리.
- **Create** `docs/superpowers/backtest-2024-results.md` — 실행 결과·평가(Phase 2 산출물).

---

## Task 1: 공용 `parallel.py` 추출 + weekend 전환

**Files:**
- Create: `kr_pipeline/llm_runner/parallel.py`
- Modify: `kr_pipeline/llm_runner/weekend.py`
- Modify: `tests/test_llm_weekend.py` (connect-failure 패치 대상)
- Test: `tests/test_llm_weekend.py` (전체, 특성 테스트)

**Interfaces:**
- Produces: `run_parallel_batch(*, dsn: str, candidates: list[dict], process_fn, concurrency: int, dry_run: bool, as_of: date, run_id: int | None = None, abort: threading.Event | None = None) -> dict`
  반환 dict 키: `processed:int, failed_tickers:list[dict{symbol,error,attempts}], integrity_skipped:list[dict], usage_limited:bool, usage_error:str|None`.
  `process_fn(conn, symbol, market, *, dry_run, as_of) -> None` 시그니처를 호출.
- Consumes: `kr_pipeline.llm_runner.llm.claude_cli.UsageLimitError`, `api.services.integrity_guard.DataIntegrityError`.

- [ ] **Step 1: 작업 전 baseline green 확인**

Run: `uv run pytest tests/test_llm_weekend.py tests/test_llm_backfill.py -q`
Expected: PASS (weekend 11개 + backfill 기존 케이스 모두 green). 실패가 있으면 그 목록을 기록(이후 회귀와 구분).

- [ ] **Step 2: `parallel.py` 생성 (weekend에서 verbatim 이식 + process_fn 주입)**

Create `kr_pipeline/llm_runner/parallel.py`:

```python
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
```

- [ ] **Step 3: weekend.py에서 이식된 코드 제거 + `run_parallel_batch` 호출로 교체**

`kr_pipeline/llm_runner/weekend.py` 수정:

(a) 상단 import를 아래로 교체(이식으로 불필요해진 `json/subprocess/threading/time/ThreadPoolExecutor/psycopg` 제거, `run_parallel_batch` 추가). `_write_heartbeat`, `_process_one_worker`, `_TRANSIENT_EXC` 정의는 **삭제**(parallel.py로 이동):

```python
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
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, ClaudeCLIError, UsageLimitError
from kr_pipeline.llm_runner.load import get_qualifying_tickers
from kr_pipeline.llm_runner.parallel import run_parallel_batch
from kr_pipeline.llm_runner.store import insert_classification


log = logging.getLogger("kr_pipeline.llm_runner.weekend")
```

(주의: `reap_stale_weekend_runs`, `_already_classified`, `_process_one` 정의는 그대로 유지. `ClaudeCLIError`/`call_claude`는 `_process_one`이 사용하므로 import 유지.)

(b) `run()` 본문에서 `concurrency` 산출 이후 ~ `return` 까지(현재의 ThreadPoolExecutor 블록 전체)를 아래로 교체:

```python
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
```

- [ ] **Step 4: connect-failure 테스트의 패치 대상을 parallel로 이동**

`tests/test_llm_weekend.py` 의 `test_weekend_worker_connect_failure_does_not_abort` 에서
`mocker.patch.object(wk.psycopg, "connect", ...)` 한 줄을 아래로 교체(워커가 parallel.py로
이동했으므로 패치 위치를 코드 위치에 맞춤 — 동작은 동일):

```python
    import kr_pipeline.llm_runner.parallel as parallel
    mocker.patch.object(parallel.psycopg, "connect", side_effect=OSError("no conn"))
```

- [ ] **Step 5: weekend 전체 테스트 green 재확인(특성 테스트 = 동작 보존 증명)**

Run: `uv run pytest tests/test_llm_weekend.py -q`
Expected: PASS (11개 전부). 특히 `test_weekend_parallel_aggregates_and_retries`,
`test_weekend_aborts_batch_on_usage_limit`, `test_weekend_writes_heartbeat_progress`,
`test_weekend_worker_connect_failure_does_not_abort`, `test_weekend_interrupt_cancels_queued_work`.

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/llm_runner/parallel.py kr_pipeline/llm_runner/weekend.py tests/test_llm_weekend.py
git commit -m "refactor(llm_runner): 병렬 실행 로직 parallel.py 공용 헬퍼로 추출 — weekend 전환(동작 불변)"
```

---

## Task 2: backfill을 `run_parallel_batch` 사용으로 전환

**Files:**
- Modify: `kr_pipeline/llm_runner/backfill.py`
- Test: `tests/test_llm_backfill.py` (기존 케이스 green 유지)

**Interfaces:**
- Consumes: `run_parallel_batch` (Task 1).
- Produces: `backfill.run(conn, *, start, end, tickers=None, dry_run=False, limit=None, concurrency=None) -> dict`
  반환 키 유지: `weeks, processed, skipped_existing, failures, failed(list[[symbol,str(as_of),err]]), start, end` + 신규 additive `integrity_skipped`.

- [ ] **Step 1: backfill.py import 추가 + run() 교체**

`kr_pipeline/llm_runner/backfill.py` 상단 import에 추가:

```python
import os
import threading
from kr_pipeline.llm_runner.parallel import run_parallel_batch
```

`run()` 함수 전체를 아래로 교체(`_enumerate_saturdays`, `_already_backfilled`, `_process_one` 정의는 유지):

```python
def run(conn: Connection, *, start: date, end: date, tickers: list[str] | None = None,
        dry_run: bool = False, limit: int | None = None, concurrency: int | None = None) -> dict:
    """기간 × 매주 토요일 백필(병렬). 토요일마다 그 주 minervini 통과 종목(또는 지정 종목)을 분류."""
    saturdays = _enumerate_saturdays(start, end)
    concurrency = concurrency or int(os.environ.get("BACKFILL_CONCURRENCY", "4"))
    agg = {
        "weeks": 0,
        "processed": 0,
        "skipped_existing": 0,
        "failures": 0,
        "failed": [],
        "integrity_skipped": [],
        "start": str(start),
        "end": str(end),
    }
    dsn = conn.info.dsn
    abort = threading.Event()   # 토요일을 가로지르는 단일 abort — 사용량 한도 시 전체 중단

    for as_of in saturdays:
        if abort.is_set():
            break
        candidates = get_qualifying_tickers(conn, as_of=as_of, tickers=tickers)
        done = _already_backfilled(conn, as_of)
        skipped = [c for c in candidates if c["symbol"] in done]
        candidates = [c for c in candidates if c["symbol"] not in done]
        if limit:
            candidates = candidates[:limit]

        log.info("backfill week=%s: %d candidate(s) (done %d)", as_of, len(candidates), len(done))

        r = run_parallel_batch(
            dsn=dsn, candidates=candidates, process_fn=_process_one,
            concurrency=concurrency, dry_run=dry_run, as_of=as_of, run_id=None, abort=abort,
        )
        agg["processed"] += r["processed"]
        for ft in r["failed_tickers"]:
            agg["failed"].append([ft["symbol"], str(as_of), ft.get("error", "")])
        agg["failures"] += len(r["failed_tickers"])
        agg["integrity_skipped"].extend(r["integrity_skipped"])
        agg["skipped_existing"] += len(skipped)
        agg["weeks"] += 1
        # 토요일별 main 커넥션 스냅샷 해제(읽기 트랜잭션 정리) — 다음 토요일 _already_backfilled 가
        # 워커 commit 을 최신으로 보게 함(READ COMMITTED 라 정합하나, 긴 트랜잭션 위생).
        conn.commit()

        if r["usage_limited"]:
            log.warning("backfill usage limit at %s — aborting (processed=%d)", as_of, agg["processed"])
            raise UsageLimitError(
                f"usage limit — backfill aborted: processed={agg['processed']}, reason={r['usage_error']}"
            )

    return agg
```

(주의: `from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError` import가 이미 backfill.py 상단에 있음 — 유지. `_process_one`은 freeze 미저장으로 그대로.)

- [ ] **Step 2: 기존 backfill 테스트 green 재확인**

Run: `uv run pytest tests/test_llm_backfill.py -q`
Expected: PASS. 특히 `test_backfill_run_multi_week_with_tickers`(weeks=2/processed=1),
`test_backfill_aborts_on_usage_limit`(calls==1, UsageLimitError),
`test_backfill_resume_after_usage_limit`(stored=[6/7,14]),
`test_backfill_run_inserts_and_wires_on_date`(resume skip).

- [ ] **Step 3: 커밋**

```bash
git add kr_pipeline/llm_runner/backfill.py
git commit -m "feat(backfill): 병렬 실행 전환(run_parallel_batch) — 단일 abort·반환키 보존·토요일별 commit"
```

---

## Task 3: backfill 병렬 동작 신규 테스트

**Files:**
- Test: `tests/test_llm_backfill.py` (append)

**Interfaces:**
- Consumes: `backfill.run`, `run_parallel_batch`, `DataIntegrityError`.

- [ ] **Step 1: 4개 테스트 추가 (파일 끝에 append)**

`tests/test_llm_backfill.py` 끝에 추가:

```python
def test_backfill_parallel_aggregates_and_retries(db, monkeypatch):
    """한 토요일 다중 종목 병렬: transient(TimeoutExpired) 1회 재시도 후 성공 집계."""
    import subprocess
    from datetime import date
    import kr_pipeline.llm_runner.backfill as bf

    monkeypatch.setattr(bf, "get_qualifying_tickers",
                        lambda conn, as_of=None, tickers=None: [
                            {"symbol": "PB01", "market": "KOSPI"},
                            {"symbol": "PB02", "market": "KOSPI"}])
    monkeypatch.setattr(bf, "_already_backfilled", lambda conn, as_of: set())
    seen = {}
    def fake_process_one(conn, symbol, market, *, dry_run, as_of):
        seen[symbol] = seen.get(symbol, 0) + 1
        if symbol == "PB02" and seen[symbol] == 1:
            raise subprocess.TimeoutExpired(cmd="claude", timeout=1)  # 1회 일시오류
    monkeypatch.setattr(bf, "_process_one", fake_process_one)

    res = bf.run(db, start=date(2024, 1, 6), end=date(2024, 1, 6),
                 tickers=["PB01", "PB02"], dry_run=True, concurrency=2)
    assert res["processed"] == 2
    assert res["failures"] == 0
    assert seen["PB02"] == 2  # 재시도로 2회 호출


def test_backfill_worker_connect_failure_does_not_abort(db, mocker):
    """워커 connect 실패는 그 종목만 실패 — 배치 전체 중단 안 함."""
    from datetime import date
    import kr_pipeline.llm_runner.backfill as bf
    import kr_pipeline.llm_runner.parallel as parallel

    mocker.patch.object(bf, "get_qualifying_tickers", return_value=[
        {"symbol": "CF01", "market": "KOSPI"}, {"symbol": "CF02", "market": "KOSPI"}])
    mocker.patch.object(bf, "_already_backfilled", return_value=set())
    mocker.patch.object(parallel.psycopg, "connect", side_effect=OSError("no conn"))

    res = bf.run(db, start=date(2024, 1, 6), end=date(2024, 1, 6),
                 tickers=["CF01", "CF02"], dry_run=True, concurrency=2)
    assert res["processed"] == 0
    assert res["failures"] == 2
    assert res["weeks"] == 1


def test_backfill_integrity_error_skips_not_fails(db, monkeypatch):
    """DataIntegrityError 는 integrity_skipped 로 분류(실패 집계 아님)."""
    from datetime import date
    import kr_pipeline.llm_runner.backfill as bf
    from api.services.integrity_guard import DataIntegrityError

    monkeypatch.setattr(bf, "get_qualifying_tickers",
                        lambda conn, as_of=None, tickers=None: [{"symbol": "IG01", "market": "KOSPI"}])
    monkeypatch.setattr(bf, "_already_backfilled", lambda conn, as_of: set())
    def fake_process_one(conn, symbol, market, *, dry_run, as_of):
        raise DataIntegrityError(ticker=symbol, on_date=date(2024, 1, 5),
                                 p_value=100.0, i_value=50.0, column="adj_close")
    monkeypatch.setattr(bf, "_process_one", fake_process_one)

    res = bf.run(db, start=date(2024, 1, 6), end=date(2024, 1, 6),
                 tickers=["IG01"], dry_run=True, concurrency=1)
    assert res["processed"] == 0
    assert res["failures"] == 0
    assert len(res["integrity_skipped"]) == 1
    assert res["integrity_skipped"][0]["symbol"] == "IG01"


def test_backfill_run_returns_expected_keys(db, monkeypatch):
    """반환 dict 키 보존(__main__ / run_tracking 소비 계약)."""
    from datetime import date
    import kr_pipeline.llm_runner.backfill as bf
    monkeypatch.setattr(bf, "get_qualifying_tickers", lambda conn, as_of=None, tickers=None: [])
    monkeypatch.setattr(bf, "_already_backfilled", lambda conn, as_of: set())
    res = bf.run(db, start=date(2024, 1, 6), end=date(2024, 1, 6), tickers=["X"], dry_run=True)
    assert set(res) == {"weeks", "processed", "skipped_existing", "failures",
                        "failed", "integrity_skipped", "start", "end"}
```

- [ ] **Step 2: 신규 테스트 실행**

Run: `uv run pytest tests/test_llm_backfill.py -q -k "parallel or connect_failure or integrity_error or returns_expected_keys"`
Expected: PASS (4개).

- [ ] **Step 3: 커밋**

```bash
git add tests/test_llm_backfill.py
git commit -m "test(backfill): 병렬 동작 케이스 추가 — 재시도·connect 흡수·integrity skip·반환키"
```

---

## Task 4: `--concurrency` CLI 인자 추가

**Files:**
- Modify: `kr_pipeline/llm_runner/__main__.py`
- Test: `tests/test_llm_backfill.py` (append)

**Interfaces:**
- Consumes: `backfill.run(..., concurrency=...)` (Task 2).

- [ ] **Step 1: 실패 테스트 — 비-backfill 모드에서 --concurrency 거부**

`tests/test_llm_backfill.py` 끝에 추가:

```python
def test_concurrency_arg_rejected_for_non_backfill():
    """--concurrency 는 backfill 전용 — 다른 모드와 함께 쓰면 명시적 에러(조용한 무시 방지)."""
    import sys
    import pytest
    from kr_pipeline.llm_runner.__main__ import main
    argv = ["prog", "--mode=weekend", "--concurrency=4"]
    old = sys.argv
    sys.argv = argv
    try:
        with pytest.raises(SystemExit):
            main()
    finally:
        sys.argv = old
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_llm_backfill.py::test_concurrency_arg_rejected_for_non_backfill -q`
Expected: FAIL (아직 `--concurrency` 인자가 없어 argparse가 unrecognized arguments로 종료하거나, 가드 미존재로 통과해버림 → 의도한 SystemExit 경로와 불일치).

- [ ] **Step 3: `__main__.py` 수정**

(a) 인자 추가 — `--force` 추가 줄 다음에:

```python
    parser.add_argument("--concurrency", type=int, help="병렬 워커 수 (backfill 전용). 생략 시 BACKFILL_CONCURRENCY env 또는 4")
```

(b) backfill 전용 가드 — 기존 `--start/--end/--tickers` 가드(`if args.mode != "backfill" and (args.start or args.end or args.tickers):`) 를 아래로 교체:

```python
    if args.mode != "backfill" and (args.start or args.end or args.tickers or args.concurrency):
        parser.error("--start/--end/--tickers/--concurrency is only supported with --mode=backfill.")
```

(c) backfill 호출에 concurrency 전달 — `backfill.run(...)` 호출을:

```python
                result = backfill.run(conn, start=_start, end=_end, tickers=_tickers,
                                      dry_run=args.dry_run, limit=args.limit,
                                      concurrency=args.concurrency)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_llm_backfill.py::test_concurrency_arg_rejected_for_non_backfill -q`
Expected: PASS.

- [ ] **Step 5: 전체 회귀 판정**

Run: `uv run pytest tests/ -q`
Expected: baseline(~31) 대비 실패 수 증가 없음. weekend/backfill 관련 전부 green.

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/llm_runner/__main__.py tests/test_llm_backfill.py
git commit -m "feat(cli): backfill --concurrency 인자 추가(비-backfill 모드 거부 가드 포함)"
```

---

## Task 5: 백테스트 분석 쿼리 + dry-run 사전 점검

**Files:**
- Create: `scripts/backtest_2024_analysis.sql`

- [ ] **Step 1: 분석 쿼리 작성**

Create `scripts/backtest_2024_analysis.sql`:

```sql
-- 2024 백테스트 분석: classification_backfill × forward-return(+4주/+12주)
-- 사용: psql postgresql://localhost/kr_pipeline -f scripts/backtest_2024_analysis.sql
WITH bf AS (
  SELECT symbol, analyzed_for_date AS sat, classification, confidence,
         pattern, watch_reason, risk_flags
  FROM classification_backfill
  WHERE analyzed_for_date BETWEEN '2024-01-06' AND '2024-12-28'
    AND symbol IN ('003230','101930','399720','200470','257720','000320','900340','267260')
),
base AS (
  SELECT b.*,
    (SELECT adj_close FROM daily_prices p
      WHERE p.ticker=b.symbol AND p.date<=b.sat ORDER BY p.date DESC LIMIT 1) AS px0
  FROM bf b
)
SELECT base.symbol, s.name, base.sat, base.classification,
  base.confidence, base.pattern, base.watch_reason, base.risk_flags,
  round((( SELECT adj_close FROM daily_prices p
            WHERE p.ticker=base.symbol AND p.date<=base.sat + 28
            ORDER BY p.date DESC LIMIT 1) / NULLIF(base.px0,0) - 1) * 100, 1) AS fwd_4w_pct,
  round((( SELECT adj_close FROM daily_prices p
            WHERE p.ticker=base.symbol AND p.date<=base.sat + 84
            ORDER BY p.date DESC LIMIT 1) / NULLIF(base.px0,0) - 1) * 100, 1) AS fwd_12w_pct
FROM base JOIN stocks s ON s.ticker=base.symbol
ORDER BY base.symbol, base.sat;
```

- [ ] **Step 2: dry-run 사전 점검(LLM 비용 0, 차트 빌드는 실제 수행)**

Run:
```bash
uv run python -m kr_pipeline.llm_runner --mode=backfill \
  --start=2024-01-06 --end=2024-12-28 --concurrency=4 --dry-run \
  --tickers=003230,101930,399720,200470,257720,000320,900340,267260
```
Expected: 에러 없이 완료. 로그에 토요일별 `candidate(s)` 수가 찍히고(통과 주만), 최종
`DONE backfill: {... "processed": <합계>, "weeks": 51 ...}`. 8종목 합계 통과 ≈ 191회 분의
inline+차트 빌드가 성공(insert는 dry-run이라 생략).

- [ ] **Step 3: 커밋**

```bash
git add scripts/backtest_2024_analysis.sql
git commit -m "feat(backtest): 2024 forward-return 분석 쿼리 + dry-run 점검"
```

---

## Task 6: 백테스트 실행 + 결과 평가 (운영)

**Files:**
- Create: `docs/superpowers/backtest-2024-results.md`

- [ ] **Step 1: 실제 백필 실행 (백그라운드)**

Run (백그라운드 — 순차 아님, 동시 4):
```bash
uv run python -m kr_pipeline.llm_runner --mode=backfill \
  --start=2024-01-06 --end=2024-12-28 --concurrency=4 \
  --tickers=003230,101930,399720,200470,257720,000320,900340,267260
```
중단 시 같은 명령 재실행 = 이어하기(`_already_backfilled` skip). 완료까지 대기.

- [ ] **Step 2: 적재 검증**

Run:
```bash
psql postgresql://localhost/kr_pipeline -c "
SELECT symbol, COUNT(*) AS n, MIN(analyzed_for_date), MAX(analyzed_for_date)
FROM classification_backfill
WHERE analyzed_for_date BETWEEN '2024-01-06' AND '2024-12-28'
  AND symbol IN ('003230','101930','399720','200470','257720','000320','900340','267260')
GROUP BY symbol ORDER BY symbol;"
```
Expected: 8종목, 종목별 건수가 설계의 통과 토요일 수와 근사(삼양식품 24, 인화정공 26, 가온칩스 15, 에이팩트 14, 실리콘투 30, 노루홀딩스 24, 윙입푸드 12, HD현대일렉트릭 46; 실패분만큼 적을 수 있음).

- [ ] **Step 3: forward-return 분석 실행**

Run: `psql postgresql://localhost/kr_pipeline -f scripts/backtest_2024_analysis.sql`
Expected: 종목 × 토요일별 classification/confidence/risk_flags + fwd_4w_pct/fwd_12w_pct 표.

- [ ] **Step 4: 결과 평가 문서 작성**

`docs/superpowers/backtest-2024-results.md` 작성: 종목별 주 단위 타임라인 표 + 유형별
성공 기준(설계 문서 §Phase2 채점 기준) 대비 평가 + 전체 요약. LLM 비결정성 고려 — 정확한
일치가 아니라 패턴으로 판정.

- [ ] **Step 5: 커밋**

```bash
git add docs/superpowers/backtest-2024-results.md
git commit -m "docs(backtest): 2024 주말분류 백테스트 결과·유형별 평가"
```

---

## Self-Review (작성자 점검 결과)

- **Spec 커버리지:** Phase 1(공용 헬퍼 추출=Task1, backfill 전환=Task2, 신규 테스트=Task3,
  CLI=Task4) + Phase 2(분석쿼리/dry-run=Task5, 실행/평가=Task6) 모두 태스크 존재.
  영향도 9항목: #1 mock 호환(Task1 Step3-4서 process_fn 주입+패치 이동), #2 반환키 보존
  (Task2 + Task3 returns_expected_keys), #3 동작변화 테스트(Task3), #4 단일 abort(Task2),
  #5 heartbeat off(backfill run_id 미전달=Task2), #6 토요일별 commit(Task2), #7 CLI(Task4),
  #8/#9 검증완료(코드 변경 없음) — 전부 반영.
- **Placeholder:** 없음(모든 코드 단계에 실제 코드 포함).
- **Type 일관성:** `run_parallel_batch` 시그니처/반환 키가 Task1 정의 ↔ Task2/Task3 사용에서 일치.
  `process_fn(conn, symbol, market, *, dry_run, as_of)` 시그니처가 weekend/backfill `_process_one`,
  테스트 fake와 일치. backfill 반환 키 집합이 Task2 정의 ↔ Task3 assert 일치.
