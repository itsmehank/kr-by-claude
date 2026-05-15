# 지표 생성 파이프라인 설계

- **상태**: Design
- **작성일**: 2026-05-16
- **범위**: 서브프로젝트 #2 (전체 시스템 중 지표 생성 파이프라인)
- **선행 의존**: 서브프로젝트 #1 (일봉/지수), #1.5 (주봉) — 완료됨

## 1. 배경 및 목적

서브프로젝트 #1, #1.5 에서 적재된 일봉/주봉/지수 데이터를 입력으로, 미너비니/오닐 framework 의 핵심 지표를 생성·적재한다. 외부 네트워크 호출 없이 **DB-to-DB** 로 동작.

후속 서브프로젝트 의존:
- #3 (UI) — 차트 오버레이, 미너비니 통과 종목 페이지, RS Rating 히트맵 등
- #4 (Claude Code CLI 자동 분석) — 미너비니 통과 + RS Rating ≥ 80 종목을 분석 대상으로 선별

### 전체 시스템 분해 (참고)

| # | 서브프로젝트 | 상태 |
|---|---|---|
| 1 | 일봉/지수 데이터 적재 파이프라인 | ✅ 완료 |
| 1.5 | 주봉 데이터 적재 파이프라인 | ✅ 완료 |
| **2** | **지표 생성 파이프라인 (본 문서)** | Design |
| 3 | 웹 UI | 미시작 |
| 4 | Claude Code CLI 자동 분석 | 미시작 |

## 2. 가격 컨벤션 (CRITICAL)

