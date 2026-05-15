# 주봉 데이터 적재 파이프라인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일봉 `daily_prices` / 지수 `index_daily` 를 입력으로 주봉 `weekly_prices` / `weekly_index` 를 생성·적재하는 `kr_pipeline.weekly` Python 패키지 구현. backfill / incremental / full-refresh 세 모드. 외부 네트워크 호출 0.

**Architecture:** 단일 패키지에 모드 인자 진입점 (Approach A, #1 동일 패턴). `transform` (순수 함수) / `store` (DB IO) / `modes` (오케스트레이션) 분리. 종목별 순차 처리 (메모리 ~100KB, 부분 실패 격리). 모든 쓰기 멱등 UPSERT. `pipeline_runs` 재사용.

**Tech Stack:** Python 3.11+, uv, psycopg[binary], pandas, pytest, freezegun (이미 모두 설치됨, 신규 의존성 없음)

**Spec:** [`../specs/2026-05-15-weekly-ohlcv-pipeline-design.md`](../specs/2026-05-15-weekly-ohlcv-pipeline-design.md)

---

## ⚙️ Autonomous Execution Protocol

**이 계획은 자율 실행 모드로 동작합니다.** 실행자는 사용자 확인을 기다리지 않고 아래 규칙을 따른다.

### Goal State

다음 조건을 **모두** 만족하면 작업 종료:

1. 본 계획의 모든 task 체크박스 (`- [ ]` → `- [x]`) 가 체크됨
2. `uv run pytest tests/` — 전체 테스트 통과 (exit code 0). 직전 기준 35 passed → 본 계획 완료 후 50+ passed 예상
3. **스모크 테스트 통과**:
   - `uv run python -m kr_pipeline.weekly --mode=backfill` 가 에러 없이 종료
   - DB 확인: `weekly_prices` 와 `weekly_index` 테이블에 합리적 행수가 들어감 (`weekly_prices` >= 100, `weekly_index` >= 2)
4. `git status` — uncommitted 변경 없음
5. `pipeline_runs` 에 최소 1 개의 `weekly | backfill | success` 행 존재

### 실행 루프

각 task 마다:
```
1. task 시작 → 체크박스 [in_progress] 표시
2. step 들을 순서대로 수행 (test → fail 확인 → 구현 → pass 확인 → commit)
3. 검증 명령의 expected output 과 실제 비교
4. 일치 → 체크박스 [x] → 다음 task
5. 불일치 → 진단 → 수정 → 재검증 (최대 3 회)
6. 3 회 동일 에러 → 사용자에게 보고 후 정지
7. 모든 task 완료 → Goal State 5 개 항목 최종 검증 → 통과 시 종료
```

### Stuck Rules

- 같은 에러 메시지 **3 회 반복** → 즉시 정지, 에러 + 시도 내역 보고
- **외부 환경 문제** (DB 다운, schema migration 실패) → 즉시 정지, 사용자에게 환경 셋업 요청
- **사양 모호성 발견** → 즉시 정지, 명확화 요청
- 그 외 모든 실패 (테스트 실패, lint, 임포트, SQL 오류 등) → **스스로 진단/수정/재시도**

### 무엇을 하지 말 것

- "다음 task 진행할까요?" 같은 확인 질문 금지
- 사양 외 기능 추가 금지 (YAGNI)
- 신규 라이브러리 추가 금지 (이미 모두 설치됨)
- #1 의 기존 모듈 변경 금지 (단, `kr_pipeline/db/schema.sql` 끝에 weekly 테이블 추가는 예외)

---

## 사전 조건 (Prerequisites)

- #1 (일봉 파이프라인) 완료 상태 — `kr_pipeline/{common,db,universe,ohlcv}` 모듈 모두 존재
- PostgreSQL 실행 중, `kr_pipeline` / `kr_test` DB 에 #1 스키마 적용 완료
- `kr_pipeline.stocks` 에 ~2,550 활성 종목, `kr_pipeline.daily_prices` 에 일정 데이터 (스모크 테스트용 최소 10 종목 × 7 일)
- `.env` 에 `DATABASE_URL` / `TEST_DATABASE_URL` 설정

각 task 시작 시 위 조건은 만족된 상태라고 가정.

---

## 파일 구조 (참조용)

```
kr_pipeline/
├── db/
│   └── schema.sql                  # ← 끝에 weekly_prices, weekly_index 추가
├── weekly/                         # ← 신규
│   ├── __init__.py
│   ├── __main__.py                 # python -m kr_pipeline.weekly 진입점
│   ├── modes.py                    # backfill / incremental / full-refresh
│   ├── transform.py                # 일봉 → 주봉 집계 (순수 함수)
│   ├── load.py                     # daily_prices / index_daily 에서 SELECT
│   └── store.py                    # weekly_prices / weekly_index UPSERT
└── (기존 ohlcv/, universe/, common/, db/ 변경 없음)

tests/
├── test_weekly_transform.py
├── test_weekly_modes.py
└── test_weekly_store.py

scripts/cron.example                # ← 끝에 weekly cron 라인 2 개 추가
README.md                           # ← Cron 등록 + 운영 쿼리에 weekly 추가
```

---

## Task 1: DB 스키마 추가

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (append)
- Modify: 적용 to `kr_pipeline` 과 `kr_test` 두 DB

- [ ] **Step 1: `kr_pipeline/db/schema.sql` 끝에 추가**

```sql

-- ====== Weekly (#1.5) ======

CREATE TABLE IF NOT EXISTS weekly_prices (
    ticker          VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    week_end_date   DATE          NOT NULL,
    open            NUMERIC(12,2) NOT NULL,
    high            NUMERIC(12,2) NOT NULL,
    low             NUMERIC(12,2) NOT NULL,
    close           NUMERIC(12,2) NOT NULL,
    adj_close       NUMERIC(12,4) NOT NULL,
    volume          BIGINT        NOT NULL,
    value           BIGINT        NOT NULL,
    trading_days    SMALLINT      NOT NULL,
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, week_end_date)
);
CREATE INDEX IF NOT EXISTS idx_weekly_prices_date ON weekly_prices(week_end_date);

CREATE TABLE IF NOT EXISTS weekly_index (
    index_code      VARCHAR(10)   NOT NULL,
    week_end_date   DATE          NOT NULL,
    open            NUMERIC(12,2) NOT NULL,
    high            NUMERIC(12,2) NOT NULL,
    low             NUMERIC(12,2) NOT NULL,
    close           NUMERIC(12,2) NOT NULL,
    volume          BIGINT,
    value           BIGINT,
    trading_days    SMALLINT      NOT NULL,
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code, week_end_date)
);
```

- [ ] **Step 2: 두 DB 에 적용**

Run:
```bash
psql postgresql://localhost/kr_pipeline -f kr_pipeline/db/schema.sql
psql postgresql://localhost/kr_test -f kr_pipeline/db/schema.sql
```

Expected: `CREATE TABLE` / `CREATE INDEX` 출력, 에러 없음 (기존 테이블은 `IF NOT EXISTS` 로 무시됨).

- [ ] **Step 3: 검증**

Run:
```bash
psql postgresql://localhost/kr_pipeline -c "\d weekly_prices"
psql postgresql://localhost/kr_pipeline -c "\d weekly_index"
psql postgresql://localhost/kr_test -c "\d weekly_prices"
```

Expected: 컬럼 출력 — `ticker`, `week_end_date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`, `value`, `trading_days`, `updated_at`. PK = `(ticker, week_end_date)`. FK to stocks. 인덱스 `idx_weekly_prices_date` 존재.

- [ ] **Step 4: 빈 패키지 디렉토리 생성**

Run:
```bash
mkdir -p kr_pipeline/weekly tests
touch kr_pipeline/weekly/__init__.py
```

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/db/schema.sql kr_pipeline/weekly/__init__.py
git commit -m "feat(weekly): DB 스키마 추가 (weekly_prices, weekly_index)"
```

---

## Task 2: weekly transform — 주봉 집계 (TDD)

**Files:**
- Create: `kr_pipeline/weekly/transform.py`
- Create: `tests/test_weekly_transform.py`

이 task 는 본 파이프라인의 핵심. 가장 큰 테스트 표면이므로 꼼꼼히.

- [ ] **Step 1: 테스트 우선 작성**

`tests/test_weekly_transform.py`:

```python
from datetime import date
import pandas as pd
import pytest

from kr_pipeline.weekly.transform import (
    aggregate_to_weekly,
    drop_incomplete_weeks,
    to_weekly_rows,
)


def _daily(date_, o, h, l, c, adj, v, val):
    return {
        "date": date_,
        "open": o, "high": h, "low": l, "close": c,
        "adj_close": adj, "volume": v, "value": val,
    }


def test_aggregate_single_full_week():
    """월~금 5일 일봉 → 1개 주봉."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 11), 100, 110, 95,  105, 105.0, 1000, 100000),   # Mon
        _daily(date(2026, 5, 12), 105, 115, 100, 108, 108.0, 1100, 113200),   # Tue
        _daily(date(2026, 5, 13), 108, 120, 102, 115, 115.0, 1200, 137400),   # Wed
        _daily(date(2026, 5, 14), 115, 125, 110, 120, 120.0, 1300, 153400),   # Thu
        _daily(date(2026, 5, 15), 120, 130, 115, 125, 125.0, 1400, 175000),   # Fri
    ])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 1
    row = weekly.iloc[0]
    assert row["week_end_date"] == date(2026, 5, 15)
    assert row["open"] == 100
    assert row["high"] == 130
    assert row["low"] == 95
    assert row["close"] == 125
    assert row["adj_close"] == 125.0
    assert row["volume"] == 6000
    assert row["value"] == 679000
    assert row["trading_days"] == 5


def test_aggregate_holiday_week_4_days():
    """월요일 휴장. 화~금 4일치만 → trading_days=4, week_end_date=금."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 12), 105, 115, 100, 108, 108.0, 1100, 113200),
        _daily(date(2026, 5, 13), 108, 120, 102, 115, 115.0, 1200, 137400),
        _daily(date(2026, 5, 14), 115, 125, 110, 120, 120.0, 1300, 153400),
        _daily(date(2026, 5, 15), 120, 130, 115, 125, 125.0, 1400, 175000),
    ])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 1
    row = weekly.iloc[0]
    assert row["week_end_date"] == date(2026, 5, 15)
    assert row["open"] == 105
    assert row["trading_days"] == 4


