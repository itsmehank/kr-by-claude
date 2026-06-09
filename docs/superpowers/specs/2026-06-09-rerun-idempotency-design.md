# 평일 파이프라인 재실행 멱등성 — evaluate_pivot · entry_params (설계)

날짜: 2026-06-09. 브랜치: `worktree-rerun-idempotency`.

## 1. 문제

`full-daily`(LLM 평일 전체 분석, 수동 실행)은 `disqualify → daily_delta → evaluate_pivot →
entry_params → performance` 를 순차 실행한다. 단계 간 체크포인트가 없고, 일부 단계가 종목 단위
재실행 skip 을 하지 않는다:

- **daily_delta / performance / disqualify**: 이미 멱등(7일 cooldown / UPSERT+skip-filled / IN 제외).
- **evaluate_pivot**: 활성 watch/entry **전수**를 매번 게이트 재평가 + 트리거 종목 LLM 재호출.
  `evaluated_at = now()` 라 매 실행 새 행 → 중단 후 재실행 시 **이미 평가한 종목도 다시 분석** +
  같은 날 trigger 로그 중복 행.
- **entry_params**: 오늘 go_now 후보를 다시 가져와 LLM 재호출(PK 충돌로 행 중복은 막히나 LLM 비용
  재발생). evaluate 가 중복 행을 만들면 서로 다른 `signal_at` 로 **중복 매수시그널** 생성 가능.

### 1.1 핵심 제약 — "같은 wall-clock 날"이 곧 중복이 아니다

운영은 하루에 두 번 실행될 수 있다:
- 오전(09시 전): **전날 데이터**(as_of=D-1)로 실행.
- 오후(18시 후): **당일 데이터**(as_of=D)로 실행.

두 실행은 같은 wall-clock 날이지만 **데이터 날짜(as_of)가 달라 독립**이어야 한다(중복 처리 금지).
"같은 wall-clock 날"을 중복 기준으로 쓰는 곳이 **두 레이어**에 있다:

**(A) run 레이어 — 1차 차단(가장 눈에 띔):** `runner_service.check_can_run` /
`check_can_run_pipeline` 의 "duplicate" 판정이 `(started_at AT TIME ZONE 'Asia/Seoul')::date = today`
(wall-clock). full-daily 는 `llm_daily_delta` 로 추적되므로 **오전 성공 후 오후 실행이 "오늘 이미
성공" = duplicate 로 차단**되고 web `force` 로만 우회된다. `pipeline_runs.params` 에 `as_of` 가
이미 저장돼 있는데도 그걸 안 본다. 게다가 `spawn_runner`/`spawn_pipeline` 은 CLI 에 `--force` 를
전달하지 않아, web force 로 통과해도 stage 는 force 없이 돈다.

**(B) stage 레이어 — 결과 저장:** `trigger_evaluation_log`·`entry_params` 가 데이터 날짜를
저장하지 않고 wall-clock(`evaluated_at`/`signal_at`)만 저장 → 저장 데이터만으론 두 실행을 구분
불가. 기존 `_fetch_go_now_candidates` 의 `(evaluated_at AT TIME ZONE 'UTC')::date = as_of` 매칭은
UTC 자정을 넘기면 깨지는 잠재 버그도 있다.

→ **양 레이어 모두 dedup 기준을 wall-clock 이 아니라 데이터 날짜(as_of)로** 바꿔야 한다.

## 2. 목표 / 범위 (옵션 A — run + stage 양 레이어)

- **오전(D-1)·오후(D)는 web force 없이 자연 독립 실행**: run 레이어 duplicate 판정을 as_of 기준으로
  바꿔, 데이터 날짜가 다르면 중복이 아니다.
- evaluate_pivot · entry_params 를 **데이터 날짜(as_of) 기준 멱등**: 같은 as_of 재실행 시 이미 처리한
  종목 skip(이어서 진행), 다른 as_of 는 독립 저장.
- 기본 = skip. `force` 시 = **같은 as_of 결과를 replace(삭제 후 재분석)**. web force → CLI `--force`
  까지 전파.
