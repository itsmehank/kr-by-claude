# 일봉 데이터 적재 파이프라인 설계

- **상태**: Design
- **작성일**: 2026-05-15
- **범위**: 서브프로젝트 #1 (전체 시스템 중 데이터 적재 파이프라인)

## 1. 배경 및 목적

한국 KOSPI / KOSDAQ 보통주 일봉 OHLCV와 KOSPI / KOSDAQ 지수 일봉을 PostgreSQL에 적재하는 파이프라인. 후속 서브프로젝트 (지표 생성, UI, Claude Code CLI 자동 분석) 의 데이터 기반이 된다.

### 전체 시스템 분해 (참고)

| # | 서브프로젝트 | 의존성 |
|---|---|---|
| **1** | **일봉 / 지수 데이터 적재 파이프라인 (본 문서)** | 없음 |
| 1.5 | 주봉 데이터 적재 파이프라인 (일봉으로부터 생성) | 1 |
| 2 | 지표 생성 파이프라인 (SMA, 52w high/low, RS rating, RS line, 미너비니 템플릿) | 1, 1.5 |
| 3 | 웹 UI (히트맵, 차트, 미너비니 통과 종목, LLM 프롬프트/데이터 생성) | 1, 1.5, 2 |
| 4 | Claude Code CLI 자동 분석 (주 1회, entry / watch / ignore 분류) | 1, 1.5, 2, 3 |

본 문서는 **#1 일봉 / 지수** 만 다룬다. 주봉은 일봉을 입력으로 받아 생성하므로 별도 스펙 (#1.5) 으로 분리.

## 2. 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 데이터 소스 | pykrx |
| DB | PostgreSQL |
| 언어 | Python (uv 관리) |
| 실행 환경 | 로컬 / 개인 서버 + cron |
| 종목 범위 | KOSPI + KOSDAQ 보통주 (ETF / 리츠 / 우선주 제외) |
| 수정주가 처리 | 원가 + 수정종가 둘 다 저장, 월 1회 전체 재적재로 갱신 |
| 코드 구조 | 단일 패키지 `kr_pipeline` + 모드 인자 진입점 (Approach A) |
| 매일 적재 윈도우 | 지난 30일 upsert (Option A) |

## 3. 코드 구조

```
kr-by-claude/
├── pyproject.toml
├── kr_pipeline/
│   ├── __init__.py
│   ├── ohlcv/
│   │   ├── __main__.py          # python -m kr_pipeline.ohlcv 진입점
│   │   ├── modes.py             # backfill / incremental / full-refresh 분기
│   │   ├── fetch.py             # pykrx 호출 (rate limit, 재시도)
│   │   ├── transform.py         # 원가 / 수정종가 정규화, 종목 필터링
│   │   └── store.py             # upsert into Postgres
│   ├── universe/
│   │   ├── __main__.py          # 종목 마스터 갱신
│   │   └── fetch.py
│   ├── db/
│   │   ├── connection.py        # psycopg / SQLAlchemy 풀
│   │   ├── schema.sql           # DDL (단일 진실)
│   │   └── migrations/          # 추후 변경용 (alembic은 보류)
│   └── common/
│       ├── config.py            # .env → 설정 객체
│       ├── logging.py
│       └── retry.py             # tenacity 래퍼
├── tests/
│   ├── test_transform.py
│   ├── test_modes.py
│   └── test_integration.py
└── scripts/
    └── cron.example
```

### 핵심 원칙

- `fetch` (외부 IO) / `transform` (순수 함수) / `store` (DB IO) 명확히 분리
- `ohlcv` 와 `universe` 는 별도 진입점 — 책임 분리, 갱신 주기 다름
- DB 스키마는 `db/schema.sql` 한 곳에서 관리. 마이그레이션 도구 도입은 YAGNI

### 진입점

```bash
# 종목 마스터 갱신 (월 1회 + 백필 초회)
python -m kr_pipeline.universe

# 일봉 OHLCV
python -m kr_pipeline.ohlcv --mode=backfill --years=2
python -m kr_pipeline.ohlcv --mode=incremental --window-days=30
python -m kr_pipeline.ohlcv --mode=full-refresh
```

## 4. DB 스키마

