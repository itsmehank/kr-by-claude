# 백필 병렬화 + 2024 주말분류 백테스트 — 설계

작성일: 2026-06-18

## 목적

2024년 데이터로 주말분류(weekend classification) 파이프라인이 "제대로 분류하는지"를
검증한다. 전체 종목은 LLM 비용이 크므로, 일봉 데이터로 **유형별 대표 8종목**을 추출해
1년치(매주 토요일) 백필을 돌리고, 분류 결과를 **이후 수익률(forward-return)**과 대조해
유형별 기대 동작과 맞는지 평가한다.

선행 조건으로, 현재 **순차 실행**인 백필을 **병렬 실행**으로 바꾼다. 이때 이미 검증된
`weekend.py`의 병렬 로직을 **공용 함수로 추출**하여 두 모드가 공유하되, weekend의 기존
동작은 한 치도 훼손하지 않는다.

## 작업 범위 — 2 Phase

### Phase 1 — 백필 병렬화 (공용 헬퍼 추출)
weekend의 병렬·재시도·관측성 로직을 공용 모듈로 추출하고, weekend와 backfill 둘 다
그것을 사용하게 한다.

### Phase 2 — 2024 백테스트 실행 + 채점
병렬화된 백필로 8종목 × 2024 토요일을 분류하고, 결과를 forward-return과 대조해 평가한다.

---

## Phase 1 설계

### 현재 상태 (검증 완료)

- `weekend.py:148 run()` — `ThreadPoolExecutor` 병렬. 워커마다 자기 DB 커넥션
  (`weekend.py:103` `psycopg.connect(dsn)`). transient(TimeoutExpired)만 재시도,
  `UsageLimitError`면 `abort` Event set → 남은 호출 차단, `DataIntegrityError`는 skip,
  그 외는 종목별 실패. heartbeat 스레드(run_id 있을 때 30초 주기). reaper로 stale 정리.
- `backfill.py:48 run()` — **순차** for-loop. 토요일마다 후보를 한 종목씩 처리.
  종목별 commit + `_already_backfilled` skip으로 "중단→재실행=이어하기" 이미 동작.
  freeze 미저장. `UsageLimitError`면 즉시 중단·전파(`backfill.py:79-87`).

### 추출 대상 — 공용 모듈 `kr_pipeline/llm_runner/parallel.py` (신규)

공용으로 옮길 **진짜 공통 부분**:

1. **워커** `_process_one_worker(dsn, item, process_fn, *, dry_run, as_of, max_retries, abort)`
   - 자기 커넥션 open(실패 시 종목 실패로 흡수 — 배치 중단 안 함)
   - 재시도 루프: transient(`subprocess.TimeoutExpired`)만 `max_retries`회, `sleep(min(2*attempts,5))`
   - `process_fn(wconn, item, dry_run=, as_of=)` 호출 후 `wconn.commit()`
   - 예외 분류: `DataIntegrityError`→integrity dict, `UsageLimitError`→abort.set()+usage_limit dict,
     `BaseException`(KeyboardInterrupt/SystemExit)→abort.set()+raise, 그 외→fail dict
   - 반환 dict: `{"status": ok|integrity|usage_limit|fail|aborted, "symbol", "attempts", ...}`

2. **실행 루프** `run_parallel_batch(*, dsn, candidates, process_fn, concurrency, dry_run, as_of, abort=None, heartbeat=None)`
   - `workers = max(1, min(concurrency, len(candidates)))`
   - `ThreadPoolExecutor` submit + `as_completed` 집계: ok→processed++, integrity→list,
     aborted→pass, usage_limit→error 기록+`shutdown(wait=False, cancel_futures=True)`+break,
     그 외→failed_tickers
   - `prog` dict {done,total,in_flight,failed} + lock, 완료마다 갱신
   - `KeyboardInterrupt/SystemExit`: abort.set()+`shutdown(cancel_futures=True)`+raise
   - `heartbeat`(선택): 주어지면 30초 주기 heartbeat 스레드 구동(`dsn`, `run_id`, 초기 1회 즉시 write),
     `finally`에서 stop+join. None이면 heartbeat 없음.
   - 반환: `{"processed", "failed_tickers", "integrity_skipped", "usage_limited": bool, "usage_error": str|None}`