def test_aggregate_holiday_friday_thursday_closes_week():
    """금요일 휴장. 월~목. week_end_date=목요일."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 11), 100, 110, 95,  105, 105.0, 1000, 100000),
        _daily(date(2026, 5, 12), 105, 115, 100, 108, 108.0, 1100, 113200),
        _daily(date(2026, 5, 13), 108, 120, 102, 115, 115.0, 1200, 137400),
        _daily(date(2026, 5, 14), 115, 125, 110, 120, 120.0, 1300, 153400),
    ])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 1
    row = weekly.iloc[0]
    assert row["week_end_date"] == date(2026, 5, 14)
    assert row["close"] == 120
    assert row["adj_close"] == 120.0
    assert row["trading_days"] == 4


def test_aggregate_multiple_weeks_split_correctly():
    """2주치 일봉 → 2주봉. 주 경계 정확히 분리."""
    daily = pd.DataFrame([
        # Week 1: 2026-05-04 ~ 2026-05-08
        _daily(date(2026, 5, 4),  100, 100, 100, 100, 100.0, 100, 10000),
        _daily(date(2026, 5, 8),  100, 100, 100, 200, 200.0, 100, 20000),
        # Week 2: 2026-05-11 ~ 2026-05-15
        _daily(date(2026, 5, 11), 200, 200, 200, 200, 200.0, 100, 20000),
        _daily(date(2026, 5, 15), 200, 200, 200, 300, 300.0, 100, 30000),
    ])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 2
    week1 = weekly[weekly["week_end_date"] == date(2026, 5, 8)].iloc[0]
    week2 = weekly[weekly["week_end_date"] == date(2026, 5, 15)].iloc[0]
    assert week1["close"] == 200
    assert week2["close"] == 300


def test_adj_close_takes_last_day_value_not_max():
    """adj_close = 그 주 마지막 거래일의 adj_close (max 가 아님)."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 11), 100, 200, 100, 150, 75.0, 100, 15000),
        _daily(date(2026, 5, 15), 150, 160, 140, 155, 77.5, 100, 15500),
    ])
    weekly = aggregate_to_weekly(daily)
    assert weekly.iloc[0]["adj_close"] == 77.5