```sql
-- 종목 마스터
CREATE TABLE stocks (
    ticker        VARCHAR(10)  PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    market        VARCHAR(10)  NOT NULL,           -- 'KOSPI' | 'KOSDAQ'
    sector        VARCHAR(100),
    listed_at     DATE,
    delisted_at   DATE,
    is_common     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_stocks_market ON stocks(market) WHERE delisted_at IS NULL;

-- 일봉 OHLCV
CREATE TABLE daily_prices (
    ticker        VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    date          DATE          NOT NULL,
    open          NUMERIC(12,2) NOT NULL,
    high          NUMERIC(12,2) NOT NULL,
    low           NUMERIC(12,2) NOT NULL,
    close         NUMERIC(12,2) NOT NULL,          -- 원가
    adj_close     NUMERIC(12,4) NOT NULL,          -- 수정종가
    volume        BIGINT        NOT NULL,
    value         BIGINT        NOT NULL,          -- 거래대금
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);
CREATE INDEX idx_daily_prices_date ON daily_prices(date);

-- 지수 일봉 (KOSPI, KOSDAQ)
CREATE TABLE index_daily (
    index_code    VARCHAR(10)   NOT NULL,           -- '1001'(KOSPI) | '2001'(KOSDAQ)
    date          DATE          NOT NULL,
    open          NUMERIC(12,2) NOT NULL,
    high          NUMERIC(12,2) NOT NULL,
    low           NUMERIC(12,2) NOT NULL,
    close         NUMERIC(12,2) NOT NULL,
    volume        BIGINT,
    value         BIGINT,
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code, date)
);

-- 적재 작업 로그
CREATE TABLE pipeline_runs (
    id            BIGSERIAL PRIMARY KEY,
    pipeline      VARCHAR(50)  NOT NULL,            -- 'ohlcv' | 'universe' | ...
    mode          VARCHAR(20)  NOT NULL,            -- 'backfill' | 'incremental' | 'full-refresh'
    started_at    TIMESTAMPTZ  NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        VARCHAR(20)  NOT NULL,            -- 'running' | 'success' | 'failed'
    rows_affected BIGINT,
    error         TEXT,
    params        JSONB
);
CREATE INDEX idx_pipeline_runs_recent ON pipeline_runs(pipeline, started_at DESC);
```

### 설계 결정 요지

- **`stocks.delisted_at`**: 매일 적재 대상은 `delisted_at IS NULL` 만. 폐지 종목 과거 데이터는 보존 → 후속 백테스팅에 의미
- **`adj_close` 만 `NUMERIC(12,4)`**: 수정 비율 누적 정밀도 보존. 원가는 원 단위라 `12,2` 면 충분
- **지수는 별도 테이블**: PK 가 다르고 (ticker 가 아닌 index_code) 의미가 다름
- **`pipeline_runs`**: cron 실패 추적용. 단순한 옵저버빌리티. UI 서브프로젝트 #3 에서 "최근 파이프라인 실행 현황" 페이지로 노출 예정
- **인덱스**: `daily_prices` 는 PK 외에 `(date)` 인덱스 — "특정 날짜의 모든 종목" UI 쿼리용

### 의도적으로 하지 않은 것 (YAGNI)

- alembic 마이그레이션 도구 도입
- 파티셔닝 (2년치 약 150만 행은 Postgres 인덱스만으로 충분)
- 별도 `corporate_actions` 테이블 (full-refresh 로 수정종가 보정)

## 5. 데이터 흐름

### `python -m kr_pipeline.universe`

종목 마스터 갱신. 월 1회 + 백필 초회.

1. `pykrx.get_market_ticker_list('YYYYMMDD', market='KOSPI' | 'KOSDAQ')`
2. 각 ticker → 이름 / 시장 / 섹터 조회 (`get_market_sector_classifications`)
3. 우선주 / 리츠 / ETF 필터 (이름 패턴 + 종목 코드 규칙)
4. UPSERT `stocks` (name, sector, updated_at 갱신)
5. 폐지 감지: 이전 실행엔 있었는데 이번 목록에 없는 ticker → `delisted_at = today`
6. `pipeline_runs` 기록

### `python -m kr_pipeline.ohlcv --mode=backfill --years=2`