### 각 모드에 남는 것 (caller-specific — 헬퍼로 옮기지 않음)

- **weekend.run**: `reap_stale_weekend_runs`(헬퍼 호출 전), `_already_classified` skip,
  `process_fn = _process_one`(freeze 저장 포함), heartbeat 설정 전달,
  `usage_limited`면 기존대로 `UsageLimitError` raise. 반환 dict 모양 유지
  (`processed/candidates/skipped_existing/failures/failed_tickers/integrity_skipped`).
- **backfill.run**: 토요일 enumeration + 토요일마다 `_already_backfilled` skip,
  `process_fn = _process_one`(freeze 미저장), heartbeat=None,
  `usage_limited`면 남은 토요일까지 중단하고 `UsageLimitError` 전파.
  `BACKFILL_CONCURRENCY` env(기본 4) + `--concurrency` CLI 옵션 추가.

### weekend 동작 보존을 어떻게 보장하나 (사용자 요구: 안전)

추출은 "코드를 옮기는" 작업이므로, **옮긴 뒤에도 기존 weekend 테스트가 전부 green**이면
동작 보존이 증명된다. 안전망이 되는 기존 테스트(`tests/test_llm_weekend.py`):

| 테스트 | 보장하는 동작 |
|---|---|
| `test_weekend_batch_dry_run_processes_all_qualifying` | 후보 전부 처리 |
| `test_weekend_parallel_aggregates_and_retries` | 병렬 집계 + transient 재시도 |
| `test_weekend_worker_connect_failure_does_not_abort` | 커넥션 실패 흡수 |
| `test_weekend_writes_heartbeat_progress` | heartbeat 기록 |
| `test_reaper_marks_stale_running_failed` | reaper(weekend 전용) |
| `test_weekend_aborts_batch_on_usage_limit` | 사용량 한도 abort |
| `test_weekend_skips_already_classified_same_as_of` | resume skip |
| `test_weekend_interrupt_cancels_queued_work` | interrupt 시 큐 취소 |
| `test_weekend_no_worker_retry_on_claude_cli_error` | ClaudeCLIError 비재시도 |
| `test_weekend_does_not_skip_daily_delta_rows` | daily_delta 보호 |
| `test_weekend_zip_excludes_prior_analysis_and_pins_as_of` | as_of 고정 |

**작업 순서(특히 안전 관련):**
1. 작업 전 `uv run pytest tests/test_llm_weekend.py tests/test_llm_backfill.py` 실행해
   green 기준선 기록(현 baseline 실패와 구분).
2. `parallel.py`로 공용 함수 추출, weekend.run이 그것을 호출하도록 교체 —
   **동작 변화 0이 목표**. 위 11개 테스트가 그대로 green인지 확인(특성 테스트).
3. backfill.run을 공용 함수 사용으로 전환.
4. backfill 병렬 테스트 추가(weekend 테스트를 본떠): 병렬 집계+transient 재시도,
   connect 실패 흡수, 사용량 한도 abort(기존 `test_backfill_aborts_on_usage_limit`의
   병렬판), resume skip 유지, interrupt 취소.
5. 전체 `uv run pytest tests/` 회귀 판정(base↔HEAD 실패 수 비교).

---

## Phase 2 설계

### 대상 8종목 (일봉 데이터 기반 추출, 검증 완료)

추출 풀 = "2024년에 게이트(minervini_pass ∧ rs_line_not_declining_7m)를 20거래일 이상
통과"한 522종목. 각 종목의 2024 성과(연수익률·최대상승·고점후낙폭·일변동성)와
유형으로 큐레이션. 게이트 재현은 `load.py:get_qualifying_tickers`와 정확히 일치
(minervini ∧ rs ∧ delisted NULL ∧ adj_low NOT NULL) 확인. 사용 가격은 `adj_close`
(수정주가)로, LLM 페이로드(수정 OHLCV)와 동일.

