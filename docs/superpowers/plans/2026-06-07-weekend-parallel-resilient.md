# 주말 LLM 분류 병렬·재시도·관측성·kill자동정리 (P1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** weekend LLM 분류를 병렬 실행 + 일시오류 재시도 + 30초 하트비트(진행/생존) + kill 자동정리(박제 방지) + 실패 종목 상세 기록으로 개선(웹 노출은 P2).

**Architecture:** `run_tracking`(공용)을 BaseException+SIGTERM 으로 강건화. `weekend.run` 을 ThreadPoolExecutor(워커별 독립 커넥션)로 병렬화하고 일시오류만 재시도. 하트비트 스레드가 30초마다 `pipeline_runs.details` 에 진행/heartbeat_at 기록, stale reaper 가 시작 시 박제된 옛 running 행 정리.

**Tech Stack:** Python (psycopg3, threading, concurrent.futures, signal), pytest+pytest-mock, auto-rollback `db` 픽스처.

---

## 배경 / 스펙 근거

스펙: `docs/superpowers/specs/2026-06-07-weekend-parallel-resilient-design.md`.

실측:
- `weekend.run(conn, *, dry_run=False, as_of=None, limit=None, ticker=None)`(weekend.py:24): 후보 순차 for-loop, `DataIntegrityError`→integrity_skipped(rollback), `Exception`→failures+failed_tickers(rollback), 종목당 `conn.commit()`. **끝에 1회 재시도 루프(81-102)**. 반환 `{processed, candidates, failures, failed_tickers:[symbol], integrity_skipped:[{...}]}`.
- `_process_one(conn, symbol, market, *, dry_run, as_of)`: build_analysis_zip + temp zip + `call_claude` + `insert_classification` + `save_freeze`.
- `call_claude` 는 `subprocess.TimeoutExpired`(uncaught)·`ClaudeCLIError`(claude_cli.py:21) 를 raise; rc/JSON 오류는 내부 4회 backoff.
- `run_tracking`(runs.py:46): `start_run`+commit→yield→success finish / `except Exception`→failed+raise. **KeyboardInterrupt/SIGTERM 미포착**(박제).
- `modes.run_weekend(conn, *, dry_run, as_of, limit, ticker=None)`(modes.py:28)→`weekend.run(...)`. `__main__`(__main__.py:92) `with run_tracking(...) as state:` 내 `state["run_id"]` 보유, `state["details"]=result`.
- `conn.info.dsn` 으로 워커 재연결 가능(검증: kr_test). `save_freeze(conn, *, artifact_bytes, content_type, ticker, stage)`.

**비목표:** 웹(P2), daily_delta/backfill, 스키마 컬럼 추가, 프롬프트.

---

### Task 1: run_tracking 강건화 (공용 — kill 박제 방지)

**Files:**
- Modify: `kr_pipeline/db/runs.py` (`run_tracking`)
- Test: `tests/test_db_runs.py` (없으면 신규)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_db_runs.py`:

```python
def test_run_tracking_marks_failed_on_keyboardinterrupt(db):
    import pytest
    from kr_pipeline.db.runs import run_tracking
    with pytest.raises(KeyboardInterrupt):
        with run_tracking(db, pipeline="t_kill", mode="x", params={}) as state:
            rid = state["run_id"]
            raise KeyboardInterrupt("simulated kill")
    db.commit()  # run_tracking 의 실패 UPDATE 는 자체 commit 됨
    with db.cursor() as cur:
        cur.execute("SELECT status, error FROM pipeline_runs WHERE id=%s", (rid,))
        status, error = cur.fetchone()
    assert status == "failed"
    assert "simulated kill" in (error or "")


