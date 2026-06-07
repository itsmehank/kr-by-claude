# 주말 LLM 분류 병렬화·재시도·관측성·kill 자동정리 (P1 백엔드) 설계

날짜: 2026-06-07
범위: **weekend 전용** (daily_delta/backfill 제외). 웹 노출은 **P2 별도**.
대상(변경): `kr_pipeline/llm_runner/weekend.py`, `kr_pipeline/llm_runner/modes.py`(run_weekend run_id 전달), `kr_pipeline/llm_runner/__main__.py`(run_id 전달), `kr_pipeline/db/runs.py`(run_tracking 강건화 — **공용**), 신규 `kr_pipeline/llm_runner/heartbeat.py`(또는 weekend 내부), 신규 reaper 헬퍼(runs.py 또는 weekend)
무변경: 프롬프트, DB 스키마(진행/heartbeat 은 기존 `pipeline_runs.details` JSONB 사용 — 컬럼 추가 없음)

## 배경 / 문제

주말 (5) 분류(`weekend.run`)는 후보(~100여 종목, minervini_pass + rs_line_not_declining_7m 통과)를 **순차 루프**로 종목당 ZIP생성→Claude CLI→DB저장. Claude 호출이 병목이라 느리다. 추가로:
- `call_claude` 의 **타임아웃(`TimeoutExpired`)·`ClaudeCLIError` 는 재시도 없이** weekend 의 `except Exception` 으로 빠져 그 종목 실패.
- 실행 중 **진행/생존 여부를 외부에서 알기 어렵다**(모든 워커가 Claude 대기 중이면 조용함).
- 프로세스를 **강제 kill 하면** `run_tracking` 의 마무리가 안 돌아 `pipeline_runs.status='running'` 박제 → 웹에서 영영 "실행중"(알려진 버그 [[runner_kill_stuck_running]]). `run_tracking` 의 `except Exception` 은 KeyboardInterrupt(Ctrl-C)·SIGTERM 을 못 잡는다.

## 목표

weekend 를 **병렬**로 빠르게 + **일시오류 재시도** + **30초 하트비트(진행/생존)** + **kill 시 상태 자동정리**(박제 방지) + **실패 종목 상세 기록**. 진행/실패 정보는 `pipeline_runs.details` 에 쌓아 P2 웹이 노출.

## 핵심 결정 (브레인스토밍 합의)

1. 동시 실행 = **ThreadPoolExecutor, 기본 4, 인자/환경변수 조절**. 워커별 독립 DB 커넥션(psycopg conn 스레드 비안전).
2. 재시도 = **일시오류(`TimeoutExpired`/`ClaudeCLIError`)만 K=2회**; 영구오류(`ValueError`/`FileNotFoundError`)·`DataIntegrityError` 는 재시도 안 함. 기존 end-of-run 1회 재시도 루프 **대체(제거)**.
3. 관측성 = **로그 하트비트 + 웹 실시간 둘 다(다)** — 30초 주기 + 완료마다. (웹 표시는 P2; P1은 데이터 기록까지.)
4. kill 자동정리 = **시그널 핸들러는 공용(run_tracking)** (모든 파이프라인 박제 방지). 하트비트·stale reaper 는 weekend 전용.

## 비목표 (Non-goals)

- 웹 화면 변경(P2). daily_delta/backfill 병렬화. DB 스키마 컬럼 추가(details JSONB 재사용). 프롬프트 변경.

## 아키텍처

### 1. run_tracking 강건화 — `db/runs.py` (공용, 모든 파이프라인 혜택)
- `except Exception` → **`except BaseException`** 로 확대: KeyboardInterrupt(Ctrl-C)·SystemExit 도 잡아 `status='failed'`(error=str(e) 또는 "aborted") 마킹 후 **re-raise**.
- with-블록 진입 시 **SIGTERM 핸들러 설치**(기존 핸들러 보존), 핸들러는 예외(`KeyboardInterrupt` 등)를 raise → 위 except 가 잡아 failed 마킹. with-블록 종료(정상/예외) 시 **원래 핸들러 복원**. **단 `signal.signal` 은 메인 스레드에서만 가능 → `threading.current_thread() is threading.main_thread()` 일 때만 설치, 아니면 skip**(BaseException 확대는 그대로 동작). 워커 스레드 안에서 run_tracking 을 쓰지 않으므로 실사용엔 영향 없음.
- 효과: Ctrl-C·일반 `kill`(SIGTERM)·예외 모두 즉시 'failed' 기록. `kill -9`(SIGKILL)는 잡을 수 없음 → §3 reaper 가 커버.

