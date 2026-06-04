# P1 — 데이터 파이프라인 통합(A/B) + 조정 드리프트 자동 재적재 설계

날짜: 2026-06-04
대상: 신규 `kr_pipeline/pipeline/`, `kr_pipeline/llm_runner/pipeline_specs.py`, `api/routers/pipelines.py`·`web/src/pages/PipelinePage.tsx`(메타 표시), 기존 `ohlcv`/`weekly`/`indicators` 모듈은 호출만(무수정)

## 배경 / 문제

현재 데이터 파이프라인 4개(ohlcv, weekly, indicators-daily, indicators-weekly)는 **각자 별도 cron**으로 돈다(평일 18:30/19:00, 토 03:00/04:00). "가격→지표" 순서가 코드로 보장되지 않고 **cron 시간차에 의존**한다. `depends_on`은 **강제 실행이 아니라 UI 표시용 메타데이터**일 뿐(코드 확인: `api/routers/pipelines.py`·`web/PipelinePage.tsx`에서만 소비, 실행을 막거나 대기하는 로직 없음). 그래서 선행이 늦거나 안 돌면 후행은 실패가 아니라 **낡은/빈 데이터로 잘못 동작**한다.

또한 분할(조정) 발생 시 과거 전 기간 adj_*가 바뀌어야 하는데, 증분(최근 30일)만 도는 일상 파이프라인은 **과거를 자동으로 못 따라간다**(현재는 수동 full-refresh 필요).

## 목표

1. **통합 A(daily)·B(weekly)**: "가격→지표"를 한 프로세스에서 순서대로 실행해 순서를 코드로 보장.
2. **드리프트 자동 재적재**: 통합 A에서 분할을 감지하면 그 종목만 전 기간 full-refresh(daily) + weekly cascade.
3. cron/runners 자동화를 통합 2개로 이전(기존 4개는 비예약 유지), UI 메타데이터를 새 구조에 맞게 최소 정리.

## 비목표 (Non-goals)

- corporate-actions·market-context·llm-* 통합/스케줄 변경 (별도 영역, 그대로 둠).
- 기존 4개 spec id **삭제**(다른 파이프라인 depends_on이 참조 → 그래프·테스트 깨짐). 대신 비예약화.
- 깊은 의존성 시각화(트리 중첩 등) — 후속.
- 전 종목 재계산(드리프트는 **감지된 종목만** 재적재).
- `ohlcv`/`weekly`/`indicators` 모듈 내부 로직 변경(호출만).

## 핵심 결정 (브레인스토밍 합의)

1. **"교체"의 현실적 형태**: 통합 A·B에 cron 부여, 기존 4개는 `default_cron=""`(비예약) + `component_of` 표식. id 유지 → depends_on 그래프·무결성 테스트 무손상.
2. **드리프트 수정 = 제자리 full-refresh**(삭제-재적재 아님). 모든 지표가 adj_* 기반이라 adj 재수신+재계산으로 완전 갱신(raw 불변, P0에서 검증).
3. **드리프트 감지 = 30일 adj_close 겹침 비교** → 겹침 없으면 365일 확대 → 그래도 없으면 pass(신규/상장폐지).

## 아키텍처

### 1. 통합 오케스트레이터 — `kr_pipeline/pipeline/`
- `chains.py`:
  - `run_daily_chain(conn, *, drift=True, limit_tickers=None)`:
    1. **드리프트 감지** (아래 §2) — ohlcv 증분이 adj_close를 덮어쓰기 **전에** DB(현재) vs KRX 비교 → 분할 종목 목록.
    2. `ohlcv.run(conn, Mode.INCREMENTAL, ...)` (증분 적재 — raw+adjusted)
    3. **드리프트 cascade** — 1에서 감지된 종목만 full-refresh(daily) + weekly cascade(아래 §2)
    4. `indicators.run_daily(conn, Mode.INCREMENTAL, ...)`
  - `run_weekly_chain(conn, *, limit_tickers=None)`:
    1. `weekly.run(conn, Mode.INCREMENTAL, ...)`
    2. `indicators.run_weekly(conn, Mode.INCREMENTAL, ...)`
- `__main__.py`: `python -m kr_pipeline.pipeline --chain=daily|weekly [--limit-tickers N] [--no-drift]`.
- 기존 `ohlcv.run`/`weekly.run`/`indicators.run_daily`/`run_weekly`를 **그대로 호출**. 한 단계가 예외 시 로깅 후 다음 단계 진행 여부는 보수적으로: ohlcv 실패해도 indicators는 기존 데이터로 의미 없으니, **단계 실패는 로그+계속**하되 chain 결과에 단계별 stats 집계(기존 모듈도 종목별 실패를 failures로 모음).