def test_run_tracking_success_unchanged(db):
    from kr_pipeline.db.runs import run_tracking
    with run_tracking(db, pipeline="t_ok", mode="x", params={}) as state:
        rid = state["run_id"]
        state["rows_affected"] = 3
    with db.cursor() as cur:
        cur.execute("SELECT status, rows_affected FROM pipeline_runs WHERE id=%s", (rid,))
        status, ra = cur.fetchone()
    assert status == "success" and ra == 3
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_db_runs.py -k keyboardinterrupt -v`
Expected: FAIL — 현재 `except Exception` 은 KeyboardInterrupt(BaseException) 미포착 → 행이 'running' 으로 남아 status != 'failed'.

- [ ] **Step 3: 구현** — `runs.py` 상단에 `import signal, threading` 추가. `run_tracking` 을 교체:

```python
@contextmanager
def run_tracking(conn: Connection, *, pipeline: str, mode: str, params: dict) -> Iterator[dict]:
    run_id = start_run(conn, pipeline=pipeline, mode=mode, params=params)
    conn.commit()
    state: dict = {"run_id": run_id, "warnings": [], "rows_affected": None, "total_count": None, "details": None}

    # 잡히는 종료 신호(SIGTERM)도 예외로 전환 → 아래 except 가 failed 마킹. 메인 스레드에서만 설치 가능.
    _is_main = threading.current_thread() is threading.main_thread()
    _prev = None
    if _is_main:
        _prev = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt(f"signal {signum}")))
    try:
        yield state
        warnings_json: str | None = None
        if state["warnings"]:
            warnings_json = json.dumps({"warnings": state["warnings"]}, ensure_ascii=False)
        finish_run(conn, run_id, status="success", rows_affected=state["rows_affected"],
                   total_count=state["total_count"], error=warnings_json, details=state["details"])
        conn.commit()
    except BaseException as e:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_runs SET finished_at = NOW(), status = 'failed', error = %s WHERE id = %s",
                (str(e) or type(e).__name__, run_id),
            )
        conn.commit()
        raise
    finally:
        if _is_main and _prev is not None:
            signal.signal(signal.SIGTERM, _prev)
```
(핵심 변경: `except Exception`→`except BaseException`; 메인스레드 한정 SIGTERM 핸들러 설치/복원.)

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_db_runs.py -v` → 2 passed. (기존 run_tracking 사용 테스트도 통과 — 성공/예외 동작 동일, 단 BaseException 으로 확대.)

- [ ] **Step 5: 커밋**
```bash
git add kr_pipeline/db/runs.py tests/test_db_runs.py
git commit -m "feat(runs): run_tracking BaseException+SIGTERM 강건화 (kill 박제 방지, 공용)"
```

---

### Task 2: stale reaper 헬퍼

**Files:**
- Modify: `kr_pipeline/llm_runner/weekend.py` (`reap_stale_weekend_runs` 추가)
- Test: `tests/test_weekend_reaper.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_weekend_reaper.py`:

```python
from datetime import datetime, timezone, timedelta
import json


def _seed_run(db, *, status, heartbeat_age_s=None, run_id_out=None):
    with db.cursor() as cur:
        details = None
        if heartbeat_age_s is not None:
            hb = (datetime.now(timezone.utc) - timedelta(seconds=heartbeat_age_s)).isoformat()
            details = json.dumps({"heartbeat_at": hb})
        cur.execute(
            "INSERT INTO pipeline_runs (pipeline, mode, started_at, status, details) "
            "VALUES ('llm_weekend','weekend', NOW(), %s, %s::jsonb) RETURNING id",
            (status, details),
        )
        return cur.fetchone()[0]


def test_reaper_marks_stale_running_failed(db):
    from kr_pipeline.llm_runner.weekend import reap_stale_weekend_runs
    stale = _seed_run(db, status="running", heartbeat_age_s=200)   # > 90s
    fresh = _seed_run(db, status="running", heartbeat_age_s=10)    # 최근
    nohb = _seed_run(db, status="running", heartbeat_age_s=None)   # heartbeat 없음
    current = _seed_run(db, status="running", heartbeat_age_s=200) # 현재 실행(제외 대상)
    db.commit()

    reap_stale_weekend_runs(db, current_run_id=current, stale_seconds=90)
    db.commit()

    def status_of(rid):
        with db.cursor() as cur:
            cur.execute("SELECT status FROM pipeline_runs WHERE id=%s", (rid,))
            return cur.fetchone()[0]
    assert status_of(stale) == "failed"      # stale → 정리
    assert status_of(fresh) == "running"     # 최근 → 보존
    assert status_of(nohb) == "running"      # heartbeat 없음 → 미매칭(보존)
    assert status_of(current) == "running"   # 현재 실행 → 제외(보존)
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_weekend_reaper.py -v` → FAIL (no `reap_stale_weekend_runs`).

- [ ] **Step 3: 구현** — `weekend.py` 에 추가:

```python
def reap_stale_weekend_runs(conn, *, current_run_id, stale_seconds: int = 90) -> int:
    """heartbeat 가 오래된 'llm_weekend' running 행을 'failed' 로 정리(kill -9/크래시 박제 복구).

    현재 실행(current_run_id)·heartbeat 없는 행은 제외. 정리한 행 수 반환.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pipeline_runs
               SET status = 'failed', finished_at = NOW(),
                   error = 'stale heartbeat — process likely killed'
             WHERE pipeline = 'llm_weekend' AND status = 'running'
               AND id <> %s
               AND details ->> 'heartbeat_at' IS NOT NULL
               AND (details ->> 'heartbeat_at')::timestamptz < NOW() - make_interval(secs => %s)
            """,
            (current_run_id if current_run_id is not None else -1, stale_seconds),
        )
        return cur.rowcount
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_weekend_reaper.py -v` → PASS.

- [ ] **Step 5: 커밋**
```bash
git add kr_pipeline/llm_runner/weekend.py tests/test_weekend_reaper.py
git commit -m "feat(weekend): reap_stale_weekend_runs — stale running 행 자동 failed 정리"
```

---

### Task 3: 병렬 워커 + 일시오류 재시도 (weekend.run)

**Files:**
- Modify: `kr_pipeline/llm_runner/weekend.py` (`run` 병렬화, `_process_one_worker` 추가)
- Test: `tests/test_weekend_parallel.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_weekend_parallel.py`:

```python
def test_weekend_parallel_aggregates_and_retries(db, mocker):
    import kr_pipeline.llm_runner.weekend as wk
    from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError

    # 후보 3개 고정
    mocker.patch.object(wk, "get_qualifying_tickers", return_value=[
        {"symbol": "OKAA", "market": "KOSPI"},
        {"symbol": "TRNS", "market": "KOSPI"},  # 일시오류 1회 후 성공
        {"symbol": "PERM", "market": "KOSPI"},  # 영구 실패
    ])
    calls = {}
    def fake_process_one(conn, symbol, market, *, dry_run, as_of):
        calls[symbol] = calls.get(symbol, 0) + 1
        if symbol == "TRNS" and calls[symbol] == 1:
            raise ClaudeCLIError("transient")          # 1회 일시오류 → 재시도
        if symbol == "PERM":
            raise ValueError("permanent")              # 영구 → 재시도 안 함
        return None
    mocker.patch.object(wk, "_process_one", side_effect=fake_process_one)

    r = wk.run(db, dry_run=True, concurrency=3, run_id=None)

    assert r["processed"] == 2                          # OKAA, TRNS
    assert calls["TRNS"] == 2                           # 재시도 1회
    assert calls["PERM"] == 1                           # 영구는 재시도 안 함
    failed = {f["symbol"]: f for f in r["failed_tickers"]}
    assert "PERM" in failed and failed["PERM"]["attempts"] == 1
    assert "permanent" in failed["PERM"]["error"]
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_weekend_parallel.py -v`
Expected: FAIL — `run()` 에 `concurrency`/`run_id` 인자 없음 + failed_tickers 가 {symbol} 리스트(dict 아님) + 재시도 동작 없음.