### 2. 병렬 실행 + 재시도 — `weekend.py`
- `run(conn, *, dry_run, as_of, limit, ticker, run_id=None, concurrency=None)`: concurrency = `concurrency or int(env WEEKEND_CONCURRENCY or 4)`.
- 후보를 `ThreadPoolExecutor(max_workers=min(concurrency, len(candidates)))` 로 처리. 각 future = `_process_one_worker(db_url, symbol, market, ...)`.
- **워커**: 자기 커넥션 `connect(db_url)` 열고(메인 커넥션의 dsn 재사용: `conn.info.dsn`; 테스트는 test DB dsn — passwordless localhost 라 재구성 가능) → `_process_one` 로직(build_analysis_zip + call_claude + insert_classification + save_freeze) + commit + close.
  - **재시도**: `TimeoutExpired`/`ClaudeCLIError` 면 최대 K=2 재시도(짧은 backoff); `DataIntegrityError` → integrity_skip(재시도 X); 그 외 예외 → 실패(재시도 X). 종목별 **attempts** 기록.
- `as_completed` 로 집계: 성공 수, `failed_tickers=[{symbol, error, attempts}]`, `integrity_skipped=[...]`. **기존 end-of-run 재시도 루프 제거**.
- 반환 dict: 기존 키 + `failed_tickers` 가 `{symbol,error,attempts}` 형태로 강화.

### 3. 하트비트 + stale reaper — weekend (heartbeat 는 details JSONB 사용)
- **하트비트 스레드**(자기 커넥션, run_id 있을 때만): 30초마다 + (메인 루프가 완료마다 갱신하는) 공유 진행상태(lock 보호: done/total/in_flight/failed)를 읽어 `UPDATE pipeline_runs SET details = <merge {weekend_progress:{...}, heartbeat_at:<utcnow iso>}> WHERE id=run_id` + commit + 로그("weekend: 37/120 done, in-flight 4, failed 2"). weekend.run 종료 시 스레드 stop+join(이후 run_tracking 이 최종 details=전체 result 기록).
- **stale reaper** `reap_stale_weekend_runs(conn, stale_seconds=90)`: weekend 시작 시, `pipeline='llm_weekend' AND status='running' AND (details->>'heartbeat_at')::timestamptz < now()-interval` 인 행을 `status='failed'`, error="stale heartbeat — process likely killed" 로 UPDATE. → `kill -9`/크래시 박제 자동 정리.

### 4. run_id 배선
- `__main__` 의 weekend 분기에서 `modes.run_weekend(..., run_id=state["run_id"])` → `weekend.run(..., run_id=...)`. run_id None 이면(테스트 등) 하트비트 skip.

## 데이터 흐름 / 동시성

- 워커 N개 각자 독립 커넥션으로 ZIP·LLM·INSERT·commit (psycopg conn 비공유). run_tracking·하트비트·reaper 는 메인 커넥션/하트비트 전용 커넥션 사용 — 워커 커넥션과 분리.
- 하트비트 스레드가 30초마다 running 행을 갱신 → 모든 워커가 LLM 대기 중이어도 liveness 신호 지속.
- 진행/실패는 `details` JSONB(`weekend_progress`, `heartbeat_at`, `failed_tickers`, `integrity_skipped`)에 기록 → API 이미 노출(웹 표시는 P2).

## 에러 처리 / 엣지

- 영구오류·정수성 위반은 재시도 없이 분류·기록. 일시오류만 재시도(무한루프 방지: K=2 상한).
- 워커 커넥션은 finally 로 close(누수 방지). 한 워커 예외는 그 종목만 실패(다른 워커 무관).
- 하트비트/리퍼 실패는 본 작업을 막지 않음(로그+계속).
- run_tracking 의 BaseException 확대는 re-raise 유지 → 상위 동작 불변(단 행은 failed 기록).

## 테스트

- **run_tracking 강건화**(runs.py): with-블록에서 KeyboardInterrupt 발생 시 행이 'failed' 로 기록되고 re-raise 되는지(db 픽스처). SIGTERM 핸들러 설치/복원(단위).
- **병렬+집계+재시도**(weekend): dry-run mock(스레드 안전·즉시)으로 N후보 병렬 처리·성공 집계. 워커 함수에 일시오류 주입 시 K회 재시도 후 성공/실패, 영구오류는 재시도 안 함(mock/monkeypatch). failed_tickers 가 {symbol,error,attempts} 형태인지.
- **stale reaper**: 오래된 heartbeat_at 의 running 'llm_weekend' 행을 seed → reaper 가 'failed' 로 정리, 최신 heartbeat 행은 보존.
- **하트비트**: progress UPDATE 가 details 에 weekend_progress·heartbeat_at 을 쓰는지(db).
- 회귀: 기존 weekend/store/runs 테스트 통과, base 대비 0. (워커 커넥션 url=메인 dsn 이라 테스트는 kr_test 로 감.)

## 파일 변경 예상

- 변경: `db/runs.py`(run_tracking BaseException+SIGTERM), `weekend.py`(병렬+재시도+하트비트+reaper 호출), `modes.py`·`__main__.py`(run_id 전달).
- 신규(또는 weekend 내부): 하트비트 스레드, `reap_stale_weekend_runs`, `_process_one_worker`.
- 테스트: `tests/` 에 run_tracking 강건화·병렬/재시도·reaper·하트비트.

## 후속

- **P2(웹)**: runner/llm-weekend 상세에서 실시간 진행 + 실패 종목(사유·attempts) + "중단됨(stale)" 표시.
- (선택) daily_delta 동일 병렬/재시도 적용.