- **forward-only**: 과거에 쌓인 중복 행 cleanup 은 하지 않는다.

### 범위 밖 (별도 티켓)
- **(B) performance 기준일 보정**: performance 가 성과 기준일을 `signal_at`(wall-clock) 대신
  `analyzed_for_date`(데이터 날짜)로 쓰도록 — 오전 케이스에서 하루 밀림 해소. 성과 로직이라 분리.
- 과거 중복 행 cleanup, web UI 설명문 동기화, 동시 실행(concurrent run) 방지, PK 변경.

## 3. 설계

`weekly_classification` 의 검증된 패턴(`classified_at` wall-clock + `analyzed_for_date` 데이터날짜)을
두 테이블에 적용한다.

### 3.1 스키마 (kr_pipeline/db/schema.sql)

```sql
-- 기존 테이블에도 적용 (CREATE TABLE IF NOT EXISTS 는 신규 컬럼 미반영)
ALTER TABLE trigger_evaluation_log ADD COLUMN IF NOT EXISTS analyzed_for_date DATE;
ALTER TABLE entry_params           ADD COLUMN IF NOT EXISTS analyzed_for_date DATE;
CREATE INDEX IF NOT EXISTS idx_trigger_eval_afd ON trigger_evaluation_log (analyzed_for_date);
CREATE INDEX IF NOT EXISTS idx_entry_params_afd ON entry_params (analyzed_for_date);
```
- CREATE 본문에도 컬럼 명시(fresh DB·가독성). **kr_pipeline·kr_test 양쪽 psql 수동 적용**.
- **PK 불변**: trigger_evaluation_log (symbol, evaluated_at) / entry_params (symbol, signal_at) 그대로
  → `signal_performance` FK(symbol, signal_at) 안전. `analyzed_for_date` 는 일반 컬럼(유일성 DB 강제
  안 함 — 앱 레벨 skip 가드로 보장, forward-only).

### 3.2 쓰기 — analyzed_for_date = as_of 저장
- `store.insert_trigger_log`: 컬럼 + `analyzed_for_date` 파라미터 추가. `evaluate_pivot._process_one`
  이 `as_of` 전달.
- `store.insert_entry_params`: 컬럼 + `analyzed_for_date` 파라미터 추가. `entry_params._process_one`
  이 run 의 `as_of` 전달.
- `evaluated_at`/`signal_at` 은 wall-clock 그대로(PK 연속). analyzed_for_date 만 신규 dedup 키.

### 3.3 읽기 — dedup 매칭 재지정 (COALESCE 필수)
- **`entry_params._fetch_go_now_candidates`**:
  - trigger 매칭: `(t.evaluated_at AT TIME ZONE 'UTC')::date = as_of`
    → `COALESCE(t.analyzed_for_date, (t.evaluated_at AT TIME ZONE 'UTC')::date) = as_of`.
    (레거시 NULL 행·기존 테스트 backward-compat + UTC자정 버그 해소.)
  - skip 가드 추가(--force 아닐 때): `AND NOT EXISTS (SELECT 1 FROM entry_params ep
    WHERE ep.symbol = t.symbol AND COALESCE(ep.analyzed_for_date, ep.signal_at::date) = as_of)`.
  - 견고화: `DISTINCT ON (t.symbol)` (같은 as_of·종목 trigger 행이 둘 이상이어도 1건만 처리).
- **`evaluate_pivot.run`**: `triggered` 에서 "이미 as_of 로 평가된 종목" 제외(--force 아닐 때).
  같은 COALESCE 기준으로 trigger_evaluation_log 조회해 제외 집합 구성.

### 3.4 읽기 — 무변경 (컬럼 추가는 additive)
- `payload_lite` build_for_5b history(7일 윈도)·build_for_6(evaluated_at 정확매칭), `performance`
  (signal_at 90일 윈도; B에서 별도 처리), `api/routers/triggers.py`·`signals.py`(표시용 SELECT·
  wall-clock 날짜필터), `test_schema_llm_runner`(issubset) — 모두 영향 없음.