def test_empty_daily_returns_empty_weekly():
    """일봉 0행 → 주봉 0행."""
    daily = pd.DataFrame(columns=["date", "open", "high", "low", "close", "adj_close", "volume", "value"])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 0
    # 컬럼은 있어야 함
    assert set(weekly.columns) >= {"week_end_date", "open", "high", "low", "close", "adj_close", "volume", "value", "trading_days"}


def test_drop_incomplete_weeks_removes_current_week():
    """today=2026-05-14 (목) 일 때 5/11~5/15 주는 미완성 → 제외."""
    weekly = pd.DataFrame([
        {"week_end_date": date(2026, 5, 8),  "close": 100},   # 완료
        {"week_end_date": date(2026, 5, 15), "close": 200},   # 미완성 (5/14 기준)
    ])
    today = date(2026, 5, 14)
    result = drop_incomplete_weeks(weekly, today)
    assert list(result["week_end_date"]) == [date(2026, 5, 8)]


def test_drop_incomplete_weeks_keeps_completed_week():
    """today=2026-05-18 (월) 일 때 5/11~5/15 주는 완료 → 포함."""
    weekly = pd.DataFrame([
        {"week_end_date": date(2026, 5, 8),  "close": 100},
        {"week_end_date": date(2026, 5, 15), "close": 200},
    ])
    today = date(2026, 5, 18)
    result = drop_incomplete_weeks(weekly, today)
    assert list(result["week_end_date"]) == [date(2026, 5, 8), date(2026, 5, 15)]


def test_drop_incomplete_weeks_with_today_on_weekend():
    """today=2026-05-16 (토) 일 때 5/11~5/15 주는 완료 → 포함."""
    weekly = pd.DataFrame([
        {"week_end_date": date(2026, 5, 15), "close": 200},
    ])
    today = date(2026, 5, 16)
    result = drop_incomplete_weeks(weekly, today)
    assert list(result["week_end_date"]) == [date(2026, 5, 15)]


def test_to_weekly_rows_tuple_format():
    """DataFrame → executemany 용 tuple 리스트."""
    weekly = pd.DataFrame([{
        "week_end_date": date(2026, 5, 15),
        "open": 100, "high": 130, "low": 95, "close": 125,
        "adj_close": 125.0, "volume": 6000, "value": 679000, "trading_days": 5,
    }])
    rows = to_weekly_rows("005930", weekly)
    assert rows == [(
        "005930", date(2026, 5, 15),
        100, 130, 95, 125,
        125.0, 6000, 679000, 5,
    )]


def test_aggregate_preserves_int_types_for_db():
    """volume, value, trading_days 는 int 로 출력 (psycopg BIGINT/SMALLINT 매칭)."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 11), 100, 100, 100, 100, 100.0, 1000, 100000),
        _daily(date(2026, 5, 15), 100, 100, 100, 100, 100.0, 2000, 200000),
    ])
    weekly = aggregate_to_weekly(daily)
    row = weekly.iloc[0]
    assert isinstance(int(row["volume"]), int)
    assert isinstance(int(row["value"]), int)
    assert isinstance(int(row["trading_days"]), int)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_weekly_transform.py -v`
Expected: FAIL — `ModuleNotFoundError: kr_pipeline.weekly.transform` 또는 ImportError

- [ ] **Step 3: `kr_pipeline/weekly/transform.py` 구현**

```python
"""주봉 집계 transform — 순수 함수, 외부 IO 없음."""
from datetime import date
import pandas as pd


# 주봉 출력 컬럼 (DataFrame / row 양쪽에서 사용)
WEEKLY_COLUMNS = [
    "week_end_date", "open", "high", "low", "close",
    "adj_close", "volume", "value", "trading_days",
]


def aggregate_to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 DataFrame 을 주봉으로 집계.
    
    입력 daily 컬럼: date, open, high, low, close, adj_close, volume, value
    출력 컬럼: week_end_date, open, high, low, close, adj_close, volume, value, trading_days
    
    주 그룹화: ISO 주 (월요일 시작). 같은 주의 행들 중 max(date) 가 week_end_date.
    pykrx 는 휴장일을 빼고 제공하므로 휴장 캘린더 관리 불필요.
    """
    if daily.empty:
        return pd.DataFrame(columns=WEEKLY_COLUMNS)
    
    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    # ISO 주 기간 ("W-SUN" = 일요일 종료, 즉 월~일 한 주)
    df["_period"] = df["date"].dt.to_period("W-SUN")
    
    grouped = df.groupby("_period")
    
    # 그룹별 집계
    agg = pd.DataFrame({
        "week_end_date": grouped["date"].max().dt.date,
        "open":          grouped.apply(lambda g: g.sort_values("date")["open"].iloc[0], include_groups=False),
        "high":          grouped["high"].max(),
        "low":           grouped["low"].min(),
        "close":         grouped.apply(lambda g: g.sort_values("date")["close"].iloc[-1], include_groups=False),
        "adj_close":     grouped.apply(lambda g: g.sort_values("date")["adj_close"].iloc[-1], include_groups=False),
        "volume":        grouped["volume"].sum(),
        "value":         grouped["value"].sum(),
        "trading_days":  grouped["date"].count(),
    }).reset_index(drop=True)
    
    return agg[WEEKLY_COLUMNS]


def drop_incomplete_weeks(weekly: pd.DataFrame, today: date) -> pd.DataFrame:
    """현재 진행 중인 주 (미완성 주) 를 제외.
    
    주가 완료된 기준: today 가 그 주의 일요일을 넘어선 시점.
    예: week_end_date=2026-05-15 (금) → 그 주 일요일은 2026-05-17 → today >= 2026-05-18 이어야 완료.
    
    실제로는 보수적으로: today > week_end_date 가 속한 주의 일요일.
    더 간단히: week_end_date 의 ISO 주가 today 의 ISO 주와 같으면 미완성 → 제외.
    """
    if weekly.empty:
        return weekly
    
    today_period = pd.Period(today, freq="W-SUN")
    # week_end_date 의 주 != today 의 주 → 완료된 주
    we_period = pd.to_datetime(weekly["week_end_date"]).dt.to_period("W-SUN")
    return weekly[we_period != today_period].reset_index(drop=True)