| 유형 | 종목 | 통과 토요일 | 비고 |
|---|---|---|---|
| ① 상승(지속) | 003230 삼양식품 | 24 | +226%, 폭락 없음, raw=adj |
| ① 상승(지속) | 101930 인화정공 | 26 | +164%, 고점후 -8.5%, raw=adj |
| ② 돌파실패 | 399720 가온칩스 | 15 | runup +107% → 고점후 -78% (고점 3/28) |
| ② 돌파실패 | 200470 에이팩트 | 14 | runup +105% → 고점후 -76% (고점 6/4) |
| ③ 클라이맥스 | 257720 실리콘투 | 30 | runup +574% → 고점후 -55% (고점 6/21) |
| ④ 횡보 | 000320 노루홀딩스 | 24 | runup +23%, 저변동(일 1.66%) |
| ⑤ 변동성 | 900340 윙입푸드 | 12 | 일변동 7%대 |
| ⑥ 장기추세 | 267260 HD현대일렉트릭 | 46 | +377%, 거의 1년 내내 통과 |

합계 약 **191회** LLM 분류.

**제외/교체 근거:** SNT에너지(100840)는 2024-03-29 무상증자로 raw +9.9% ↔ adj +203%.
adj가 경제적 정답이나 "깨끗한 상승주" 유형에 기업행위 변수가 섞여 해석을 흐리므로
인화정공으로 교체. 나머지 7종목은 raw=adj 일치로 왜곡 없음 확인.

### 실행

```bash
# 1) dry-run 사전 점검 (LLM 비용 0): 8종목이 각 토요일에 후보로 잡히고 입력 빌드 정상인지
uv run python -m kr_pipeline.llm_runner --mode=backfill \
  --start=2024-01-06 --end=2024-12-28 --concurrency=4 --dry-run \
  --tickers=003230,101930,399720,200470,257720,000320,900340,267260

# 2) 실제 백필 (백그라운드). 중단되면 같은 명령 재실행 = 이어하기
uv run python -m kr_pipeline.llm_runner --mode=backfill \
  --start=2024-01-06 --end=2024-12-28 --concurrency=4 \
  --tickers=003230,101930,399720,200470,257720,000320,900340,267260
```

결과는 `classification_backfill`(PK: symbol, analyzed_for_date)에 적재. 실데이터 무오염.

### 채점 기준 (forward-return)

각 토요일 분류 시점 기준 이후 **+4주 / +12주** adj_close 수익률을 일봉에서 계산해 대조.
(2024 후반 토요일의 +12주는 2025년으로 넘어가며, 2025 데이터가 2026-06까지 있어 측정 가능.)

유형별 "성공" 기대:

- **① 상승**: 상승 전/초입 토요일에 entry 또는 watch(ignore 아님) → 잘 포착했나
- **② 돌파실패**: 고점 근처에서 깔끔한 entry를 내지 않았는지 / 위험플래그·watch로 경고
- **③ 클라이맥스**: 포물선 고점 토요일에 ignore(climax) 또는 강한 위험플래그
- **④ 횡보**: entry가 아니라 watch(base forming), 낮은 확신도
- **⑤ 변동성**: 확신도가 적절히 낮은지, 위험플래그에 변동성 반영
- **⑥ 장기추세**: 주 단위 판정이 일관·합리적으로 변하는지 (watch→적정 pivot에서 entry)

판정은 LLM 비결정성 때문에 **정확한 일치가 아니라 패턴**으로 평가
(재실행 결과를 동일성으로 비교 금지 — 메모리 규칙).

### 결과물

- 종목별 **주 단위 타임라인 표**: `토요일 | classification | confidence | 주요 risk_flags | +4주 | +12주`
- `classification_backfill` + 일봉 forward-return 조인 분석 쿼리
- 종목별 "의도대로 분류됐는지" 짧은 평가 + 전체 요약

### 알려진 제약

- 백필은 freeze(입력 스냅샷)를 저장하지 않음(`backfill.py:103`). 특정 시점 입력을
  재확인하려면 `build_analysis_inline(conn, symbol, on_date=토요일)`로 재구성(코드 수정 불필요).
- 게이트 통과 종목만 분류됨 — "폭락 중"인 시점은 게이트 탈락으로 분류 안 됨(의도된 동작).
  종목이 게이트를 들고나는 구간 자체가 관찰 대상.

## 비범위 (YAGNI)

- 백필 freeze 저장 추가 (필요 시 재구성으로 충분)
- 전체 종목/다년도 백테스트 (이번은 8종목 × 2024 한정)
- 채점 자동 스코어링 대시보드 (이번은 쿼리 + 수동 평가)