### 3.5 `--force` = replace (stage 레이어)
- CLI `--force`(default False) → `__main__` → `run_full_daily(force=)` → `evaluate_pivot.run(force=)`
  / `entry_params.run(force=)` 전파. 단일 모드(`--mode=evaluate --force`)도 지원.
  ※ `--ticker` 는 weekend 전용(`_TICKER_SUPPORTED_MODES={"weekend"}`)이라 evaluate/entry 의
  `--force` 는 **항상 as_of 전체 종목** 대상.
- replace 동작: 해당 단계가 **그 스코프의 as_of 행을 먼저 DELETE 후 재분석**.
  - evaluate: `DELETE FROM trigger_evaluation_log WHERE COALESCE(analyzed_for_date,
    (evaluated_at AT TIME ZONE 'UTC')::date)=as_of`.
  - entry: `DELETE FROM entry_params WHERE COALESCE(analyzed_for_date, signal_at::date)=as_of` →
    **`signal_performance` ON DELETE CASCADE 로 해당 시그널 성과기록 동반 삭제**(재분석=옛 성과 폐기, 의도된 동작).

### 3.6 run 레이어 — duplicate 판정을 as_of 기준으로
- **프로덕션 경로 = `check_can_run_pipeline`**(웹 `/run` 라우터가 사용). `check_can_run`(모드기반)·
  `spawn_runner` 는 **현재 테스트 전용**(test_api_runner_service.py 만 사용) — 중복 로직을 **공유 헬퍼로
  추출**해 한 곳만 고치고 양쪽이 쓰게 한다(분기/누락 방지).
- 공유 헬퍼 `_resolve_as_of(conn, explicit_date)` 신설(= `--date`/date 있으면 그 값, 없으면
  `MAX(daily_indicators.date)`). `__main__` 과 check 함수가 **동일 로직 공유**.
  ※ 웹 full-daily 는 `--date` 를 안 넘기므로(spawn args=`--mode=full-daily`) check·러너 양쪽
  `_resolve_as_of(conn, None)=MAX(daily_indicators.date)` 로 자동 일치 → params/date 를 check 에
  따로 넘길 필요 없음.
- "duplicate" 판정 변경 (⚠ **backward-compat 결합 조건** — check_can_run_pipeline 은 *모든* 파이프라인
  공유인데 `as_of` 를 params 에 넣는 건 **llm_runner 뿐**. ohlcv/indicators/weekly/market_context/
  corporate_actions/universe/data_daily/data_weekly 는 미저장 → 순수 as_of 비교로 바꾸면 그들의
  duplicate 방지가 깨짐):
  - 기존: `status='success' AND (started_at AT TIME ZONE 'Asia/Seoul')::date = today`
  - 변경: **SELECT 에 `params` 추가** + 조건을
    `status='success' AND ( params->>'as_of' = prospective::text
        OR (params->>'as_of' IS NULL AND (started_at AT TIME ZONE 'Asia/Seoul')::date = today) )`.
    → LLM(as_of 있음): as_of 매칭(어느 날이든) — 오전(D-1)/오후(D) 다른 as_of=중복 아님, 같은 as_of=중복.
    비-LLM(as_of NULL): 기존 wall-clock today 유지(레거시 보존). pipeline/mode_prefix 매칭 그대로.
  - `running` 상태 체크(동시 실행 방지)는 **그대로 유지**(force 무관). force=True 면 duplicate 우회.
- ※ 의미 변화(개선): 데이터가 안 바뀐 채(예: 휴장일) 다음 날 재실행하면 같은 as_of 라 duplicate 로 막힘
  = 무의미 재분석 방지(기존엔 wall-clock 다르면 허용 후 stage no-op). 의도된 개선.