def to_weekly_rows(ticker: str, weekly: pd.DataFrame) -> list[tuple]:
    """weekly_prices.executemany 용 tuple 리스트 변환."""
    return [
        (
            ticker,
            r["week_end_date"],
            int(r["open"]),
            int(r["high"]),
            int(r["low"]),
            int(r["close"]),
            float(r["adj_close"]),
            int(r["volume"]),
            int(r["value"]),
            int(r["trading_days"]),
        )
        for _, r in weekly.iterrows()
    ]


def to_weekly_index_rows(index_code: str, weekly: pd.DataFrame) -> list[tuple]:
    """weekly_index.executemany 용 tuple 리스트. volume/value 는 NULL 가능."""
    rows = []
    for _, r in weekly.iterrows():
        vol = r.get("volume")
        val = r.get("value")
        rows.append((
            index_code,
            r["week_end_date"],
            int(r["open"]),
            int(r["high"]),
            int(r["low"]),
            int(r["close"]),
            int(vol) if vol is not None and not pd.isna(vol) else None,
            int(val) if val is not None and not pd.isna(val) else None,
            int(r["trading_days"]),
        ))
    return rows
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_weekly_transform.py -v`
Expected: 11 passed

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `uv run pytest -v 2>&1 | tail -5`
Expected: 46 passed (35 prior + 11 new). 기존 테스트 회귀 없음.

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/weekly/transform.py tests/test_weekly_transform.py
git commit -m "feat(weekly): transform - 일봉 → 주봉 집계 (순수 함수)"
```

---

## Task 3: weekly load — 일봉 SELECT

**Files:**
- Create: `kr_pipeline/weekly/load.py`

전용 SELECT 헬퍼. 단일 책임으로 분리 (`modes.py` 가 SQL 조립 안 하도록).

- [ ] **Step 1: 구현**

```python
"""weekly 파이프라인 입력 로딩 — daily_prices / index_daily 에서 SELECT."""
from datetime import date

import pandas as pd
from psycopg import Connection


def load_daily_for_ticker(
    conn: Connection,
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """한 종목의 일봉을 기간 범위로 가져옴.
    
    return columns: date, open, high, low, close, adj_close, volume, value
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, open, high, low, close, adj_close, volume, value
              FROM daily_prices
             WHERE ticker = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (ticker, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def load_index_daily(
    conn: Connection,
    index_code: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """한 지수의 일봉을 기간 범위로 가져옴.
    
    return columns: date, open, high, low, close, volume, value, adj_close(=close)
    (지수는 수정 개념 없음 → adj_close 컬럼은 close 와 동일하게 채워서 transform 일관성 유지)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, open, high, low, close, volume, value
              FROM index_daily
             WHERE index_code = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (index_code, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["adj_close"] = df["close"]   # 지수는 수정 없음
    return df


def load_active_tickers(conn: Connection, limit: int | None = None) -> list[str]:
    """active universe — delisted_at IS NULL 종목."""
    with conn.cursor() as cur:
        sql = "SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


def get_daily_min_date(conn: Connection) -> date | None:
    """daily_prices 의 가장 오래된 날짜. backfill 시작점 결정용."""
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(date) FROM daily_prices")
        row = cur.fetchone()
        return row[0] if row and row[0] else None
```

- [ ] **Step 2: 임포트 가능 확인**

Run:
```bash
uv run python -c "from kr_pipeline.weekly.load import load_daily_for_ticker, load_index_daily, load_active_tickers, get_daily_min_date; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: 커밋**

```bash
git add kr_pipeline/weekly/load.py
git commit -m "feat(weekly): load - daily_prices / index_daily SELECT 헬퍼"
```

---

## Task 4: weekly store — UPSERT (TDD)

**Files:**
- Create: `kr_pipeline/weekly/store.py`
- Create: `tests/test_weekly_store.py`

- [ ] **Step 1: 테스트 우선 작성**

```python
# tests/test_weekly_store.py
from datetime import date

from kr_pipeline.weekly.store import upsert_weekly_prices, upsert_weekly_index


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_weekly_prices_inserts_new(db):
    _seed_stock(db)
    rows = [(
        "005930", date(2026, 5, 15),
        100, 130, 95, 125, 125.0, 6000, 679000, 5,
    )]
    affected = upsert_weekly_prices(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT close, adj_close, trading_days FROM weekly_prices "
            "WHERE ticker = '005930' AND week_end_date = '2026-05-15'"
        )
        assert cur.fetchone() == (125, 125.0, 5)


def test_upsert_weekly_prices_updates_on_conflict(db):
    _seed_stock(db)
    rows_v1 = [("005930", date(2026, 5, 15), 100, 130, 95, 125, 125.0, 6000, 679000, 5)]
    upsert_weekly_prices(db, rows_v1)
    rows_v2 = [("005930", date(2026, 5, 15), 100, 135, 90, 128, 128.0, 7000, 800000, 5)]
    upsert_weekly_prices(db, rows_v2)

    with db.cursor() as cur:
        cur.execute(
            "SELECT high, low, close, adj_close, volume FROM weekly_prices "
            "WHERE ticker = '005930' AND week_end_date = '2026-05-15'"
        )
        assert cur.fetchone() == (135, 90, 128, 128.0, 7000)


def test_upsert_weekly_prices_empty_returns_zero(db):
    affected = upsert_weekly_prices(db, [])
    assert affected == 0


def test_upsert_weekly_index_inserts(db):
    rows = [("1001", date(2026, 5, 15), 2500, 2520, 2490, 2510, None, None, 5)]
    affected = upsert_weekly_index(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT close, volume FROM weekly_index "
            "WHERE index_code = '1001' AND week_end_date = '2026-05-15'"
        )
        assert cur.fetchone() == (2510, None)


