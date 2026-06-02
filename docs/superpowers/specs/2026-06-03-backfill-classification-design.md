# 과거 시점 백필/백테스트 분류 — 별도 테이블 + 실행 경로

설계일: 2026-06-03
범위: sub-project ③ (3분해 중 마지막). ①(최신판정 축, 완료·main) · ②(on_date 시계열 정합화, 완료·main) 기반.

## 배경 / 목적

과거 특정 시점 기준으로 LLM 분류를 재현(백필/백테스트)하되, 그 결과가 라이브의 "현재 분류 상태"를 오염시키지 않게 한다. ①②가 기반을 깔았다:
- ② — 차트·CSV 빌더가 `on_date` 를 존중 → 과거 시점 데이터로 분석 가능.
- ① — 라이브 "현재 상태" 판정이 `analyzed_for_date` 축 (단 백필은 별도 테이블이라 라이브 소비처가 아예 안 봄).

③은 "과거 한 날짜를 정확히 백필 테이블에 넣는" 실행 경로를 만든다.

## 핵심 결정 (브레인스토밍 확정)

- **단일 날짜/실행** (A): 한 번 실행 = 과거 한 시점. 기간 스윕은 비범위.
- **라이브 테이블 미러** (A): `classification_backfill` 은 `weekly_classification` 과 동일 컬럼 구성.
- **멱등 skip** (C): 식별키 `(symbol, analyzed_for_date)`, `ON CONFLICT DO NOTHING` → 중단 후 재실행 시 남은 것만 채움.
- **freeze 저장 생략**: 백필은 입력 ZIP 아카이브를 남기지 않음.

## 실행 방식

```
python -m kr_pipeline.llm_runner --mode=backfill --date=2025-09-30
```
- `--date` **필수**: backfill 모드인데 `--date` 미지정 시 `parser.error` 로 차단 (과거 날짜 없는 백필은 무의미·위험).
- `__main__.py` 는 이미 `--date` → `as_of` 를 계산. `--mode` choices 와 `PIPELINE_DB_NAME_BY_MODE` 에 `backfill` → `llm_backfill` 추가.
- `run_tracking(pipeline="llm_backfill", mode="backfill")` 로 `pipeline_runs` 기록 → runners 페이지에 라이브와 구분 표시.

## 한 종목 처리 (`backfill._process_one`)

1. 후보: `get_qualifying_tickers(conn, as_of)` (그 날짜의 minervini 통과 종목 — weekend 와 동일 함수). **이미 그 as_of 로 백필된 종목(`classification_backfill` 에 `(symbol, analyzed_for_date=as_of)` 존재)은 후보에서 제외** → 재개 시 LLM 을 다시 호출하지 않음(비용 절약). `ON CONFLICT (symbol, analyzed_for_date) DO NOTHING` 은 동시성/경합 대비 안전망(backstop).
2. `zip_bytes = build_analysis_zip(conn, symbol, on_date=as_of)` ← ②의 on_date 사용 (과거 차트·CSV).
3. `result = call_claude(prompt_file="analyze_chart_v3.md", attachments=[zip], dry_run=dry_run)` (라이브와 같은 프롬프트).
4. `insert_backfill_classification(conn, symbol=symbol, classified_at=now, analyzed_for_date=as_of, market, result, source="backfill", llm_meta=...)`.
5. 종목별 `conn.commit()` (중단 시 거기까지 보존). 예외 시 rollback + 실패 목록.
6. **freeze 저장 안 함.**

## 테이블 `classification_backfill`

`weekly_classification` 과 동일 컬럼 (symbol, classified_at, market, classification, pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date, risk_flags jsonb, confidence, reasoning, source, llm_call_duration_s, llm_input_tokens, llm_output_tokens, created_at, analyzed_for_date, triggered_rules jsonb, measurements jsonb).

차이:
- **PK/UNIQUE = `(symbol, analyzed_for_date)`** (라이브는 `(symbol, classified_at)`).
- `analyzed_for_date` **NOT NULL** (백필은 항상 기준일 보유).
- `schema.sql` 에 `CREATE TABLE IF NOT EXISTS classification_backfill (...)` 추가 + DB 적용.

## 저장 로직 `store.insert_backfill_classification`

`store.py` 에 신규 함수. `insert_classification` 과 동일하게 `apply_phase1_gates(conn, symbol, classified_at, result)` 를 적용(라이브와 동일 충실도)한 뒤, **`classification_backfill`** 에 INSERT, `ON CONFLICT (symbol, analyzed_for_date) DO NOTHING`. 컬럼/파라미터는 `insert_classification` 미러 + analyzed_for_date NOT NULL 전달.

## 격리 (오염 차단)

①에서 "현재 상태"를 읽는 6개 소비처(classifications API, get_active_monitoring, get_classified_losing_minervini, zip_builder._fetch_latest_analysis_result, payload_lite ×2, freeze_cleanup)는 전부 `weekly_classification` 만 조회. `classification_backfill` 은 새 테이블이라 **구조적으로 안 보임** → 라이브 현재 뷰 오염 불가능. (코드 규율이 아니라 스키마 분리가 보장.)

## 비범위 (Out of scope)

- 기간 스윕(여러 날짜 자동 루프) — 단일 날짜만. 반복은 셸/후속.
- 백테스트 평가·비교 UI ("과거 watch 가 실제로 올랐나") — 별도 후속(④).
- 라이브 러너(weekend/daily_delta) 변경 — 백필은 독립 경로, 라이브 무변경.
- freeze 저장 — 생략.
- 백필 결과를 보여주는 web 페이지 — 비범위(테이블 적재까지만).

## 테스트 전략 (real DB, TDD)

1. **적재**: `backfill.run(conn, as_of=과거)` → `classification_backfill` 에 행, `analyzed_for_date=as_of`, `source='backfill'`, `classified_at` 은 실행 시각(now 근처). (dry_run=False, mock LLM 또는 dry_run 경로 활용 — call_claude 가 dry_run mock 지원.)
2. **멱등(핵심)**: 같은 as_of 2회 실행 → 2회차 신규 0건(건수 불변).
3. **격리(핵심)**: 백필 행 삽입 후 `GET /api/classifications` (weekly_classification 조회)에 그 symbol 이 **없음**.
4. **on_date 결선**: `backfill._process_one` 이 `build_analysis_zip` 를 `on_date=as_of` 로 호출 (dry_run + spy/monkeypatch 로 인자 확인, 또는 통합적으로 zip 내용이 as_of 이하임 확인).
5. **--date 필수**: `--mode=backfill` + `--date` 없음 → `parser.error`(SystemExit).
6. **스키마**: `classification_backfill` 존재 + PK `(symbol, analyzed_for_date)` (test_schema 류).
7. **회귀**: `uv run pytest tests/` baseline(~26 isolation fail) 불변.

## 영향받는 파일 요약

- `kr_pipeline/db/schema.sql` (CREATE TABLE classification_backfill)
- `kr_pipeline/llm_runner/backfill.py` (신규 — run + _process_one)
- `kr_pipeline/llm_runner/store.py` (insert_backfill_classification 신규)
- `kr_pipeline/llm_runner/__main__.py` (mode choices + PIPELINE_DB_NAME_BY_MODE + --date 필수 검증 + 라우팅)
- 테스트: `tests/test_llm_backfill.py` (신규), `tests/test_schema_*` (백필 테이블), `tests/test_api_classifications.py` (격리)