### 3.7 force 전파 (web → CLI)
- 라우터 `/run`(`runner.py`)은 이미 `force` 수신 → `check_can_run_pipeline(force=)` 에 전달(기존).
- **누락 보완**: `spawn_pipeline` 에 `force` 파라미터 추가 → CLI cmd 에 **bare `--force` append**
  (⚠ `--force` 는 store_true 라 generic `--{name}={value}` 메커니즘 쓰면 `--force=true` 로 argparse
  실패 → 반드시 `cmd += ["--force"] if force` 형태로). 라우터가 `req.force` 를 spawn 까지 전달.
  `spawn_runner`(테스트 전용)도 동일 시그니처로 정합.
- `__main__` 에 `--force`(store_true) 인자 신설 → `run_full_daily(force=)` / 단일모드 run(force=) 전파.
- web UI 토글 자체(프런트)는 범위 밖 — 백엔드 경로만 완성(기본 skip 안전).

## 4. 동작 특성 / 엣지
- **실패 종목 자연 재시도**: LLM 실패→rollback 된 종목은 행이 없어 skip 대상 아님 → 재실행 시 재처리.
  "존재 기반 skip"이 곧 "실패분만 이어서". (의도된 동작)
- **오전/오후 독립**: as_of 가 달라 run 레이어 duplicate 도 아니고(force 불필요), stage 의
  analyzed_for_date 도 달라 자동 분리.
- **legacy NULL**: COALESCE 로 evaluated_at::date fallback → 기존 행·테스트 비파괴.
- **limit**: skip 후 남은 후보에 적용(합리적).
- **동시 실행 방지는 그대로**: `check_can_run_pipeline` 의 `running` 상태 체크가 동시 실행을 계속
  차단(이번 변경은 그 아래 *duplicate(같은 날)* 판정만 as_of 기준으로 바꿈). stage-level read-then-act
  레이스는 순차 재실행 전제라 무관.
- **cron 은 run-게이트 우회**: OS crontab 이 CLI(`python -m kr_pipeline.llm_runner ...`)를 직접 호출
  → `check_can_run_pipeline` 미경유. 따라서 run-level duplicate 변경은 **웹 트리거 실행만** 영향.
  cron 과 수동 실행이 같은 as_of 로 겹쳐도 **stage-level skip 이 중복 분석/시그널을 방지**(여전히 보호).

## 5. 테스트 (TDD)
- **run 레이어**(`check_can_run_pipeline` 프로덕션 + `check_can_run` 테스트전용 — 공유헬퍼라 함께
  커버): 같은 as_of success 존재 시 duplicate, **다른 as_of success 만 있으면 can_run=ok**(오전/오후
  핵심), 레거시 NULL as_of 행은 무시, running 시 always 차단, force 시 우회. 기존
  test_api_runner_service 의 wall-clock 가정 케이스 갱신.
- **stage evaluate**: 같은 as_of 로 이미 trigger 행 있는 종목 skip / 없는 종목 처리.
- **stage entry**: `_fetch_go_now_candidates` 가 이미 entry_params 있는 종목 제외 + DISTINCT ON 중복 trigger 1건화.
- **오전/오후 독립**: as_of=D-1 처리 후 as_of=D 실행이 D-1 행을 건드리지 않고 독립 저장(run+stage 양쪽).
- **force replace**: 같은 as_of 행 삭제 후 재생성 + entry_params CASCADE 로 signal_performance 동반 삭제 확인.
- **force 전파**: spawn 이 `--force` 를 cmd 에 포함하는지(command 문자열 검증, subprocess 미실행).
- legacy NULL 행(analyzed_for_date 미지정 INSERT)이 COALESCE 로 계속 매칭. 레거시 run(params 무 as_of) fallback.
- 회귀: 기존 evaluate/entry/payload/performance/schema/runner_service 테스트 baseline 유지(net 0).

## 6. 후속 티켓
- **(B) performance 기준일 = analyzed_for_date** 로 교체(오전 케이스 하루 밀림 해소).
- web UI 설명문(`LlmPipelinePage.tsx`, `tables.ts`) analyzed_for_date / 매칭 기준 동기화.
- (선택) 과거 중복 행 일회 cleanup 마이그레이션.