def test_upsert_weekly_index_updates_on_conflict(db):
    rows_v1 = [("1001", date(2026, 5, 15), 2500, 2520, 2490, 2510, 1000, 1000000, 5)]
    upsert_weekly_index(db, rows_v1)
    rows_v2 = [("1001", date(2026, 5, 15), 2500, 2530, 2480, 2520, 2000, 2000000, 5)]
    upsert_weekly_index(db, rows_v2)

    with db.cursor() as cur:
        cur.execute("SELECT close, volume FROM weekly_index WHERE index_code='1001' AND week_end_date='2026-05-15'")
        assert cur.fetchone() == (2520, 2000)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_weekly_store.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: `kr_pipeline/weekly/store.py` 구현**

```python
"""weekly_prices / weekly_index UPSERT 헬퍼."""
from psycopg import Connection


def upsert_weekly_prices(conn: Connection, rows: list[tuple]) -> int:
    """
    rows: (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days)
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO weekly_prices
              (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, week_end_date) DO UPDATE
               SET open = EXCLUDED.open,
                   high = EXCLUDED.high,
                   low = EXCLUDED.low,
                   close = EXCLUDED.close,
                   adj_close = EXCLUDED.adj_close,
                   volume = EXCLUDED.volume,
                   value = EXCLUDED.value,
                   trading_days = EXCLUDED.trading_days,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount


def upsert_weekly_index(conn: Connection, rows: list[tuple]) -> int:
    """
    rows: (index_code, week_end_date, open, high, low, close, volume, value, trading_days)
    """
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO weekly_index
              (index_code, week_end_date, open, high, low, close, volume, value, trading_days, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (index_code, week_end_date) DO UPDATE
               SET open = EXCLUDED.open,
                   high = EXCLUDED.high,
                   low = EXCLUDED.low,
                   close = EXCLUDED.close,
                   volume = EXCLUDED.volume,
                   value = EXCLUDED.value,
                   trading_days = EXCLUDED.trading_days,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_weekly_store.py -v`
Expected: 5 passed

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 51 passed (46 prior + 5 new)

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/weekly/store.py tests/test_weekly_store.py
git commit -m "feat(weekly): store - weekly_prices / weekly_index UPSERT"
```

---

## Task 5: weekly modes — 분기 + 오케스트레이션 (TDD)

**Files:**
- Create: `kr_pipeline/weekly/modes.py`
- Create: `tests/test_weekly_modes.py`

- [ ] **Step 1: 테스트 우선 작성**

```python
# tests/test_weekly_modes.py
from datetime import date, timedelta
from freezegun import freeze_time

from kr_pipeline.weekly.modes import Mode, compute_date_range


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.FULL_REFRESH.value == "full-refresh"


@freeze_time("2026-05-18")  # Monday
def test_incremental_range_4_weeks():
    """today=Mon 5/18 → start=5/18 - 28일 = 4/20, end=today-1 = 5/17"""
    start, end = compute_date_range(Mode.INCREMENTAL, window_weeks=4)
    assert start == date(2026, 4, 20)
    assert end == date(2026, 5, 17)


@freeze_time("2026-05-18")
def test_incremental_default_window_is_4():
    start, end = compute_date_range(Mode.INCREMENTAL)
    # 28일 윈도우
    assert (date(2026, 5, 18) - start).days == 28