최초 1회. 2년치 일봉 + 지수.

1. `start_date = today - 2년`, `end_date = yesterday`
2. 대상: `SELECT ticker FROM stocks WHERE delisted_at IS NULL`
3. 종목별로 pykrx 두 번 호출:
   - `get_market_ohlcv(start, end, ticker, adjusted=False)` → 원가
   - `get_market_ohlcv(start, end, ticker, adjusted=True)`  → 수정종가
4. `transform`: 두 결과 merge → `daily_prices` 행 생성
5. UPSERT `daily_prices` (배치 ~1,000 행 단위)
6. 지수: `get_index_ohlcv(start, end, '1001' | '2001')` → `index_daily` UPSERT
7. 진행률 로깅, 종목별 실패는 모아서 마지막에 1회 재시도
8. `pipeline_runs` 기록

### `python -m kr_pipeline.ohlcv --mode=incremental --window-days=30`

매일 cron. 장 마감 후 (예: 18:30 KST).

1. `start_date = today - 30일`, `end_date = today`
2. backfill 과 동일한 fetch 로직 (기간만 다름)
3. UPSERT `daily_prices`, `index_daily`
4. `pipeline_runs` 기록

### `python -m kr_pipeline.ohlcv --mode=full-refresh`

월 1회. 수정종가만 전체 재계산.

1. `start_date = (SELECT MIN(date) FROM daily_prices)`, `end_date = yesterday`
2. 종목별로 `get_market_ohlcv(start, end, ticker, adjusted=True)`
3. `UPDATE daily_prices SET adj_close = ?, updated_at = NOW() WHERE ticker = ? AND date = ?` — INSERT 안 함
4. `pipeline_runs` 기록

### 호출 패턴 & Rate Limiting

- pykrx 는 종목별 순차 호출. 2,500 종목 × 2 회 (원가 / 수정) = 5,000 호출
- 동시성: 동시 2~4 개 (`asyncio.Semaphore` 또는 `ThreadPoolExecutor`)
- 호출당 짧은 sleep (jitter 포함, 100~300ms)
- 예상 소요: backfill 1~2 시간, incremental ~30 분, full-refresh 백필과 유사
- **실제 측정 후 조정 필요** (위는 추정치)

### Cron 등록 예시

```cron
# 매일 18:30 KST, 일봉 incremental
30 18 * * 1-5  cd /home/me/kr-by-claude && uv run python -m kr_pipeline.ohlcv --mode=incremental --window-days=30

# 매월 1일 02:00, 수정종가 full-refresh
0  2 1 * *     cd /home/me/kr-by-claude && uv run python -m kr_pipeline.ohlcv --mode=full-refresh

# 매월 1일 04:00, 종목 마스터 갱신
0  4 1 * *     cd /home/me/kr-by-claude && uv run python -m kr_pipeline.universe
```

## 6. 에러 처리 / 재시도 / 멱등성

### 멱등성

- 모든 쓰기는 `INSERT ... ON CONFLICT ... DO UPDATE` (UPSERT)
- `full-refresh` 는 `UPDATE` 만 (없는 행은 무시)
- `universe.delisted_at` 감지는 이미 세팅된 행을 손대지 않음

### 재시도 전략

| 범위 | 정책 | 도구 |
|---|---|---|
| 개별 pykrx 호출 | 3 회 재시도, exponential backoff (1s → 2s → 4s) + jitter | tenacity |
| DB 트랜잭션 | 1 회 재시도 (lock contention 대응) | tenacity |
| 종목 단위 실패 | 모아두고 마지막에 1 회 재시도. 그래도 실패하면 로깅 후 진행 | 내부 `failed_tickers` |
| 파이프라인 전체 | 재시도 안 함. cron 다음 실행이 복구 | — |

### 부분 실패 처리

한두 종목 실패가 전체 파이프라인을 중단시키지 않음. `pipeline_runs.error` 에 실패 종목 목록 JSON 으로 저장. 다음 incremental 실행이 자연 복구.

### 트랜잭션 단위

- 종목 100 개 묶음 또는 ~10,000 행 단위로 1 트랜잭션
- 한 배치 실패해도 다른 배치는 커밋 → 부분 진행 보존

### 로깅