- [ ] **Step 3: 구현** — `weekend.py` 상단 import 추가:
```python
import os, time, subprocess
import psycopg
from concurrent.futures import ThreadPoolExecutor, as_completed
from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError
```
워커 함수 추가:
```python
_TRANSIENT_EXC = (subprocess.TimeoutExpired, ClaudeCLIError)

def _process_one_worker(dsn, symbol, market, *, dry_run, as_of, max_retries=2):
    """자기 커넥션으로 한 종목 처리. 일시오류만 재시도. dict 반환."""
    from api.services.integrity_guard import DataIntegrityError
    wconn = psycopg.connect(dsn)
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
```
`run()` 의 순차 루프 + end-of-run 재시도(81-102) 전체를 다음으로 교체(후보 산정·로그까지는 유지):
```python
    concurrency = concurrency or int(os.environ.get("WEEKEND_CONCURRENCY", "4"))
    processed = 0
    failed_tickers: list[dict] = []
    integrity_skipped: list[dict] = []
    dsn = conn.info.dsn

    workers = max(1, min(concurrency, len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_process_one_worker, dsn, c["symbol"], c["market"],
                          dry_run=dry_run, as_of=as_of): c["symbol"] for c in candidates}
        for fut in as_completed(futs):
            r = fut.result()
            if r["status"] == "ok":
                processed += 1
            elif r["status"] == "integrity":
                integrity_skipped.append(r["detail"])
            else:
                failed_tickers.append({"symbol": r["symbol"], "error": r.get("error", ""), "attempts": r["attempts"]})

    log.info("weekend batch done: processed=%d failed=%d integrity_skipped=%d",
             processed, len(failed_tickers), len(integrity_skipped))
    return {
        "processed": processed,
        "candidates": len(candidates),
        "failures": len(failed_tickers),
        "failed_tickers": failed_tickers,           # [{symbol,error,attempts}]
        "integrity_skipped": integrity_skipped,
    }
```
`run()` 시그니처에 `concurrency: int | None = None, run_id: int | None = None` 추가(run_id 는 Task 4 에서 사용). 기존 `from api.services.integrity_guard import DataIntegrityError`(루프 내) 는 워커로 이동했으므로 run 본문에서 제거.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_weekend_parallel.py -v` → PASS. (워커가 `psycopg.connect(dsn)` 로 kr_test 에 붙고 `_process_one` 은 mock 이라 실제 DB 작업 없음.)

- [ ] **Step 5: 커밋**
```bash
git add kr_pipeline/llm_runner/weekend.py tests/test_weekend_parallel.py
git commit -m "feat(weekend): ThreadPoolExecutor 병렬 + 일시오류 재시도 + failed_tickers 상세"
```

---

### Task 4: 하트비트 + run_id 배선 + reaper 호출

**Files:**
- Modify: `kr_pipeline/llm_runner/weekend.py` (하트비트 스레드, run() 에 진행추적·reaper·heartbeat 결선)
- Modify: `kr_pipeline/llm_runner/modes.py` (run_weekend run_id 전달), `kr_pipeline/llm_runner/__main__.py` (run_id 전달)
- Test: `tests/test_weekend_heartbeat.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_weekend_heartbeat.py`:

```python
def test_weekend_writes_heartbeat_progress(db, mocker):
    import json
    import kr_pipeline.llm_runner.weekend as wk
    # running 행 하나 생성(이 run 의 row)
    with db.cursor() as cur:
        cur.execute("INSERT INTO pipeline_runs (pipeline, mode, started_at, status) "
                    "VALUES ('llm_weekend','weekend',NOW(),'running') RETURNING id")
        run_id = cur.fetchone()[0]
    db.commit()

    mocker.patch.object(wk, "get_qualifying_tickers", return_value=[{"symbol": "AAAA", "market": "KOSPI"}])
    mocker.patch.object(wk, "_process_one", side_effect=lambda *a, **k: None)

    wk.run(db, dry_run=True, concurrency=1, run_id=run_id)

    with db.cursor() as cur:
        cur.execute("SELECT details FROM pipeline_runs WHERE id=%s", (run_id,))
        details = cur.fetchone()[0]
    assert details is not None
    assert details.get("heartbeat_at")                       # 초기 heartbeat 기록됨
    assert details.get("weekend_progress", {}).get("total") == 1
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_weekend_heartbeat.py -v` → FAIL (run_id 미사용, details 미기록).

- [ ] **Step 3: 구현** — `weekend.py` 상단 `import threading`. 하트비트/진행 결선:

```python
def _write_heartbeat(dsn, run_id, progress: dict):
    import json
    from datetime import datetime, timezone
    payload = json.dumps({"weekend_progress": progress, "heartbeat_at": datetime.now(timezone.utc).isoformat()})
    hb = psycopg.connect(dsn)
    try:
        with hb.cursor() as cur:
            cur.execute("UPDATE pipeline_runs SET details = %s::jsonb WHERE id = %s", (payload, run_id))
        hb.commit()
    finally:
        hb.close()
```
`run()` 안에서, reaper + 공유 진행상태 + 하트비트 스레드를 결선. Task 3 의 ThreadPoolExecutor 블록을 다음으로 감싼다:
```python
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
        if run_id is None:
            return
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
        # 초기 즉시 1회 기록(첫 틱 전 kill 도 stale 추적 가능) 후 주기 스레드 시작
        with prog_lock:
            prog["in_flight"] = min(workers, total)
        _write_heartbeat(dsn, run_id, dict(prog))
        hb_thread.start()
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_process_one_worker, dsn, c["symbol"], c["market"],
                              dry_run=dry_run, as_of=as_of): c["symbol"] for c in candidates}
            for fut in as_completed(futs):
                r = fut.result()
                if r["status"] == "ok":
                    processed += 1
                elif r["status"] == "integrity":
                    integrity_skipped.append(r["detail"])
                else:
                    failed_tickers.append({"symbol": r["symbol"], "error": r.get("error", ""), "attempts": r["attempts"]})
                with prog_lock:
                    prog["done"] += 1
                    prog["failed"] = len(failed_tickers)
                    prog["in_flight"] = max(0, min(workers, total) - 0)  # 근사: 남은 미완료 중 동시 한도
    finally:
        stop.set()
        if hb_thread.is_alive():
            hb_thread.join(timeout=5)