def test_backfill_uses_db_min(monkeypatch):
    """backfill 은 DB 의 MIN(date) 를 시작점으로."""
    from kr_pipeline.weekly import modes
    monkeypatch.setattr(modes, "_get_daily_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        start, end = compute_date_range(Mode.BACKFILL, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 17)


def test_full_refresh_uses_db_min(monkeypatch):
    """full-refresh 도 backfill 과 같은 범위."""
    from kr_pipeline.weekly import modes
    monkeypatch.setattr(modes, "_get_daily_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        start, end = compute_date_range(Mode.FULL_REFRESH, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 17)


def test_unknown_mode_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown mode"):
        compute_date_range("oops")  # noqa
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_weekly_modes.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: `kr_pipeline/weekly/modes.py` 구현**

```python
"""weekly 모드 분기 + 오케스트레이션."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
import logging

from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.weekly.load import (
    load_daily_for_ticker, load_index_daily, load_active_tickers, get_daily_min_date,
)
from kr_pipeline.weekly.transform import (
    aggregate_to_weekly, drop_incomplete_weeks, to_weekly_rows, to_weekly_index_rows,
)
from kr_pipeline.weekly.store import upsert_weekly_prices, upsert_weekly_index


log = logging.getLogger("kr_pipeline.weekly")


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full-refresh"


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)


def _get_daily_min_date(conn: Connection) -> date:
    d = get_daily_min_date(conn)
    return d if d else date.today()


def compute_date_range(
    mode: Mode,
    *,
    window_weeks: int = 4,
    conn: Connection | None = None,
) -> tuple[date, date]:
    """모드별 일봉 SELECT 범위 (start, end). end 는 항상 어제 까지."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    
    if mode == Mode.INCREMENTAL:
        return today - timedelta(days=window_weeks * 7), yesterday
    if mode in (Mode.BACKFILL, Mode.FULL_REFRESH):
        return _get_daily_min_date(conn), yesterday
    raise ValueError(f"Unknown mode: {mode}")


def _process_ticker(
    conn: Connection,
    ticker: str,
    start: date,
    end: date,
    today: date,
) -> int:
    """한 종목의 일봉을 SELECT → 집계 → UPSERT. 영향받은 행수 반환."""
    daily = load_daily_for_ticker(conn, ticker, start, end)
    if daily.empty:
        return 0
    weekly = aggregate_to_weekly(daily)
    weekly = drop_incomplete_weeks(weekly, today)
    if weekly.empty:
        return 0
    rows = to_weekly_rows(ticker, weekly)
    affected = upsert_weekly_prices(conn, rows)
    conn.commit()
    return affected


def _process_index(
    conn: Connection,
    index_code: str,
    start: date,
    end: date,
    today: date,
) -> int:
    """한 지수의 일봉을 SELECT → 집계 → UPSERT."""
    daily = load_index_daily(conn, index_code, start, end)
    if daily.empty:
        return 0
    weekly = aggregate_to_weekly(daily)
    weekly = drop_incomplete_weeks(weekly, today)
    if weekly.empty:
        return 0
    rows = to_weekly_index_rows(index_code, weekly)
    affected = upsert_weekly_index(conn, rows)
    conn.commit()
    return affected


def _run_sanity_checks(conn: Connection) -> list[str]:
    """주봉 적재 후 sanity 검증. 경고 메시지 리스트.
    
    1. 커버리지: 최근 week_end_date 의 weekly 종목 수 / 활성 universe 종목 수 < 90% → 경고
    2. 가격 이상치: close <= 0 or adj_close <= 0
    3. trading_days = 0 인 행
    """
    warnings: list[str] = []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT ticker) FROM weekly_prices
             WHERE week_end_date = (SELECT MAX(week_end_date) FROM weekly_prices)
        """)
        weekly_count = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM stocks WHERE delisted_at IS NULL")
        active_count = cur.fetchone()[0] or 0
        if active_count > 0:
            ratio = weekly_count / active_count
            if ratio < 0.90:
                warnings.append(
                    f"coverage_low: 최근 주봉 종목 {weekly_count}/{active_count} "
                    f"({ratio*100:.1f}%, 임계 90%)"
                )
        
        cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE close <= 0 OR adj_close <= 0")
        bad_price = cur.fetchone()[0] or 0
        if bad_price > 0:
            warnings.append(f"bad_prices: {bad_price} 행이 close 또는 adj_close <= 0")
        
        cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE trading_days = 0")
        zero_days = cur.fetchone()[0] or 0
        if zero_days > 0:
            warnings.append(f"zero_trading_days: {zero_days} 행이 trading_days = 0")
    return warnings


def run(
    conn: Connection,
    mode: Mode,
    *,
    window_weeks: int = 4,
    limit_tickers: int | None = None,
) -> RunStats:
    today = date.today()
    start, end = compute_date_range(mode, window_weeks=window_weeks, conn=conn)
    log.info(f"weekly mode={mode.value} range={start}..{end}")
    
    tickers = load_active_tickers(conn, limit=limit_tickers)
    log.info(f"weekly tickers to process: {len(tickers)}")
    
    params = {
        "window_weeks": window_weeks if mode == Mode.INCREMENTAL else None,
        "limit_tickers": limit_tickers,
        "start": str(start),
        "end": str(end),
    }
    params = {k: v for k, v in params.items() if v is not None}
    
    rows_total = 0
    failures: list[tuple[str, str]] = []
    
    with run_tracking(conn, pipeline="weekly", mode=mode.value, params=params) as state:
        # 종목 처리
        for i, ticker in enumerate(tickers, 1):
            try:
                rows_total += _process_ticker(conn, ticker, start, end, today)
            except Exception as e:
                failures.append((ticker, str(e)))
            if i % 100 == 0:
                log.info(f"weekly progress: {i}/{len(tickers)} (failures: {len(failures)})")
        
        # 1차 실패 재시도
        if failures:
            log.warning(f"Retrying {len(failures)} failed tickers")
            retry_failures: list[tuple[str, str]] = []
            for ticker, _ in failures:
                try:
                    rows_total += _process_ticker(conn, ticker, start, end, today)
                except Exception as e:
                    retry_failures.append((ticker, str(e)))
            failures = retry_failures
        
        # 지수 처리
        for index_code in ("1001", "2001"):
            try:
                rows_total += _process_index(conn, index_code, start, end, today)
            except Exception as e:
                failures.append((index_code, str(e)))
        
        # sanity checks
        warnings = _run_sanity_checks(conn)
        state["warnings"].extend(warnings)
    
    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_weekly_modes.py -v`
Expected: 6 passed

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 57 passed (51 prior + 6 new)

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/weekly/modes.py tests/test_weekly_modes.py
git commit -m "feat(weekly): modes - backfill/incremental/full-refresh 분기 + 오케스트레이션"
```

---

## Task 6: weekly 진입점 (argparse)

**Files:**
- Create: `kr_pipeline/weekly/__main__.py`

- [ ] **Step 1: 구현**

```python
"""weekly 파이프라인 진입점."""
import argparse
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.weekly.modes import Mode, run


log = logging.getLogger("kr_pipeline.weekly")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.weekly")
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--window-weeks", type=int, default=4, help="incremental 윈도우 (주)")
    p.add_argument("--limit-tickers", type=int, default=None, help="테스트용 종목 수 제한")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    
    with connect(cfg.database_url) as conn:
        stats = run(
            conn,
            Mode(args.mode),
            window_weeks=args.window_weeks,
            limit_tickers=args.limit_tickers,
        )
        log.info(
            f"DONE weekly rows_affected={stats.rows_affected} "
            f"failures={len(stats.failures)} warnings={len(stats.warnings)}"
        )
        if stats.warnings:
            for w in stats.warnings:
                log.warning(f"sanity: {w}")
        if stats.failures:
            log.warning(f"Failed tickers: {[t for t, _ in stats.failures[:20]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 헬프 출력 확인**

Run: `uv run python -m kr_pipeline.weekly --help`
Expected:
```
usage: python -m kr_pipeline.weekly [-h] --mode {backfill,incremental,full-refresh}
                                    [--window-weeks WINDOW_WEEKS]
                                    [--limit-tickers LIMIT_TICKERS]
```
exit 0

- [ ] **Step 3: 커밋**

```bash
git add kr_pipeline/weekly/__main__.py
git commit -m "feat(weekly): 진입점 (argparse)"
```

---

## Task 7: 통합 테스트 + 라이브 백필 스모크

**Files:**
- Create: `tests/test_weekly_integration.py`

- [ ] **Step 1: 통합 테스트 작성**

```python
"""weekly 파이프라인 end-to-end 통합 테스트.
실제 Postgres 필요. 네트워크는 안 씀 (DB-to-DB)."""
from datetime import date

import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.weekly.modes import Mode, run


pytestmark = pytest.mark.integration


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM weekly_prices")
        cur.execute("DELETE FROM weekly_index")
        cur.execute("DELETE FROM daily_prices")
        cur.execute("DELETE FROM index_daily")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('WEEKTEST1', 'WEEKTEST2')")
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'weekly'")
    conn.commit()


def _seed_daily(conn):
    """2주치 일봉 + 2종목 + 지수 시드 (실제 daily_prices/index_daily 사용)."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('WEEKTEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('WEEKTEST2', 'T2', 'KOSPI') ON CONFLICT DO NOTHING")
        # Week 1: 2026-05-04(Mon) ~ 2026-05-08(Fri)
        # Week 2: 2026-05-11(Mon) ~ 2026-05-15(Fri)
        days_w1 = [date(2026, 5, d) for d in (4, 5, 6, 7, 8)]
        days_w2 = [date(2026, 5, d) for d in (11, 12, 13, 14, 15)]
        for ticker in ("WEEKTEST1", "WEEKTEST2"):
            for d in days_w1 + days_w2:
                cur.execute(
                    """
                    INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                    VALUES (%s, %s, 100, 110, 90, 105, 105.0, 1000, 105000)
                    """,
                    (ticker, d),
                )
        # 지수 1001 도 시드
        for d in days_w1 + days_w2:
            cur.execute(
                """
                INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                VALUES ('1001', %s, 2500, 2520, 2480, 2510, 1000, 1000000)
                """,
                (d,),
            )
    conn.commit()


def test_backfill_end_to_end(test_db_url):
    """일봉 시드 → backfill → weekly 2주 × 2종목 + 지수 2주."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_daily(conn)
        
        try:
            stats = run(conn, Mode.BACKFILL, limit_tickers=2)
            
            assert stats.rows_affected >= 4  # 2종목 × 2주 + 지수 2주 = 6
            
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker LIKE 'WEEKTEST%'")
                assert cur.fetchone()[0] == 4  # 2주 × 2종목
                cur.execute("SELECT COUNT(*) FROM weekly_index WHERE index_code = '1001'")
                assert cur.fetchone()[0] == 2  # 2주
                cur.execute(
                    "SELECT close, trading_days FROM weekly_prices "
                    "WHERE ticker = 'WEEKTEST1' AND week_end_date = '2026-05-15'"
                )
                assert cur.fetchone() == (105, 5)
                cur.execute("SELECT pipeline, mode, status FROM pipeline_runs ORDER BY id DESC LIMIT 1")
                assert cur.fetchone() == ("weekly", "backfill", "success")
        finally:
            _cleanup(conn)


def test_incremental_overwrites_existing(test_db_url):
    """incremental 두 번 돌려도 결과 동일 (멱등)."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_daily(conn)
        
        try:
            run(conn, Mode.BACKFILL, limit_tickers=2)
            run(conn, Mode.INCREMENTAL, window_weeks=4, limit_tickers=2)
            
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker LIKE 'WEEKTEST%'")
                # 멱등: 여전히 4행
                assert cur.fetchone()[0] == 4
        finally:
            _cleanup(conn)


def test_partial_failure_isolates(test_db_url):
    """한 종목 변환 실패 → 다른 종목은 정상 적재."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('WEEKTEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('WEEKTEST2', 'T2', 'KOSPI') ON CONFLICT DO NOTHING")
            # WEEKTEST1: 정상 데이터 (5/4 ~ 5/8)
            for d in [date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 8)]:
                cur.execute(
                    """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                       VALUES ('WEEKTEST1', %s, 100, 110, 90, 105, 105.0, 1000, 105000)""",
                    (d,),
                )
            # WEEKTEST2: 데이터 없음 (load_daily_for_ticker 가 빈 DataFrame 반환 → continue, 실패 아님)
        conn.commit()
        
        try:
            stats = run(conn, Mode.BACKFILL, limit_tickers=2)
            
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker = 'WEEKTEST1'")
                assert cur.fetchone()[0] == 1  # 1주
                cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker = 'WEEKTEST2'")
                assert cur.fetchone()[0] == 0  # 없음
        finally:
            _cleanup(conn)
```

- [ ] **Step 2: 통합 테스트 실행**

Run: `uv run pytest tests/test_weekly_integration.py -v -m integration 2>&1 | tail -15`
Expected: 3 passed

- [ ] **Step 3: 전체 테스트 회귀 확인**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 60 passed (57 prior + 3 new integration)

- [ ] **Step 4: 라이브 backfill 스모크 (실제 production DB 사용)**

이 단계는 진짜 데이터를 다룹니다. 현재 production DB 의 `daily_prices` 는 약 50 행 (10 종목 × 5 일, #1 스모크 잔재). 적은 데이터지만 backfill 검증에는 충분.

Run: `uv run python -m kr_pipeline.weekly --mode=backfill 2>&1 | tail -20`

Expected:
- 정상 종료 (exit 0)
- 로그에 `weekly mode=backfill range=...` 나옴
- DONE 로그가 `rows_affected=N` 으로 종료, N >= 12 정도 (10 종목 × 1 ~ 2 주 + 지수)
- sanity warning 1 개 정도 (coverage_low — 2,550 active 중 weekly 행 있는 종목은 ~10 개 뿐이라 < 90%)

DB 검증:
```bash
psql postgresql://localhost/kr_pipeline -c "SELECT COUNT(*) FROM weekly_prices"
psql postgresql://localhost/kr_pipeline -c "SELECT COUNT(DISTINCT ticker) FROM weekly_prices"
psql postgresql://localhost/kr_pipeline -c "SELECT * FROM weekly_prices LIMIT 3"
psql postgresql://localhost/kr_pipeline -c "SELECT * FROM weekly_index"
psql postgresql://localhost/kr_pipeline -c "SELECT pipeline, mode, status, LEFT(error,80) FROM pipeline_runs ORDER BY id DESC LIMIT 3"
```

Expected:
- `weekly_prices`: 10 ~ 20 행 (10 종목 × 1 ~ 2 주, 미완성 주 제외)
- `weekly_index`: 1 ~ 2 행 (지수 1001 만 — `index_daily` 에 1001 만 있음 추정)
- 합리적 값 (close 가 daily_prices 마지막 close 와 일치)
- pipeline_runs 최근: `weekly | backfill | success` 와 coverage_low 경고

- [ ] **Step 5: 커밋**

```bash
git add tests/test_weekly_integration.py
git commit -m "test(weekly): end-to-end 통합 테스트 (backfill, 멱등, 부분 실패 격리)"
```

---

## Task 8: Cron + README 업데이트

**Files:**
- Modify: `scripts/cron.example` (append)
- Modify: `README.md` (append to existing sections)

- [ ] **Step 1: `scripts/cron.example` 끝에 추가**

```cron

# 매주 토요일 03:00, 지난 주 주봉 incremental
0 3 * * 6  cd $PROJECT_DIR && uv run python -m kr_pipeline.weekly --mode=incremental --window-weeks=4 >> $LOG_DIR/weekly.log 2>&1

# 매월 1일 03:00, 주봉 full-refresh (일봉 full-refresh 02:00 이후 trigger)
0 3 1 * *  cd $PROJECT_DIR && uv run python -m kr_pipeline.weekly --mode=full-refresh >> $LOG_DIR/weekly.log 2>&1
```

- [ ] **Step 2: `README.md` 실행 섹션에 주봉 명령 추가**

기존 `## 실행` 섹션 끝에 추가:
```markdown
- 주봉 백필: `uv run python -m kr_pipeline.weekly --mode=backfill`
- 주봉 증분: `uv run python -m kr_pipeline.weekly --mode=incremental --window-weeks=4`
- 주봉 재적재: `uv run python -m kr_pipeline.weekly --mode=full-refresh`
```

`## 운영 점검 쿼리` 섹션의 SQL 블록 끝에 추가:
```sql

-- 가장 최근 주봉 종목 수
SELECT week_end_date, COUNT(DISTINCT ticker) 
FROM weekly_prices 
WHERE week_end_date = (SELECT MAX(week_end_date) FROM weekly_prices)
GROUP BY 1;

-- 종목별 주봉 카운트 분포 (상위 10)
SELECT ticker, COUNT(*) AS week_count 
FROM weekly_prices 
GROUP BY ticker 
ORDER BY 2 DESC LIMIT 10;
```

- [ ] **Step 3: 커밋**

```bash
git add scripts/cron.example README.md
git commit -m "docs(weekly): cron 등록 + README 실행/운영 쿼리"
```

---

## Task 9: 최종 Goal State 검증

이 task 는 코드 변경 없음. 자율 실행자가 마지막에 검증.

- [ ] **Step 1: 전체 테스트 통과**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 60 passed (35 #1 + 25 #1.5).

- [ ] **Step 2: 통합 테스트 분리 실행**

Run: `uv run pytest -m integration -v 2>&1 | tail -10`
Expected: 4 passed (1 #1 integration + 3 #1.5 integration)

- [ ] **Step 3: 라이브 backfill 스모크 (재실행)**

Run: `uv run python -m kr_pipeline.weekly --mode=backfill 2>&1 | tail -10`
Expected: 정상 종료, DONE 로그 출력

- [ ] **Step 4: incremental 스모크 (검증)**

Run: `uv run python -m kr_pipeline.weekly --mode=incremental --window-weeks=4 2>&1 | tail -10`
Expected: 정상 종료, weekly_prices 행수 변화 없거나 같음 (멱등)

- [ ] **Step 5: DB 최종 상태 확인**

Run:
```bash
psql postgresql://localhost/kr_pipeline -c "
SELECT 'weekly_prices' AS t, COUNT(*) FROM weekly_prices
UNION ALL SELECT 'weekly_index', COUNT(*) FROM weekly_index
UNION ALL SELECT 'pipeline_runs weekly', COUNT(*) FROM pipeline_runs WHERE pipeline='weekly'
"
```
Expected: weekly_prices > 0, weekly_index > 0, pipeline_runs weekly >= 2

- [ ] **Step 6: git status 깨끗한지 확인**

Run: `git status`
Expected: `nothing to commit, working tree clean`

- [ ] **Step 7: 종료 보고**

위 6 단계 모두 통과 → 사용자에게 짧게 보고:
```
Weekly 파이프라인 (서브프로젝트 #1.5) 완료.
- backfill / incremental / full-refresh 3 모드 동작
- 60 passed (#1 + #1.5)
- 라이브 backfill 스모크 통과
- DB 상태: weekly_prices N행, weekly_index M행
다음: 서브프로젝트 #2 (지표 생성)
```

---

## Self-Review (계획 작성자 메모)

- ✅ Spec 의 모든 결정 사항이 task 에 매핑됨 (3 모드, 종목별 순차, 미완성 주 제외, sanity checks, run_tracking 재사용, schema.sql 에 weekly 테이블 추가)
- ✅ Placeholder 없음 — 모든 step 의 코드/SQL/명령은 그대로 실행 가능
- ✅ 타입/시그니처 일관성:
  - `aggregate_to_weekly`, `drop_incomplete_weeks`, `to_weekly_rows`, `to_weekly_index_rows` 가 일관됨
  - `upsert_weekly_prices(conn, rows)`, `upsert_weekly_index(conn, rows)` 모두 `int` 반환
  - `Mode` enum / `compute_date_range` / `run` 시그니처 일관
  - `RunStats` 는 #1 과 동일 구조 (rows_affected, failures, warnings)
- ⚠️ 알려진 트레이드오프:
  - `to_period("W-SUN")` 사용 — 월요일~일요일을 한 주로 묶음. 대부분의 의도와 부합. 한국 시장 영업일이 월~금이므로 토/일이 같은 주에 묶여도 데이터 없음 (영향 없음)
  - pandas `apply` 안에 `iloc[0]` 사용 — 단순한 표현이지만 큰 group 에서는 약간 느림. 종목별 ~500 행 처리라 무시 가능
- ⚠️ 자율 실행자 주의:
  - 만약 `aggregate_to_weekly` 의 `groupby.apply` 가 pandas 버전 차이로 `include_groups=False` 미지원 시 deprecation warning 만 무시하고 통과
  - 만약 통합 테스트의 `_seed_daily` 가 외래키 제약으로 실패 시 (stocks 가 먼저 있어야 함) — 코드 순서 그대로 따르면 됨

자율 실행자는 위 ⚠️ 항목을 인지하고 진행할 것.