### 2. 드리프트 감지 + cascade — `pipeline/drift.py`
- **반드시 ohlcv 증분 적재 전에 실행** — 증분이 최근 30일 adj_close 를 분할-후 값으로 덮어쓰면, "DB vs KRX" 비교가 (둘 다 분할-후라) 일치해 분할을 놓친다. 감지는 **덮어쓰기 전 DB(분할-전 잔존) 값**과 새 KRX(분할-후) 값을 비교해야 한다.
- `detect_drifted_tickers(conn, as_of, tolerance) -> list[str]`:
  - 각 활성 종목: DB의 최근 30일 `daily_prices.adj_close`(아직 덮어쓰기 전) vs `fetch_adj_only(30일)` 결과를 비교.
  - 핵심 판정은 순수 함수: `is_drift(db_adj: dict[date,float], krx_adj: dict[date,float], tol) -> bool` — **겹치는 날짜**(DB·KRX 둘 다 있는 날)에서 |db-krx|>tol 이면 True. 겹침 0이면 365일 확대 비교(호출부), 그래도 0이면 False(pass).
  - 분할 발생 시: 분할은 전 기간 adj_close 를 같은 배수로 바꾸므로, 최근 30일 겹침 날짜에서도 차이가 드러난다(증분 덮어쓰기 전이므로).
- `reload_ticker(conn, ticker)`:
  - daily: `fetch_adj_only(ticker, full_range)` → `update_adj_prices` → 그 종목 daily 지표 재계산.
  - weekly cascade: 그 종목 weekly 재집계(`aggregate_to_weekly`) → upsert → weekly 지표 재계산.
- 평상시 분할 0건이면 cascade 없음(증분만).

### 3. pipeline_specs / cron / 메타 UI
- 신규 spec 2개: `data-daily`(group=data, cron 평일, depends_on=["corporate-actions"]), `data-weekly`(cron 토, depends_on=["data-daily"]). pipeline_db_name 각 `data_daily`/`data_weekly`. modes: 통합 실행 args.
- 기존 4개: `default_cron=""`(비예약), 신규 필드 `component_of`(ohlcv·indicators-daily→"data-daily"; weekly·indicators-weekly→"data-weekly").
- `api/routers/pipelines.py`: 응답에 `component_of` 전달(있으면). `web/PipelinePage.tsx`: `component_of` 있는 카드는 "○○ 팀의 부품(수동)"으로 구분 표시(그룹/배지). 깊은 트리 없음.
- depends_on/consumed_by 기존 로직·이름 그대로 → 무결성 유지.

### 4. 스케줄
- `data-daily`: 평일 장마감 후(기존 ohlcv 18:30 + indicators 19:00 자리 → 예: 18:30 시작, 내부에서 순차). `data-weekly`: 토요일(기존 03:00/04:00 자리).
- market-context(평일 19:30)·llm-*(20:00 등) cron 불변 → 통합 A 뒤 자기 시간에 실행.

## 구현 노트
- **순서가 핵심**: detect(§2)는 ohlcv 증분 **전에** 실행해 "DB 현재 adj_close(30일) vs KRX 재조회(30일)"를 비교한다. 증분이 먼저 덮어쓰면 비교가 일치해 분할을 놓친다.
- **KRX 비용**: detect 가 종목별 30일 adj 재조회(`fetch_adj_only`)를 하므로, 그날 ohlcv 증분과 합쳐 KRX 호출이 늘어난다(detect 30일 + 증분). 평일 1회·장마감 후라 감내 가능. (최적화 여지: 증분 fetch 결과를 detect 와 공유 — 단 ohlcv 모듈 무수정 원칙상 우선 별도 조회로 시작.)
- detect 는 ohlcv 증분과 독립적으로 "DB vs KRX" 비교라 순서·구현이 단순·견고.

## 테스트
- `is_drift` 순수 함수: 겹침에서 차이>tol→True, 동일→False, 겹침0→False(확대는 호출부).
- `run_daily_chain`/`run_weekly_chain`: 모듈 run을 mock 해 **순서대로 호출**되는지, drift=False 시 cascade 미호출, 한 단계 실패 시 처리.
- `reload_ticker`: 단일 종목 daily+weekly full-refresh 경로(mock fetch).
- pipeline_specs: 신규 2개 필드 완비, 기존 4개 cron=""·component_of, depends_on 무결성, `data-weekly` depends_on data-daily.
- `pipelines.py` 응답에 component_of, cron 생성이 빈-cron 스킵(P0의 `get_default_cron_lines` 가드 재사용).
- baseline 회귀 0(base↔HEAD 비교).

## 파일 변경 예상
- 신규: `kr_pipeline/pipeline/__init__.py`, `chains.py`, `drift.py`, `__main__.py`.
- 변경: `kr_pipeline/llm_runner/pipeline_specs.py`(신규 2 spec + 기존 4 cron=""·component_of), `api/routers/pipelines.py`(component_of 전달), `web/src/pages/PipelinePage.tsx`+`web/src/lib/types.ts`(component_of 표시).
- 테스트: `tests/test_pipeline_chains.py`(신규), `tests/test_pipeline_drift.py`(신규), `tests/test_pipeline_specs.py`(갱신).