```
(주의: 위 `processed/failed_tickers/integrity_skipped/workers` 는 Task 3 에서 이미 선언됨. Task 3 의 ThreadPoolExecutor 블록을 이 결선 버전으로 대체.)
- `modes.run_weekend` 시그니처에 `run_id: int | None = None` 추가, `weekend.run(conn, ..., run_id=run_id)` 로 전달.
- `__main__.py` weekend 분기: `modes.run_weekend(conn, dry_run=..., as_of=..., limit=..., ticker=..., run_id=state["run_id"])`.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_weekend_heartbeat.py tests/test_weekend_parallel.py tests/test_weekend_reaper.py -v` → PASS (heartbeat details 기록 + 병렬/재시도 + reaper 모두).

- [ ] **Step 5: 커밋**
```bash
git add kr_pipeline/llm_runner/weekend.py kr_pipeline/llm_runner/modes.py kr_pipeline/llm_runner/__main__.py tests/test_weekend_heartbeat.py
git commit -m "feat(weekend): 하트비트(진행/heartbeat_at) + run_id 배선 + reaper 호출"
```

---

### Task 5: 회귀

**Files:** 없음(검증)

- [ ] **Step 1: 변경영역 + 인접**
```bash
uv run pytest tests/test_db_runs.py tests/test_weekend_reaper.py tests/test_weekend_parallel.py tests/test_weekend_heartbeat.py tests/test_llm_runner_store.py -v
```
Expected: 신규 전부 PASS.

- [ ] **Step 2: 전체 회귀 base 대비**
```bash
uv run pytest tests/ -q 2>&1 | grep "^FAILED" | sed 's/ -.*//' | sort > /tmp/wp_head.txt
wc -l < /tmp/wp_head.txt
```
Expected: base(`git merge-base HEAD main`) 사전 실패 수와 동일 — 신규 회귀 0. 다르면 `comm -23` 로 식별 후 수정. (특히 run_tracking 을 쓰는 기존 테스트가 BaseException 확대로 안 깨지는지 확인.)

- [ ] **Step 3: 최종 커밋(없으면 skip)**

---

## Self-Review

**1. Spec coverage:**
- run_tracking 강건화(공용, BaseException+SIGTERM): Task 1 ✓
- stale reaper(현재실행 제외, NULL 미매칭): Task 2 ✓
- 병렬(ThreadPoolExecutor, 워커별 conn, concurrency 기본4/env): Task 3 ✓
- 일시오류만 재시도(K=2), 영구/정수성 미재시도, attempts 기록, end-of-run 재시도 제거: Task 3 ✓
- failed_tickers={symbol,error,attempts}: Task 3 ✓
- 하트비트(초기 t=0 + 30초, details.weekend_progress+heartbeat_at, 로그): Task 4 ✓
- run_id 배선(__main__→run_weekend→run): Task 4 ✓
- reaper 호출(시작 시, 현재 run 제외): Task 4 ✓
- 회귀 0: Task 5 ✓

**2. Placeholder scan:** 모든 코드 스텝에 실제 코드/명령/기대. Task 4 의 in_flight 는 "근사"로 명시(정확 카운트 아님 — 표시용). Task 5 `<base>`=`git merge-base HEAD main`.

**3. Type consistency:** `_process_one_worker` 반환 dict(status/symbol/attempts/error/detail) ↔ run 집계 일관. `run(concurrency, run_id)` 시그니처 ↔ modes/__main__ 전달 일관. `reap_stale_weekend_runs(conn,*,current_run_id,stale_seconds)` ↔ Task4 호출 일관. heartbeat details 키(weekend_progress/heartbeat_at) ↔ reaper(heartbeat_at)·테스트 일관.

**알려진 한계(의도적):** in_flight 는 근사치(표시용). kill -9 첫 순간(초기 heartbeat 기록 직전) 의 극히 짧은 창은 미커버(초기 heartbeat 가 거의 즉시라 무시 가능). 웹 표시는 P2.