- `kr_pipeline.common.logging` 에서 JSON 한 줄 포맷 (timestamp / level / pipeline / mode / message)
- stdout 출력 → cron 이 파일 리다이렉트
- 별도 관찰 시스템 도입은 YAGNI

### 데이터 검증 (sanity check)

각 모드 종료 직전에 가벼운 검증. 이상 시 `pipeline_runs.error` 에 경고로 기록 (실패로는 안 침).

- 가장 최근 영업일 일봉이 들어온 종목 수가 평소 대비 80% 미만 → 경고
- `close <= 0` 또는 `adj_close <= 0` 행이 있는지

### 알림

- 별도 알림 시스템 없음. UI 서브프로젝트 #3 에서 `pipeline_runs` 페이지로 노출

## 7. 테스팅 전략

### 테스트 계층

| 계층 | 무엇을 테스트하나 | 도구 | 비중 |
|---|---|---|---|
| 단위 (transform) | 순수 함수 — 우선주 필터, 원가 / 수정종가 merge, 폐지 감지 | pytest | 가장 두텁게 |
| 단위 (modes) | 모드별 분기, 인자 파싱, 기간 계산 (fetch 는 mock) | pytest + mock | 적당히 |
| 통합 (DB) | 실제 Postgres 에 UPSERT 동작, PK 충돌 시 정확한 컬럼만 갱신 | pytest + testcontainers-python 또는 로컬 Postgres | 핵심만 |
| 외부 IO (fetch) | pykrx 호출 자체는 테스트 안 함 (외부 의존, flaky) | — | 안 함 |

### 단위 테스트 (예시)

```python
# tests/test_transform.py
def test_filter_common_stocks_excludes_preferred(): ...
def test_filter_common_stocks_excludes_etf_by_ticker_pattern(): ...
def test_merge_raw_and_adjusted_aligns_by_date(): ...
def test_merge_handles_missing_dates_gracefully(): ...

# tests/test_modes.py
def test_incremental_window_calculates_correct_range(freezer): ...
def test_full_refresh_only_updates_adj_close(mock_store): ...
def test_backfill_2_years_calculates_correct_range(freezer): ...
```

### 통합 테스트 (예시)

```python
# tests/test_integration.py
def test_upsert_preserves_other_columns_in_full_refresh(db): ...
def test_incremental_upsert_handles_conflict(db): ...
def test_delisted_detection(db): ...
```

### 테스트 DB

- `tests/conftest.py` 에 `db` fixture: 로컬 Postgres 에 매 테스트마다 트랜잭션 → 끝나면 ROLLBACK
- 스키마는 `db/schema.sql` 그대로 적용 (프로덕션 동일)

### 의도적으로 하지 않을 것

- pykrx fixture 녹화 (vcr.py 등): 외부 API 가 바뀌면 어차피 깨짐
- end-to-end 실제 cron 시뮬레이션
- 수정종가 정확성 검증 (pykrx 결과를 그대로 저장하는 것이므로 pykrx 신뢰)
- 커버리지 숫자 목표 (의미 있는 테스트만 작성)

### 개발 워크플로우

- TDD: 새 기능 / 버그 수정 시 실패하는 테스트 먼저 → 통과시키기
- transform 로직은 100% 단위 테스트 (외부 의존 없음)
- store 로직은 통합 테스트 (DB 거동 검증)

## 8. 범위 밖 (Out of Scope)

- 주봉 데이터 생성 / 적재 → 서브프로젝트 #1.5 (별도 스펙)
- 모든 지표 (SMA, 52w high/low, RS rating, RS line, 미너비니 템플릿) → 서브프로젝트 #2
- 웹 UI, 차트, 히트맵 → 서브프로젝트 #3
- Claude Code CLI 자동 분석 → 서브프로젝트 #4
- 실시간 / 분봉 데이터
- 알림 시스템 (이메일 / Slack / Discord)
- 종목 펀더멘털 (재무제표, 시가총액 등)

## 9. 후속 작업

본 스펙 승인 후:

1. `writing-plans` 스킬로 구현 계획 작성
2. 구현 계획에 따라 코드 작성 (TDD)
3. 검증 후 서브프로젝트 #1.5 (주봉) 또는 #2 (지표) 로 진행