**모든 기술적 지표는 수정종가 (`adj_close`) 를 사용한다.** 원가 (`close`) 는 본 파이프라인에서 직접 사용하지 않으며, 화면 표시(예: "현재 가격") 또는 거래 체결가 재현 등 특수 목적에만 사용 가능 (#3 UI 의 결정).

구체적으로:
- **SMA(n)** — `adj_close` 의 n 일 단순평균
- **52주 high/low** — `adj_close` 의 252 영업일 최대/최소
- **RS Line** — `adj_close_stock / close_index` (지수는 수정 개념 없으므로 `close` 그대로 — 의도된 비대칭)
- **RS Rating** — `adj_close` 1년 수익률 백분위
- **미너비니 8 조건** — 모든 비교에서 `adj_close` 사용

이유: SMA 자체가 `adj_close` 평균이므로 비교 대상도 `adj_close` 여야 단위가 맞음. 액면분할 시 raw `close` 와 SMA 가 다른 단위가 되어 무의미.

## 3. 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 아키텍처 | Python 파이프라인 (`kr_pipeline.indicators`), #1, #1.5 와 동일 패턴 |
| 입력 | `daily_prices`, `weekly_prices`, `index_daily`, `weekly_index`, `stocks` |
| 출력 | `daily_indicators`, `weekly_indicators` |
| 저장 구조 | Wide 테이블, 일봉/주봉 분리 |
| 적재 모드 | `backfill`, `incremental`, `full-refresh` × `--target=daily|weekly` (6 조합) |
| RS Rating | 단순 (1년 수익률 백분위 0~99) |
| RS Line 벤치마크 | 종목 소속 시장 (KOSPI 종목 → KOSPI 지수, KOSDAQ 종목 → KOSDAQ 지수) |
| 상장 1년 미만 처리 | 관련 지표 NULL ("insufficient history") |
| `adj_close` 컬럼 | denormalize — `daily_indicators` / `weekly_indicators` 에 미러 컬럼 |
| 외부 IO | 없음 (DB-to-DB) |
| 처리 방식 | 종목별 순차 + Phase 분할 (A/B/C) |

## 4. 코드 구조

```
kr_pipeline/
├── indicators/                  # ← 신규
│   ├── __init__.py
│   ├── __main__.py              # argparse 진입점
│   ├── modes.py                 # backfill / incremental / full-refresh 분기
│   ├── compute/                 # 지표별 순수 함수 — 테스트 표면
│   │   ├── __init__.py
│   │   ├── sma.py               # SMA(n) 계산
│   │   ├── high_low.py          # 52w high/low + pct
│   │   ├── rs_line.py           # 종목/지수 비율 + booleans + 52w_high_date
│   │   ├── rs_rating.py         # 1년 수익률 백분위 (universe 단위)
│   │   └── minervini.py         # 8 조건 + 종합 boolean
│   ├── load.py                  # daily_prices / weekly_prices / index 에서 SELECT
│   └── store.py                 # daily_indicators / weekly_indicators UPSERT
└── (기존 ohlcv/, universe/, weekly/, common/, db/ 변경 없음)

tests/
├── test_indicators_sma.py
├── test_indicators_high_low.py
├── test_indicators_rs_line.py
├── test_indicators_rs_rating.py
├── test_indicators_minervini.py
├── test_indicators_modes.py
├── test_indicators_store.py
└── test_indicators_integration.py
```

### 핵심 원칙

- `compute/*` 는 **모두 순수 함수**. 입력: pandas Series/DataFrame, 출력: Series/DataFrame. DB/네트워크 안 만짐.
- 각 지표 모듈 분리 → 단위 테스트가 작고 정확.
- `modes.py` 는 오케스트레이션: load → compute 모듈 호출 → store.
- `store.py` 는 두 테이블 UPSERT 헬퍼.
- #1, #1.5 와 일관된 패턴.

### 진입점

```bash
# 1회성 백필
python -m kr_pipeline.indicators --target=daily --mode=backfill
python -m kr_pipeline.indicators --target=weekly --mode=backfill

# 매일/매주 증분
python -m kr_pipeline.indicators --target=daily --mode=incremental --window-days=30
python -m kr_pipeline.indicators --target=weekly --mode=incremental --window-weeks=4

# 수정종가 갱신 흡수 (월 1회)
python -m kr_pipeline.indicators --target=daily --mode=full-refresh
python -m kr_pipeline.indicators --target=weekly --mode=full-refresh
```

## 5. DB 스키마

```sql
-- ====== 일봉 시점 지표 ======
CREATE TABLE daily_indicators (
    ticker            VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    date              DATE          NOT NULL,
    
    -- 가격 anchor (수정종가) — daily_prices.adj_close 미러
    -- 분석 쿼리에서 SMA/52w 와 같이 보는 패턴이 보편적이라 JOIN 회피용 denormalization
    adj_close         NUMERIC(12,4) NOT NULL,
    
    -- 이동평균 (수정종가 기준)
    sma_10            NUMERIC(12,4),
    sma_21            NUMERIC(12,4),       -- VCP / 단기 모멘텀 분석용 (Trend Template 외)
    sma_50            NUMERIC(12,4),
    sma_150           NUMERIC(12,4),
    sma_200           NUMERIC(12,4),
    
    -- 52주 high/low (수정종가 기준, 252 영업일)
    w52_high          NUMERIC(12,4),
    w52_low           NUMERIC(12,4),
    pct_from_52w_high NUMERIC(8,4),         -- (adj_close - w52_high) / w52_high × 100
    pct_from_52w_low  NUMERIC(8,4),         -- (adj_close - w52_low) / w52_low × 100
    
    -- RS Line (종목 수정종가 / 벤치마크 종가)
    rs_line               NUMERIC(16,8),
    rs_line_52w_high      NUMERIC(16,8),
    rs_line_52w_high_date DATE,             -- O'Neil 7개월 하락 판정용
    rs_line_at_52w_high   BOOLEAN,
    rs_line_uptrend_6w    BOOLEAN,            -- 판정: rs_line > rs_line.rolling(30영업일=6주).mean()
    rs_line_uptrend_13w   BOOLEAN,            -- 판정: rs_line > rs_line.rolling(65영업일=13주).mean()
    rs_line_in_decline_7m BOOLEAN,            -- 판정: (today - rs_line_52w_high_date) >= 140영업일 (7개월)
    
    -- RS Rating (1년 수익률 백분위, 0~99)
    rs_rating         SMALLINT,
    
    -- 미너비니 템플릿 (8 조건 + 종합)
    minervini_c1      BOOLEAN,    -- adj_close > sma_150 > sma_200
    minervini_c2      BOOLEAN,    -- sma_150 > sma_200
    minervini_c3      BOOLEAN,    -- sma_200 이 최근 22 영업일 상승 추세
    minervini_c4      BOOLEAN,    -- sma_50 > sma_150 > sma_200
    minervini_c5      BOOLEAN,    -- adj_close > sma_50
    minervini_c6      BOOLEAN,    -- adj_close >= w52_low × 1.25
    minervini_c7      BOOLEAN,    -- adj_close >= w52_high × 0.75
    minervini_c8      BOOLEAN,    -- rs_rating >= 70
    minervini_pass    BOOLEAN,    -- 8개 모두 True 종합
    
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);

CREATE INDEX idx_daily_indicators_date ON daily_indicators(date);
CREATE INDEX idx_daily_indicators_minervini ON daily_indicators(date, minervini_pass)
    WHERE minervini_pass = TRUE;
CREATE INDEX idx_daily_indicators_rs ON daily_indicators(date, rs_rating)
    WHERE rs_rating >= 70;
CREATE INDEX idx_daily_indicators_analyst_target ON daily_indicators(date, rs_rating)
    WHERE minervini_pass = TRUE AND rs_rating >= 80;     -- #4 분석 대상 빠른 조회

-- ====== 주봉 시점 지표 ======
CREATE TABLE weekly_indicators (
    ticker            VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    week_end_date     DATE          NOT NULL,
    
    -- 가격 anchor (주봉 수정종가) — weekly_prices.adj_close 미러
    adj_close         NUMERIC(12,4) NOT NULL,
    
    -- 주봉 이동평균 (주봉 수정종가 기준)
    sma_10w           NUMERIC(12,4),       -- 10주 SMA (~50일 대응)
    sma_30w           NUMERIC(12,4),       -- 30주 SMA (~150일 대응)
    sma_40w           NUMERIC(12,4),       -- 40주 SMA (~200일 대응)
    
    -- 52주 high/low (주봉 기준, 52주)
    w52_high          NUMERIC(12,4),
    w52_low           NUMERIC(12,4),
    pct_from_52w_high NUMERIC(8,4),
    pct_from_52w_low  NUMERIC(8,4),
    
    -- RS Line (주봉)
    rs_line               NUMERIC(16,8),
    rs_line_52w_high      NUMERIC(16,8),
    rs_line_52w_high_date DATE,
    rs_line_at_52w_high   BOOLEAN,
    rs_line_uptrend_6w    BOOLEAN,            -- 판정: rs_line > rs_line.rolling(6주).mean() (주봉이므로 6주 = 6 행)
    rs_line_uptrend_13w   BOOLEAN,            -- 판정: rs_line > rs_line.rolling(13주).mean()
    rs_line_in_decline_7m BOOLEAN,            -- 판정: (today - rs_line_52w_high_date) >= 28주 (7개월)
    
    -- RS Rating (주봉 기준 1년 수익률 백분위)
    rs_rating         SMALLINT,
    
    -- 미너비니 템플릿 (주봉 버전 — 거시적 검토용)
    minervini_c1      BOOLEAN,    -- adj_close > sma_30w > sma_40w
    minervini_c2      BOOLEAN,    -- sma_30w > sma_40w
    minervini_c3      BOOLEAN,    -- sma_40w 이 최근 5 주 상승 추세 (1개월 ≈ 4.4주, 책 기준 정합)
    minervini_c4      BOOLEAN,    -- sma_10w > sma_30w > sma_40w
    minervini_c5      BOOLEAN,    -- adj_close > sma_10w
    minervini_c6      BOOLEAN,    -- adj_close >= w52_low × 1.25
    minervini_c7      BOOLEAN,    -- adj_close >= w52_high × 0.75
    minervini_c8      BOOLEAN,    -- rs_rating >= 70
    minervini_pass    BOOLEAN,
    
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, week_end_date)
);

CREATE INDEX idx_weekly_indicators_date ON weekly_indicators(week_end_date);
CREATE INDEX idx_weekly_indicators_minervini ON weekly_indicators(week_end_date, minervini_pass)
    WHERE minervini_pass = TRUE;
```

### 설계 결정 요지

- **모든 지표 컬럼 NULLABLE** — 상장 1년 미만 등 lookback 부족 시 NULL. analyst LLM 에는 "insufficient history" 로 전달.
- **`adj_close` 미러 컬럼** — 분석 쿼리 (`WHERE adj_close > sma_50`) 가 JOIN 없이 단일 테이블에서 가능. 저장 비용 ~10MB 무시 가능.
- **`rs_line` 타입 `NUMERIC(16,8)`** — 비율의 광범위 (~0.0001 ~ ~수백) 정밀도 확보.
- **미너비니 8 조건 모두 별도 컬럼** — UI 에서 "왜 통과/실패?" 디테일 표시 가능.
- **주봉 `minervini_c3` 5주** — "at least 1 month" ≈ 22 영업일 ≈ 4.4 주. 5주가 책 기준 정합.
- **3 가지 파셔널 인덱스** — `minervini_pass`, `rs_rating ≥ 70`, `minervini_pass AND rs_rating ≥ 80` (#4 분석 대상). 자주 쓰일 쿼리 패턴.

### 의도적으로 안 한 것 (YAGNI / Out of Scope)

- **거래량 지표 (volume SMA, breakout volume 비율 등)** — 미너비니/오닐 모두 강조하는 중요한 지표. 본 #2 에서는 trend template 자체에만 집중. **#2 후속 V2 작업으로 우선 처리 권장** (low-volume breakout 리스크 분석 등 LLM 입력 컨텍스트 풍부화).
- ATR / MACD / RSI / Bollinger Bands
- 월봉 / 분봉 지표
- View / Materialized view (#3 UI 단계에서 결정)

## 6. 데이터 흐름

### 공통: 3 단계 처리

지표 중 **RS Rating** 만 universe 전체 비교 (백분위) 필요. 나머지는 종목별 독립.

```
Phase A: 종목별 시계열 지표 (병렬 가능)
  ├─ SMA(10, 21, 50, 150, 200)
  ├─ 52w high/low + pct_from_*
  ├─ RS Line + 52w_high_date + uptrend booleans
  └─ 1년 수익률 (rs_rating 입력용 임시 보관)
  → UPSERT daily_indicators (rs_rating, minervini_* 제외)

Phase B: 날짜별 RS Rating 계산
  → 각 date 에서 모든 종목의 1년 수익률 백분위 계산
  → UPDATE daily_indicators SET rs_rating = ...

Phase C: 미너비니 8 조건 + 종합
  → 단일 SQL UPDATE (denormalize 된 adj_close 덕분에 JOIN 없음)
  → UPDATE daily_indicators
     SET minervini_c1 = (adj_close > sma_150 AND sma_150 > sma_200),
         ...
         minervini_pass = (c1 AND c2 AND c3 AND c4 AND c5 AND c6 AND c7 AND c8)
```

### Lookback 적용

`--window-days=30` 명령 시 실제 SELECT:

```python
LOOKBACK_DAYS = 252  # max(SMA200+22d, 52w high/low, 1y return)
sql_start = today - 30 - LOOKBACK_DAYS  # ~282일 전
sql_end = today

# 282일치 SELECT, 30일치만 UPSERT (앞 252일은 계산 재료)
```

가장 큰 lookback 출처:
- 52주 high/low: 252 영업일
- 1년 수익률 (rs_rating): 252 영업일
- SMA(200) + 22일 상승 추세 판정: 222 영업일

→ **최대 lookback = 252 거래일**

주봉도 동일 패턴: `--window-weeks=4` 시 lookback 52 주 → SQL 56 주.

### 모드별 동작

**backfill** — 1 회성:
```
start = (SELECT MIN(date) FROM daily_prices)
end = (SELECT MAX(date) FROM daily_prices)
Phase A/B/C 전체 기간
```

**incremental** — 매일/매주:
```
start = today - window - lookback
end = today
Phase A/B/C — 처음 lookback 부분은 계산 재료, window 부분만 UPSERT
```

**full-refresh** — 월 1회 (일봉/주봉 full-refresh 직후):
```
start = (SELECT MIN(date) FROM daily_prices)
end = (SELECT MAX(date) FROM daily_prices)
전체 기간 Phase A/B/C → 모든 지표 UPSERT (수정종가 변경 흡수)
```

### Cron 등록 (#1, #1.5 시간차 패턴)

```cron
TZ=Asia/Seoul

# 평일 19:00 — 일봉 지표 (일봉 18:30 적재 30분 후)
0  19 * * 1-5  cd $PROJECT_DIR && uv run python -m kr_pipeline.indicators --target=daily --mode=incremental --window-days=30 >> $LOG_DIR/indicators.log 2>&1

# 매주 토요일 04:00 — 주봉 지표 (주봉 03:00 적재 1시간 후)
0  4 * * 6     cd $PROJECT_DIR && uv run python -m kr_pipeline.indicators --target=weekly --mode=incremental --window-weeks=4 >> $LOG_DIR/indicators.log 2>&1

# 매월 1일 03:00 — 일봉 지표 full-refresh (일봉 02:00 후)
0  3 1 * *     cd $PROJECT_DIR && uv run python -m kr_pipeline.indicators --target=daily --mode=full-refresh >> $LOG_DIR/indicators.log 2>&1

# 매월 1일 05:00 — 주봉 지표 full-refresh (주봉 04:00 후)
0  5 1 * *     cd $PROJECT_DIR && uv run python -m kr_pipeline.indicators --target=weekly --mode=full-refresh >> $LOG_DIR/indicators.log 2>&1
```

각 작업 사이 30분~1시간 버퍼. 명시적 의존성 체크 안 함 (단순성 유지) — 단, 지표 시작 시 가벼운 prerequisite 로깅으로 운영자에게 단서 제공.

### 처리 성능 추정

| Phase | 일봉 incremental | 일봉 backfill |
|---|---|---|
| A (종목별) | 2,500 × 282행 → ~2분 | 2,500 × ~500행 → ~8분 |
| B (날짜별 RS) | 30 dates → 3초 | ~500 dates → 50초 |
| C (단일 SQL UPDATE) | <1초 | ~5초 |
| **합계** | **~2-3분** | **~10분** |

주봉은 데이터 양 1/5 → 더 빠름.

## 7. 에러 처리 / 멱등성 / Sanity

### 멱등성

- 모든 쓰기 UPSERT — 같은 명령 두 번 = 같은 결과
- PK = `(ticker, date)` / `(ticker, week_end_date)`
- `ON CONFLICT DO UPDATE SET ...` 로 모든 지표 컬럼 갱신

### 트랜잭션 단위

| Phase | 단위 |
|---|---|
| A | 종목 단위 commit (한 종목 처리 후 commit, 다음 종목으로) |
| B | 전체 date 처리 후 1 회 commit (배치 UPDATE) |
| C | 단일 SQL UPDATE → 1 회 commit |

한 종목 실패해도 다른 종목 보존.

### 종목 단위 부분 실패 + 끝-of-run 재시도

Phase A 에만 적용 (#1 OHLCV `_run_full_refresh` 동일 패턴):
```
1차 루프: 모든 종목 시도 → 실패 종목 모음
끝나면 → 실패 종목 1회 재시도 → 최종 실패는 pipeline_runs.error 기록
```

Phase B/C 는 SQL 단일 쿼리라 재시도 불필요 (실패 시 전체 트랜잭션 롤백, 사용자 보고).

### Lookback 부족 처리

상장 1년 미만 등 데이터 부족 시:
- `rolling(window, min_periods=window)` → 데이터 부족하면 NaN
- pandas NaN → psycopg None → SQL NULL
- 미너비니 조건은 NULL 입력 시 그 조건도 NULL (SQL 3-valued logic)
- `minervini_pass = (c1 AND c2 AND ... AND c8)` — 조건 하나라도 NULL 이면 결과 NULL → 통과 안 함 (안전)

LLM 전달 시 NULL 은 "insufficient history" 로 매핑 (#4).

### Sanity 검증 (#1, #1.5 패턴 재사용)

작업 종료 직전 4 가지 가벼운 SQL:

| 검증 | 임계값 |
|---|---|
| 커버리지 | 최근 date 의 `daily_indicators` 행수 / `daily_prices` 행수 < 95% → 경고 |
| SMA NULL 비율 | 최근 date 의 `sma_200 IS NULL` 비율 > 30% → 경고 (정상은 5-10%) |
| RS Rating 분포 | 정상 분포 (max=99, min=0, count > 1000) 인지 |
| 미너비니 통과율 | 비정상 (0% 또는 50% 이상) → 경고 |

경고는 `pipeline_runs.error` 에 JSON 으로 기록, status=success 유지.

### 외부 의존성 가벼운 체크

지표 시작 직전 prerequisite 로깅 (실패 처리 안 함):
```python
SELECT MAX(started_at) FROM pipeline_runs 
 WHERE pipeline='ohlcv' AND status='success'
# 24시간 넘으면 WARN 로깅, pipeline_runs.error 기록. 진행은 계속.
```

cron 시간차로 안전하지만 만일을 위함.

### 로깅

- Phase 진입마다 progress 로그 (`Phase A start`, `Phase A done in 2.3min`)
- Phase A 종목 100개마다 진행률
- 최종 `DONE rows_affected=N failures=M sanity_warnings=K phase_a=2.3min phase_b=12s phase_c=0.4s`
- 실패 종목 상위 20개 WARN

## 8. 테스팅 전략

### 테스트 계층 — 7 개 파일 ~50 개 테스트

| 파일 | 테스트 대상 | 개수 | 비고 |
|---|---|---|---|
| `test_indicators_sma.py` | SMA(n) 단순 평균 | ~4 | window 정확성, NaN, 길이 부족 |
| `test_indicators_high_low.py` | 52주 high/low + pct | ~6 | 두텁게 |
| `test_indicators_rs_line.py` | 비율 + booleans + 52w_high_date | ~10 | 가장 두텁게 |
| `test_indicators_rs_rating.py` | 백분위 (universe 단위) | ~5 | 정확성 + tie 처리 |
| `test_indicators_minervini.py` | 8 조건 + 종합 | ~12 | 각 조건별 + 종합 |
| `test_indicators_modes.py` | 모드 분기, lookback 계산 | ~4 | freeze_time |
| `test_indicators_store.py` | UPSERT (통합) | ~5 | 실제 Postgres |
| `test_indicators_integration.py` | end-to-end (3 phase + DB) | ~3 | 통합 |

총 ~50 테스트. ~40 개가 순수 함수 단위 테스트 (외부 IO 없음, 빠름).

### 핵심 단위 테스트 예시

```python
# test_indicators_rs_line.py
def test_rs_line_uses_adj_close_not_raw(): ...
def test_rs_line_52w_high_date_tracked(): ...
def test_rs_line_at_52w_high_today(): ...
def test_rs_line_uptrend_13w_when_slope_positive(): ...
def test_rs_line_in_decline_7m_when_high_was_long_ago(): ...
def test_rs_line_insufficient_history_returns_null(): ...

# test_indicators_minervini.py
def test_c1_close_above_sma150_above_sma200(): ...
def test_c3_sma200_rising_over_22_days(): ...
def test_c6_close_25pct_above_52w_low(): ...
def test_c8_rs_rating_threshold_70(): ...
def test_pass_requires_all_8(): ...
def test_pass_fails_if_any_null(): ...

# test_indicators_rs_rating.py
def test_rs_rating_assigns_99_to_top_stock(): ...
def test_rs_rating_handles_ties(): ...
def test_rs_rating_excludes_insufficient_history(): ...
def test_rs_rating_percentile_formula(): ...
```

### 통합 테스트

```python
# test_indicators_integration.py
def test_backfill_end_to_end(db): ...           # 3 phase 완료, 정확한 sma_200, rs_rating, minervini_pass
def test_incremental_idempotent(db): ...        # 같은 incremental 두 번 → 결과 동일
def test_full_refresh_updates_adj_close_dependent(db): ...   # daily_prices.adj_close 변경 → 지표 재계산
```

### 의도적으로 안 할 것

- pykrx mock (호출 안 함)
- 성능 벤치마크 (분 단위 작업, 의미 없음)
- `run_tracking` 직접 테스트 (#1 에서 검증 끝)
- `load.py` 단위 테스트 (단순 SELECT, 통합 테스트로 충분)
- 전체 universe 시뮬레이션 (~5 종목으로 통합 충분)

### 테스트 DB 격리

- 단위 테스트: `db` fixture (트랜잭션 → ROLLBACK)
- 통합 테스트: `_cleanup` + `try/finally` (자체 정리, kr_test 폴루션 방지)

### 개발 워크플로우

- TDD: compute 모듈 함수 하나 만들 때마다 실패 테스트 먼저 → 통과
- compute 는 100% 단위 테스트
- store / modes 는 통합 테스트

## 9. 범위 밖 (Out of Scope)

### 본 #2 에서 의도적으로 제외

- **거래량 지표** — V2 우선순위 ↑. 미너비니/오닐 모두 강조하는 지표 (Stage 1→2 전환, breakout volume). #4 LLM 분석 입력에 거래량 컨텍스트 없으면 low-volume breakout 리스크 플래그 못 닮. **#2 완료 직후 V2 로 처리 권장**.
- ATR / MACD / RSI / Bollinger Bands / Stochastic 등 다른 기술적 지표
- 월봉 / 분봉 지표
- View / Materialized view
- 펀더멘털 (PER, PBR, ROE 등)
- 차트 이미지 생성 (#3)
- LLM 분석 입력 포맷 (#4)

## 10. 후속 작업

본 스펙 승인 후:
1. `writing-plans` 스킬로 구현 계획 작성
2. `subagent-driven-development` 으로 구현 (#1, #1.5 와 동일 패턴)
3. 검증 후 V2 (거래량 지표) 또는 #3 (UI) 진행
