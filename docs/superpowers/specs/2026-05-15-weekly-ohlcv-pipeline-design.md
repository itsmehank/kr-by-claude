# 주봉 데이터 적재 파이프라인 설계

- **상태**: Design
- **작성일**: 2026-05-15
- **범위**: 서브프로젝트 #1.5 (전체 시스템 중 주봉 파이프라인)
- **선행 의존**: 서브프로젝트 #1 (일봉 / 지수 적재 파이프라인) — 완료됨

## 1. 배경 및 목적

서브프로젝트 #1 에서 적재된 일봉 `daily_prices` 및 지수 `index_daily` 를 입력으로, 주봉 `weekly_prices` 와 `weekly_index` 를 생성·적재한다. 외부 네트워크 호출 없이 **DB-to-DB** 로 동작.

후속 서브프로젝트 (#2 지표, #3 UI, #4 Claude Code CLI 분석) 가 주봉 데이터에 의존한다. 특히:
- 미너비니 템플릿의 일부 조건 (주봉 기준 SMA, 52주 고가 등)
- 오닐 스타일의 거시 추세 (월/주 단위)
- RS Line / RS Rating (지수 주봉 대비 종목 주봉)

### 전체 시스템 분해 (참고)

| # | 서브프로젝트 | 상태 |
|---|---|---|
| 1 | 일봉 / 지수 데이터 적재 파이프라인 | ✅ 완료 |
| **1.5** | **주봉 데이터 적재 파이프라인 (본 문서)** | Design |
| 2 | 지표 생성 파이프라인 | 미시작 |
| 3 | 웹 UI | 미시작 |
| 4 | Claude Code CLI 자동 분석 | 미시작 |

## 2. 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 아키텍처 | Python 파이프라인 (`kr_pipeline.weekly`), #1 과 동일 패턴 |
| 입력 | `daily_prices`, `index_daily` (PostgreSQL, #1 에서 적재됨) |
| 출력 | `weekly_prices`, `weekly_index` (신규 테이블) |
| 주봉 날짜 표기 | 그 주 마지막 영업일 (대개 금요일). `week_end_date` 컬럼 |
| 미완성 주 | 제외 — 완료된 주만 적재 |
| 적재 모드 | `backfill`, `incremental`, `full-refresh` (#1 과 1:1 대응) |
| 처리 방식 | 종목 하나씩 순차 처리 (메모리 ~100KB, 부분 실패 격리) |
| 외부 IO | 없음 (DB-to-DB), pykrx 호출 0 |

## 3. 코드 구조

```
kr_pipeline/
├── weekly/
│   ├── __init__.py
│   ├── __main__.py          # python -m kr_pipeline.weekly 진입점
│   ├── modes.py             # backfill / incremental / full-refresh 분기
│   ├── transform.py         # 일봉 → 주봉 집계 (순수 함수)
│   └── store.py             # weekly_prices / weekly_index UPSERT
└── (기존 ohlcv/, universe/, common/, db/ 그대로)

tests/
├── test_weekly_transform.py # 집계 로직 단위 테스트 (가장 두텁게)
├── test_weekly_modes.py     # 모드 분기 + 윈도우 계산
└── test_weekly_store.py     # UPSERT 동작 (통합)
```

### 핵심 원칙 (#1 과 동일)
- `transform` (순수 함수, 외부 IO 없음 — 입력: 일봉 `pd.DataFrame`, 출력: 주봉 `pd.DataFrame`) → 테스트의 90%
- `store` (DB UPSERT)
- `modes` (분기 + 일봉 SELECT + transform + store 호출)
- 단일 진입점, 모드 인자 (Approach A)

**`fetch` 모듈 없음** — pykrx 호출 안 함. 일봉 DB 가 입력.

### 진입점

```bash
# 1회성 백필 — 모든 완료된 주 생성
python -m kr_pipeline.weekly --mode=backfill

# 매주 증분 — 최근 N 주 재생성 (늦은 일봉 보정 흡수)
python -m kr_pipeline.weekly --mode=incremental --window-weeks=4

# 일봉 full-refresh 이후 — 수정종가 변경 흡수
python -m kr_pipeline.weekly --mode=full-refresh
```

**3 개 모드가 일봉과 1:1 대응**:

| 일봉 (#1) | 주봉 (#1.5) |
|---|---|
| `backfill --years=2` (2 년치 일봉) | `backfill` (그 2 년치의 주봉 생성) |
| `incremental --window-days=30` (지난 30 일) | `incremental --window-weeks=4` (지난 4 주) |
| `full-refresh` (수정종가 갱신) | `full-refresh` (수정종가 변경된 주봉 재생성) |

## 4. DB 스키마

```sql
-- 종목 주봉 OHLCV
CREATE TABLE weekly_prices (
    ticker          VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    week_end_date   DATE          NOT NULL,        -- 그 주 마지막 영업일 (보통 금요일)
    open            NUMERIC(12,2) NOT NULL,        -- 그 주 첫 영업일 open
    high            NUMERIC(12,2) NOT NULL,        -- 주중 최고가
    low             NUMERIC(12,2) NOT NULL,        -- 주중 최저가
    close           NUMERIC(12,2) NOT NULL,        -- 마지막 영업일 close
    adj_close       NUMERIC(12,4) NOT NULL,        -- 마지막 영업일 adj_close
    volume          BIGINT        NOT NULL,        -- 주중 거래량 합
    value           BIGINT        NOT NULL,        -- 주중 거래대금 합
    trading_days    SMALLINT      NOT NULL,        -- 그 주 실제 거래일 수 (보통 5)
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, week_end_date)
);
CREATE INDEX idx_weekly_prices_date ON weekly_prices(week_end_date);

-- 지수 주봉 (KOSPI, KOSDAQ)
CREATE TABLE weekly_index (
    index_code      VARCHAR(10)   NOT NULL,
    week_end_date   DATE          NOT NULL,
    open            NUMERIC(12,2) NOT NULL,
    high            NUMERIC(12,2) NOT NULL,
    low             NUMERIC(12,2) NOT NULL,
    close           NUMERIC(12,2) NOT NULL,
    volume          BIGINT,                          -- 지수 거래량 (nullable)
    value           BIGINT,                          -- 지수 거래대금 (nullable)
    trading_days    SMALLINT      NOT NULL,
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code, week_end_date)
);
```

### 설계 결정 요지

- **`week_end_date` 컬럼명**: `date` 라고만 두면 의미가 모호. "주봉의 날짜" 임을 컬럼명에서 명확히.
- **`trading_days` 추가**: 그 주에 실제 몇 영업일이 있었는지 (보통 5, 명절 주는 3~4). 향후 지표 (#2) 에서 "정상 주" 필터링용. `SMALLINT`.
- **`adj_close`**: 마지막 영업일의 `daily_prices.adj_close` 그대로 사용. 자체 계산 안 함. `NUMERIC(12,4)` 유지.
- **`pipeline_runs` 재사용**: 별도 weekly 로그 테이블 없음. `pipeline='weekly'` 로 기록.
- **`schema.sql` 에 추가**: `kr_pipeline/db/schema.sql` 끝에 두 테이블 DDL 추가. 단일 진실 유지.

### 의도적으로 안 한 것 (YAGNI)

- 월봉 테이블 → #2 또는 별도 결정
- `week_start_date` 컬럼 → `week_end_date` 만으로 충분 (계산 가능)
- 별도 view (`v_weekly_with_indicators`) → #2 에서

## 5. 데이터 흐름

### 공통: 주 경계 계산

pykrx 는 휴장일을 자동으로 빼고 데이터를 주므로, `groupby(ISO_week)` 후 `max(date)` 로 그 주 마지막 거래일을 얻으면 KRX 휴장 캘린더를 따로 관리할 필요 없음.

```python
# transform.py 핵심 로직
def assign_week_end(daily_df: pd.DataFrame) -> pd.DataFrame:
    """각 일봉 행에 그 주의 마지막 거래일 (week_end_date) 부착."""
    period = pd.to_datetime(daily_df["date"]).dt.to_period("W-SUN")  # ISO 주
    by_week = daily_df.assign(_w=period).groupby("_w")["date"].transform("max")
    return daily_df.assign(week_end_date=by_week)
```

### 미완성 주 제외

```python
def is_week_complete(week_end_date: date, today: date) -> bool:
    """그 주 마지막 거래일이 '확정' 인가?
    
    조건: today 가 그 주 일요일 이후 (= 다음 주 시작) 이면 그 주는 끝남.
    예: week_end_date=2026-05-15 (금), today=2026-05-18 (월) → True
    """
```

매주 incremental 실행 시점 (보통 토요일 03:00) 에 지난 주가 완료된 것으로 판정됨.

### `python -m kr_pipeline.weekly --mode=backfill`

```
1. start = (SELECT MIN(date) FROM daily_prices), end = today - 1
2. tickers = SELECT ticker FROM stocks WHERE delisted_at IS NULL
3. 종목별 순차 처리:
   a. daily_df = SELECT * FROM daily_prices WHERE ticker=? AND date BETWEEN start..end
   b. weekly_df = aggregate_to_weekly(daily_df)
   c. drop_incomplete_weeks(weekly_df, today)
   d. UPSERT weekly_prices, conn.commit() per ticker
4. 지수도 같은 방식 (index_daily → weekly_index, '1001'/'2001')
5. run_tracking + sanity checks → pipeline_runs 기록
```

### `python -m kr_pipeline.weekly --mode=incremental --window-weeks=4`

```
1. cutoff = today - (window_weeks * 7) 일
2. 일봉 SELECT 시 WHERE date >= cutoff
3. 나머지 backfill 과 동일
4. UPSERT (기존 행 overwrite — 늦은 일봉 보정 흡수)
```

**왜 4 주?** 일봉의 30 일 incremental 윈도우와 정렬. 일봉 보정이 30 일 내 흡수되므로 영향 주봉 (~4 주) 도 같이 재생성.

### `python -m kr_pipeline.weekly --mode=full-refresh`

```
1. 전체 일봉 SELECT (이미 수정종가가 갱신된 상태로 가정 — 일봉 full-refresh 가 선행)
2. 전체 기간 주봉 재생성 → UPSERT
```

**언제 실행?** 매월 1 일 새벽, 일봉 `--mode=full-refresh` (02:00) 가 끝난 후 (03:00).

### 처리 방식: 종목별 순차 (Option A)

- 한 번에 한 종목치 일봉 (~500 행, ~80 KB) 만 메모리에 올림
- 종목 단위 트랜잭션 (한 종목 실패해도 다른 종목 보존)
- 진행률 로깅 자연스러움 ("1500/2550 진행 중")
- 외부 네트워크 없으므로 단일 스레드로 충분 — `ThreadPoolExecutor` 불필요

### Cron 등록 추가

`scripts/cron.example` 에 추가:

```cron
# 매주 토요일 03:00, 지난 주 주봉 incremental
0 3 * * 6  cd $PROJECT_DIR && uv run python -m kr_pipeline.weekly --mode=incremental --window-weeks=4 >> $LOG_DIR/weekly.log 2>&1

# 매월 1일 03:00, 주봉 full-refresh (일봉 full-refresh 02:00 이후)
0 3 1 * *  cd $PROJECT_DIR && uv run python -m kr_pipeline.weekly --mode=full-refresh >> $LOG_DIR/weekly.log 2>&1
```

## 6. 에러 처리 / 재시도 / 멱등성

### 멱등성
- 모든 쓰기는 UPSERT — 같은 모드를 여러 번 돌려도 결과 동일
- PK = `(ticker, week_end_date)` / `(index_code, week_end_date)`
- `ON CONFLICT DO UPDATE` 로 모든 컬럼 갱신

### 종목 단위 부분 실패 + 끝-of-run 1 회 재시도

#1 의 OHLCV `_run_full_refresh` 와 동일 패턴:

```
1차 루프: 종목 모두 시도 → 실패 종목 모음
끝나면 → 실패 종목 1 회 재시도 → 최종 실패 종목 pipeline_runs.error 기록
```

**왜 재시도?** 네트워크는 없지만 DB lock contention 같은 일시적 이슈 가능. #1 과 일관된 패턴 유지.

### 트랜잭션 단위
- 종목 단위 commit (한 종목 처리 → commit → 다음 종목)
- 한 종목 실패해도 다른 종목 보존

### Sanity 검증

#1 의 `_run_sanity_checks` 패턴 재사용:

1. **커버리지**: `weekly_prices` 의 가장 최근 `week_end_date` 종목 수가 `daily_prices` 같은 주 종목 수 대비 **90% 미만** 이면 경고 (일봉의 80% 보다 엄격 — 일봉이 다 들어왔으면 주봉도 다 만들어져야 정상)
2. **가격 이상치**: `close <= 0` 또는 `adj_close <= 0` 행
3. **거래일 수 이상**: `trading_days = 0` 인 행 (이론상 없어야 함)

경고는 `pipeline_runs.error` 에 JSON, status 는 success 유지.

### 로깅
- 종목 100 개마다 progress 로그
- 최종 `DONE successes=N failures=M sanity_warnings=K`
- 실패 종목 상위 20 개 WARN 로그

### 의도적으로 안 한 것

- Multi-thread/process 처리 (DB IO + CPU 변환, GIL 영향, 의미 없음)
- 별도 알림 (`pipeline_runs` → UI 에서 확인)
- 강제 일관성 검증 (`weekly.close == 마지막 daily.close` 같은 cross-table 검증) — sanity check 로 충분, YAGNI

## 7. 테스팅 전략

### 테스트 계층

| 계층 | 무엇을 테스트하나 | 비중 |
|---|---|---|
| 단위 (transform) | 주 경계, 휴일 처리, 미완성 주 제외, OHLCV 집계 | 가장 두텁게 (~10) |
| 단위 (modes) | 모드 분기, 윈도우 계산, 일봉 SELECT 범위 | 적당히 (~4) |
| 통합 (DB) | 실제 Postgres UPSERT, full-refresh 갱신, 부분 실패 | 핵심만 (~3) |
| 외부 IO | 없음 (네트워크 호출 없음) | — |

### transform 단위 테스트 (예시)

```python
# tests/test_weekly_transform.py
def test_aggregate_single_full_week(): ...           # 월~금 5일 → 1주
def test_aggregate_holiday_week_4_days(): ...        # 월 휴장, 화~금 → trading_days=4
def test_aggregate_holiday_at_end_thursday_closes_week(): ...  # 금 휴장
def test_aggregate_multiple_weeks_split_correctly(): ...  # 2주치 → 2주봉
def test_drop_incomplete_weeks(): ...                # 진행 중 주 제외
def test_keep_completed_weeks_only(): ...
def test_adj_close_takes_last_day_value(): ...
def test_volume_sums_correctly_with_some_zero_days(): ...
def test_empty_daily_returns_empty_weekly(): ...
def test_to_weekly_rows_tuple_format(): ...
```

### modes 단위 테스트

```python
# tests/test_weekly_modes.py
@freeze_time("2026-05-18")
def test_incremental_window_4_weeks_range(): ...     # today=Mon → cutoff = today - 28일
def test_backfill_uses_db_min_to_yesterday(): ...
def test_full_refresh_same_as_backfill_range(): ...
def test_modes_run_routes_to_correct_handler(mocker): ...
```

### 통합 테스트

```python
# tests/test_weekly_integration.py (marker: integration)
def test_backfill_then_incremental_idempotent(db): ...  # 같은 결과 유지
def test_full_refresh_picks_up_adj_close_changes(db): ...
def test_partial_failure_does_not_corrupt_others(db): ...
```

### 개발 워크플로우
- TDD: transform 함수 하나 만들 때마다 실패 테스트 먼저 → 통과
- transform 은 100% 단위 테스트로 검증 (순수 함수)
- store 는 통합 테스트로 검증

### 의도적으로 안 할 것

- pykrx 호출 mock (호출 안 함)
- 성능 벤치마크 (분 단위 작업, 의미 없음)
- `run_tracking` 직접 테스트 (#1 에서 검증 끝)

## 8. 범위 밖 (Out of Scope)

- 월봉 / 분봉 생성 → 별도 (필요 시 #2 안에서)
- 지표 계산 (SMA, RS Rating 등) → 서브프로젝트 #2
- 웹 UI 노출 → 서브프로젝트 #3
- 차트 이미지 생성 → 서브프로젝트 #3 또는 #4
- LLM 분석 입력 데이터 포맷 → 서브프로젝트 #3 또는 #4
- 일봉 보정 (#1 이 담당)

## 9. 후속 작업

본 스펙 승인 후:

1. `writing-plans` 스킬로 구현 계획 작성
2. `subagent-driven-development` 으로 구현 (#1 과 동일 패턴)
3. 검증 후 서브프로젝트 #2 (지표 생성) 진행
