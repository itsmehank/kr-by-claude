# 지표 생성 파이프라인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 일봉/주봉/지수 데이터에서 SMA, 52w high/low, RS Line, RS Rating, 미너비니 8조건 + 종합 통과를 생성·적재하는 `kr_pipeline.indicators` Python 패키지 구현.

**Architecture:** 단일 패키지 + 모드 인자 진입점 (#1, #1.5 와 동일 패턴). `compute/*` 순수 함수 + `load`/`store` DB IO 분리. 3 phase 처리: A (종목별 시계열 지표 + minervini c1-c7), B (날짜별 RS Rating), C (단일 SQL UPDATE 로 c8 + pass). 외부 IO 없음 (DB-to-DB).

**Tech Stack:** Python 3.11+, uv, psycopg[binary], pandas, numpy, pytest, freezegun (모두 이미 설치됨, 신규 의존성 없음)

**Spec:** [`../specs/2026-05-16-indicators-pipeline-design.md`](../specs/2026-05-16-indicators-pipeline-design.md)

---

## ⚙️ Autonomous Execution Protocol

**이 계획은 자율 실행 모드로 동작합니다.** 실행자는 사용자 확인을 기다리지 않고 아래 규칙을 따른다.

### Goal State

다음 조건을 **모두** 만족하면 작업 종료:

1. 본 계획의 모든 task 체크박스 (`- [ ]` → `- [x]`) 가 체크됨
2. `uv run pytest tests/` — 전체 테스트 통과 (exit code 0). 직전 기준 68 passed → 본 계획 완료 후 ~118 passed 예상
3. **스모크 테스트 통과**:
   - `uv run python -m kr_pipeline.indicators --target=daily --mode=backfill` 가 에러 없이 종료
   - DB 확인: `daily_indicators` 테이블에 합리적 행수 (>= 10) 및 `minervini_pass` 컬럼이 정상 boolean
4. `git status` — uncommitted 변경 없음
5. `pipeline_runs` 에 최소 1 개의 `indicators | backfill | success` 행 존재

### 실행 루프

각 task 마다:
```
1. task 시작 → 체크박스 [in_progress]
2. step 들 순서대로 (test → fail 확인 → 구현 → pass 확인 → commit)
3. 검증 명령의 expected output 과 실제 비교
4. 일치 → [x] → 다음 task
5. 불일치 → 진단 → 수정 → 재검증 (최대 3 회)
6. 3 회 동일 에러 → 사용자 보고 후 정지
7. 모든 task 완료 → Goal State 검증 → 종료
```

### Stuck Rules

- 같은 에러 메시지 **3 회 반복** → 즉시 정지, 보고
- **외부 환경 문제** (DB 다운, schema migration 실패) → 즉시 정지, 사용자에게 셋업 요청
- **사양 모호성 발견** → 즉시 정지, 명확화 요청
- 그 외 모든 실패 → **스스로 진단/수정/재시도**

### 무엇을 하지 말 것

- "다음 task 진행할까요?" 확인 질문 금지
- 사양 외 기능 추가 금지 (YAGNI — 거래량 지표는 V2)
- 신규 라이브러리 추가 금지
- 기존 모듈 (#1, #1.5) 변경 금지 (단, `kr_pipeline/db/schema.sql` 끝에 indicators 테이블 추가는 예외)

---

## 사전 조건

- #1, #1.5 완료 상태 — `kr_pipeline/{common,db,universe,ohlcv,weekly}` 모듈 존재
- PostgreSQL 실행 중, `kr_pipeline` / `kr_test` DB 에 #1, #1.5 스키마 적용 완료
- `daily_prices` 와 `weekly_prices` 에 일정 데이터 (스모크 테스트용 최소 10 종목 × 300+ 영업일치 권장)
- `.env` 에 `DATABASE_URL` / `TEST_DATABASE_URL` 설정

스모크 테스트용 충분한 일봉 데이터 확보 권장 — `daily_prices` 가 적으면 lookback 부족으로 NULL 만 나옴.

---

## 파일 구조 (참조용)

```
kr_pipeline/
├── db/
│   └── schema.sql                    # ← 끝에 daily_indicators, weekly_indicators 추가
├── indicators/                       # ← 신규
│   ├── __init__.py
│   ├── __main__.py
│   ├── modes.py                      # 3 phase 분기 + 오케스트레이션
│   ├── compute/
│   │   ├── __init__.py
│   │   ├── sma.py                    # SMA(n)
│   │   ├── high_low.py               # 52w high/low + pct
│   │   ├── rs_line.py                # 비율 + booleans + 52w_high_date
│   │   ├── rs_rating.py              # 1년 수익률 백분위 (universe 단위)
│   │   └── minervini.py              # 8 조건 (c1-c7 in Python, c8+pass in SQL)
│   ├── load.py                       # SELECT 헬퍼
│   └── store.py                      # UPSERT 헬퍼
└── (기존 모듈 변경 없음)

tests/
├── test_indicators_sma.py
├── test_indicators_high_low.py
├── test_indicators_rs_line.py
├── test_indicators_rs_rating.py
├── test_indicators_minervini.py
├── test_indicators_store.py
├── test_indicators_modes.py
└── test_indicators_integration.py

scripts/cron.example                  # ← 끝에 indicators cron 4 라인 추가
README.md                             # ← 실행 + 운영 쿼리에 indicators 추가
```

---

## Task 1: DB 스키마 추가

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (append)

- [ ] **Step 1: `kr_pipeline/db/schema.sql` 끝에 추가**

```sql

-- ====== Indicators (#2) ======

CREATE TABLE IF NOT EXISTS daily_indicators (
    ticker            VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    date              DATE          NOT NULL,
    
    adj_close         NUMERIC(12,4) NOT NULL,
    
    sma_10            NUMERIC(12,4),
    sma_21            NUMERIC(12,4),       -- VCP / 단기 모멘텀 분석용 (Trend Template 외)
    sma_50            NUMERIC(12,4),
    sma_150           NUMERIC(12,4),
    sma_200           NUMERIC(12,4),
    
    w52_high          NUMERIC(12,4),
    w52_low           NUMERIC(12,4),
    pct_from_52w_high NUMERIC(8,4),
    pct_from_52w_low  NUMERIC(8,4),
    
    rs_line               NUMERIC(16,8),
    rs_line_52w_high      NUMERIC(16,8),
    rs_line_52w_high_date DATE,
    rs_line_at_52w_high   BOOLEAN,
    rs_line_uptrend_6w    BOOLEAN,
    rs_line_uptrend_13w   BOOLEAN,
    rs_line_in_decline_7m BOOLEAN,
    
    rs_rating         SMALLINT,
    
    minervini_c1      BOOLEAN,
    minervini_c2      BOOLEAN,
    minervini_c3      BOOLEAN,
    minervini_c4      BOOLEAN,
    minervini_c5      BOOLEAN,
    minervini_c6      BOOLEAN,
    minervini_c7      BOOLEAN,
    minervini_c8      BOOLEAN,
    minervini_pass    BOOLEAN,
    
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_indicators_date ON daily_indicators(date);
CREATE INDEX IF NOT EXISTS idx_daily_indicators_minervini ON daily_indicators(date, minervini_pass)
    WHERE minervini_pass = TRUE;
CREATE INDEX IF NOT EXISTS idx_daily_indicators_rs ON daily_indicators(date, rs_rating)
    WHERE rs_rating >= 70;
CREATE INDEX IF NOT EXISTS idx_daily_indicators_analyst_target ON daily_indicators(date, rs_rating)
    WHERE minervini_pass = TRUE AND rs_rating >= 80;

CREATE TABLE IF NOT EXISTS weekly_indicators (
    ticker            VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    week_end_date     DATE          NOT NULL,
    
    adj_close         NUMERIC(12,4) NOT NULL,
    
    sma_10w           NUMERIC(12,4),
    sma_30w           NUMERIC(12,4),
    sma_40w           NUMERIC(12,4),
    
    w52_high          NUMERIC(12,4),
    w52_low           NUMERIC(12,4),
    pct_from_52w_high NUMERIC(8,4),
    pct_from_52w_low  NUMERIC(8,4),
    
    rs_line               NUMERIC(16,8),
    rs_line_52w_high      NUMERIC(16,8),
    rs_line_52w_high_date DATE,
    rs_line_at_52w_high   BOOLEAN,
    rs_line_uptrend_6w    BOOLEAN,
    rs_line_uptrend_13w   BOOLEAN,
    rs_line_in_decline_7m BOOLEAN,
    
    rs_rating         SMALLINT,
    
    minervini_c1      BOOLEAN,
    minervini_c2      BOOLEAN,
    minervini_c3      BOOLEAN,
    minervini_c4      BOOLEAN,
    minervini_c5      BOOLEAN,
    minervini_c6      BOOLEAN,
    minervini_c7      BOOLEAN,
    minervini_c8      BOOLEAN,
    minervini_pass    BOOLEAN,
    
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, week_end_date)
);
CREATE INDEX IF NOT EXISTS idx_weekly_indicators_date ON weekly_indicators(week_end_date);
CREATE INDEX IF NOT EXISTS idx_weekly_indicators_minervini ON weekly_indicators(week_end_date, minervini_pass)
    WHERE minervini_pass = TRUE;
```

- [ ] **Step 2: 두 DB 에 적용**

```bash
psql postgresql://localhost/kr_pipeline -f kr_pipeline/db/schema.sql
psql postgresql://localhost/kr_test -f kr_pipeline/db/schema.sql
```

Expected: `CREATE TABLE` / `CREATE INDEX` 출력, 에러 없음.

- [ ] **Step 3: 검증**

```bash
psql postgresql://localhost/kr_pipeline -c "\d daily_indicators"
psql postgresql://localhost/kr_pipeline -c "\d weekly_indicators"
```

Expected: 모든 컬럼 존재, PK = `(ticker, date)` / `(ticker, week_end_date)`. 4 개 인덱스 (daily) + 2 개 인덱스 (weekly).

- [ ] **Step 4: 빈 패키지 디렉토리 생성**

```bash
mkdir -p kr_pipeline/indicators/compute tests
touch kr_pipeline/indicators/__init__.py
touch kr_pipeline/indicators/compute/__init__.py
```

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/db/schema.sql kr_pipeline/indicators/__init__.py kr_pipeline/indicators/compute/__init__.py
git commit -m "feat(indicators): DB 스키마 추가 (daily_indicators, weekly_indicators)"
```

---

## Task 2: compute/sma.py — SMA(n) 단순 평균 (TDD)

**Files:**
- Create: `kr_pipeline/indicators/compute/sma.py`
- Create: `tests/test_indicators_sma.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_indicators_sma.py
import pandas as pd
import pytest
from kr_pipeline.indicators.compute.sma import sma


def test_sma_basic_5_day():
    """5일 SMA: 마지막 5개 평균."""
    s = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0])
    result = sma(s, window=5)
    # 4번째 인덱스(5번째 값)부터 시작: mean(10,20,30,40,50)=30
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[3])
    assert result.iloc[4] == 30.0   # mean(10..50)
    assert result.iloc[5] == 40.0   # mean(20..60)
    assert result.iloc[6] == 50.0   # mean(30..70)


def test_sma_insufficient_history_returns_nan():
    """window 보다 짧으면 모두 NaN."""
    s = pd.Series([10.0, 20.0])
    result = sma(s, window=5)
    assert result.isna().all()


def test_sma_handles_nan_in_input():
    """입력 중간에 NaN 이 있으면 그 윈도우 결과도 NaN."""
    import numpy as np
    s = pd.Series([10.0, 20.0, np.nan, 40.0, 50.0, 60.0])
    result = sma(s, window=3)
    # 첫 두 행: NaN (히스토리 부족), 3번째: window 안에 NaN 있어 NaN, ...
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])  # 10, 20, NaN
    assert pd.isna(result.iloc[3])  # 20, NaN, 40
    assert pd.isna(result.iloc[4])  # NaN, 40, 50
    assert result.iloc[5] == 50.0   # 40, 50, 60


def test_sma_preserves_index():
    """입력 Series 의 index 그대로 유지."""
    s = pd.Series([10.0, 20.0, 30.0], index=pd.date_range("2026-01-01", periods=3))
    result = sma(s, window=2)
    assert list(result.index) == list(s.index)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_indicators_sma.py -v`
Expected: ImportError

- [ ] **Step 3: 구현**

```python
# kr_pipeline/indicators/compute/sma.py
"""단순 이동 평균 (Simple Moving Average) 순수 함수."""
import pandas as pd


def sma(adj_close: pd.Series, window: int) -> pd.Series:
    """SMA(window). 수정종가 입력 필수.
    
    데이터가 window 일치 미만이면 NaN.
    window 안에 NaN 이 있으면 결과도 NaN (pandas 기본).
    """
    return adj_close.rolling(window=window, min_periods=window).mean()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_indicators_sma.py -v`
Expected: 4 passed

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 72 passed (68 prior + 4 new)

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/indicators/compute/sma.py tests/test_indicators_sma.py
git commit -m "feat(indicators): compute/sma - SMA(n) 단순 이동 평균"
```

---

## Task 3: compute/high_low.py — 52주 high/low + pct (TDD)

**Files:**
- Create: `kr_pipeline/indicators/compute/high_low.py`
- Create: `tests/test_indicators_high_low.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_indicators_high_low.py
import pandas as pd
import pytest
from kr_pipeline.indicators.compute.high_low import w52_high_low, pct_from_high_low


def test_high_low_basic():
    """충분한 데이터: rolling max/min."""
    s = pd.Series([10.0, 20.0, 30.0, 25.0, 15.0])
    h, l = w52_high_low(s, window=3)
    # 처음 2개: NaN (history 부족), index 2부터: max/min(10,20,30)
    assert pd.isna(h.iloc[0])
    assert pd.isna(l.iloc[0])
    assert h.iloc[2] == 30.0 and l.iloc[2] == 10.0
    assert h.iloc[3] == 30.0 and l.iloc[3] == 20.0
    assert h.iloc[4] == 30.0 and l.iloc[4] == 15.0


def test_high_low_window_size_252_default():
    """기본 window=252."""
    s = pd.Series(range(300), dtype=float)
    h, l = w52_high_low(s)  # default window=252
    # 251번째 이전: NaN
    assert h.isna().iloc[:251].all()
    # 251번째: max(0..251)=251
    assert h.iloc[251] == 251.0
    assert l.iloc[251] == 0.0


def test_high_low_insufficient_history():
    """window 미만 → 전부 NaN."""
    s = pd.Series([10.0, 20.0])
    h, l = w52_high_low(s, window=5)
    assert h.isna().all()
    assert l.isna().all()


def test_pct_from_high_low_basic():
    """pct = (close - high)/high * 100 (음수), (close - low)/low * 100 (양수)."""
    close = pd.Series([100.0, 110.0, 120.0])
    high = pd.Series([130.0, 130.0, 130.0])
    low = pd.Series([80.0, 80.0, 80.0])
    pct_h, pct_l = pct_from_high_low(close, high, low)
    # close=100, high=130: (100-130)/130*100 = -23.08
    assert abs(pct_h.iloc[0] - (-23.076923)) < 0.001
    # close=100, low=80: (100-80)/80*100 = 25.0
    assert pct_l.iloc[0] == 25.0


def test_pct_from_high_low_handles_nan():
    """high/low 가 NaN 이면 pct 도 NaN."""
    import numpy as np
    close = pd.Series([100.0, 110.0])
    high = pd.Series([np.nan, 130.0])
    low = pd.Series([80.0, np.nan])
    pct_h, pct_l = pct_from_high_low(close, high, low)
    assert pd.isna(pct_h.iloc[0])
    assert pd.isna(pct_l.iloc[1])


def test_high_low_preserves_index():
    """입력 Series index 유지."""
    idx = pd.date_range("2026-01-01", periods=5)
    s = pd.Series([10.0, 20.0, 30.0, 25.0, 15.0], index=idx)
    h, l = w52_high_low(s, window=3)
    assert list(h.index) == list(idx)
    assert list(l.index) == list(idx)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_high_low.py -v`
Expected: ImportError

- [ ] **Step 3: 구현**

```python
# kr_pipeline/indicators/compute/high_low.py
"""52주 high/low 및 현재가 위치 백분율 순수 함수."""
import pandas as pd


def w52_high_low(adj_close: pd.Series, window: int = 252) -> tuple[pd.Series, pd.Series]:
    """52주(기본 252영업일) rolling max/min.
    
    데이터가 window 미만이면 NaN.
    """
    high = adj_close.rolling(window=window, min_periods=window).max()
    low = adj_close.rolling(window=window, min_periods=window).min()
    return high, low


def pct_from_high_low(
    adj_close: pd.Series,
    high: pd.Series,
    low: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """현재가의 52주 high / low 대비 위치 (백분율).
    
    pct_from_high = (adj_close - high) / high * 100  (보통 음수, 0이면 신고가)
    pct_from_low  = (adj_close - low) / low * 100   (보통 양수, 0이면 신저가)
    """
    pct_h = (adj_close - high) / high * 100
    pct_l = (adj_close - low) / low * 100
    return pct_h, pct_l
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_high_low.py -v`
Expected: 6 passed

- [ ] **Step 5: 전체 회귀**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 78 passed

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/indicators/compute/high_low.py tests/test_indicators_high_low.py
git commit -m "feat(indicators): compute/high_low - 52주 high/low + pct"
```

---

## Task 4: compute/rs_line.py — RS Line + booleans + 52w_high_date (TDD)

**Files:**
- Create: `kr_pipeline/indicators/compute/rs_line.py`
- Create: `tests/test_indicators_rs_line.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_indicators_rs_line.py
from datetime import date
import pandas as pd
import numpy as np
import pytest
from kr_pipeline.indicators.compute.rs_line import (
    compute_rs_line,
    compute_rs_line_52w_high_and_date,
    compute_rs_line_at_52w_high,
    compute_rs_line_uptrend,
    compute_rs_line_in_decline_7m,
)


def test_rs_line_basic_ratio():
    """rs_line = adj_close_stock / close_index"""
    stock = pd.Series([1000.0, 1100.0, 1200.0])
    index_close = pd.Series([2500.0, 2500.0, 2400.0])
    result = compute_rs_line(stock, index_close)
    assert result.iloc[0] == 0.4         # 1000/2500
    assert result.iloc[1] == 0.44        # 1100/2500
    assert result.iloc[2] == 0.5         # 1200/2400


def test_rs_line_nan_when_either_missing():
    """둘 중 하나 NaN 이면 결과 NaN"""
    stock = pd.Series([1000.0, np.nan, 1200.0])
    index_close = pd.Series([2500.0, 2500.0, np.nan])
    result = compute_rs_line(stock, index_close)
    assert result.iloc[0] == 0.4
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])


def test_rs_line_52w_high_and_date_tracked():
    """52주(252영업일) rolling 신고가 및 해당 날짜 기록."""
    idx = pd.date_range("2026-01-01", periods=10, freq="D").date
    rs = pd.Series([0.3, 0.5, 0.4, 0.6, 0.55, 0.7, 0.65, 0.6, 0.55, 0.5], index=idx)
    high, high_date = compute_rs_line_52w_high_and_date(rs, window=3)
    # window=3 (테스트용으로 짧게): 처음 2개는 NaN
    assert pd.isna(high.iloc[0])
    assert pd.isna(high_date.iloc[0])
    # index 2: max(0.3, 0.5, 0.4) = 0.5 → idx[1]
    assert high.iloc[2] == 0.5
    assert high_date.iloc[2] == idx[1]
    # index 5: max(0.6, 0.55, 0.7) = 0.7 → idx[5]
    assert high.iloc[5] == 0.7
    assert high_date.iloc[5] == idx[5]


def test_rs_line_at_52w_high_today():
    """오늘 RS Line == 52주 max → True"""
    rs = pd.Series([0.5, 0.6, 0.7])
    high = pd.Series([0.7, 0.7, 0.7])
    result = compute_rs_line_at_52w_high(rs, high)
    assert result.iloc[2] == True   # rs[2]==high[2]
    assert result.iloc[0] == False  # rs[0]<high[0]


def test_rs_line_uptrend_when_above_rolling_mean():
    """rs_line > rolling_mean → True (spec 정의)"""
    # rs increasing → rs > rolling_mean
    rs = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7])
    result = compute_rs_line_uptrend(rs, window=3)
    # rolling mean at index 2 = (0.1+0.2+0.3)/3 = 0.2; rs=0.3 > 0.2 → True
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == True
    assert result.iloc[6] == True


def test_rs_line_uptrend_false_when_below():
    """rs_line < rolling_mean → False"""
    rs = pd.Series([0.7, 0.6, 0.5, 0.4, 0.3])
    result = compute_rs_line_uptrend(rs, window=3)
    # mean(0.7, 0.6, 0.5) = 0.6, rs[2]=0.5 < 0.6 → False
    assert result.iloc[2] == False


def test_rs_line_in_decline_7m_when_high_was_long_ago():
    """rs_line_52w_high_date 가 140 영업일 이상 전 → True"""
    idx = pd.date_range("2026-01-01", periods=300, freq="D").date
    # high_date: 모두 idx[10] (오래 전)
    high_date = pd.Series([idx[10]] * 300, index=idx)
    # current_date 는 인덱스가 곧 날짜
    current_dates = pd.Series(idx, index=idx)
    result = compute_rs_line_in_decline_7m(high_date, current_dates, threshold_days=140)
    # idx[10] = 2026-01-11, idx[10+140] = ~ 2026-05-31
    # 0~149번 index: 차이 < 140
    # 150번 index 이후: 차이 >= 140
    assert result.iloc[10] == False    # 같은 날
    assert result.iloc[100] == False   # 90일 차이
    assert result.iloc[150] == True    # 140일 차이
    assert result.iloc[200] == True


def test_rs_line_in_decline_handles_nan_high_date():
    """high_date 가 NaN 이면 결과 NaN"""
    idx = pd.date_range("2026-01-01", periods=3).date
    high_date = pd.Series([pd.NaT, idx[0], idx[0]], index=idx)
    current_dates = pd.Series(idx, index=idx)
    result = compute_rs_line_in_decline_7m(high_date, current_dates, threshold_days=140)
    assert pd.isna(result.iloc[0])


def test_rs_line_insufficient_history_returns_null():
    """충분한 lookback 없으면 NaN"""
    rs = pd.Series([0.5, 0.6])
    high, _ = compute_rs_line_52w_high_and_date(rs, window=5)
    assert high.isna().all()


def test_rs_line_preserves_index():
    """index 유지"""
    idx = pd.date_range("2026-01-01", periods=3)
    stock = pd.Series([1000.0, 1100.0, 1200.0], index=idx)
    index_close = pd.Series([2500.0, 2500.0, 2400.0], index=idx)
    result = compute_rs_line(stock, index_close)
    assert list(result.index) == list(idx)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_rs_line.py -v`
Expected: ImportError

- [ ] **Step 3: 구현**

```python
# kr_pipeline/indicators/compute/rs_line.py
"""RS Line: 종목 수정종가 / 벤치마크 종가. 그리고 책 신호 booleans."""
from datetime import date as _date
import pandas as pd


def compute_rs_line(adj_close_stock: pd.Series, close_index: pd.Series) -> pd.Series:
    """RS Line = adj_close_stock / close_index.
    
    종목은 수정종가, 지수는 close (지수는 수정 개념 없음 — 의도된 비대칭).
    """
    return adj_close_stock / close_index


def compute_rs_line_52w_high_and_date(
    rs_line: pd.Series,
    window: int = 252,
) -> tuple[pd.Series, pd.Series]:
    """RS Line 의 rolling max 와 그 max 가 된 날짜.
    
    index 는 날짜여야 함 (DatetimeIndex 또는 date 객체 리스트).
    """
    high = rs_line.rolling(window=window, min_periods=window).max()
    
    # argmax 위치 → 해당 날짜 (rolling apply 로 idx 추적)
    def _argmax_date(window_values):
        if window_values.isna().any():
            return None
        max_pos = window_values.values.argmax()
        return window_values.index[max_pos]
    
    high_date = rs_line.rolling(window=window, min_periods=window).apply(
        lambda x: x.values.argmax(),
        raw=False,
    )
    # high_date 는 offset (0..window-1). 실제 날짜로 변환.
    n = len(rs_line)
    high_date_series = pd.Series([None] * n, index=rs_line.index, dtype=object)
    for i in range(window - 1, n):
        if pd.isna(high_date.iloc[i]):
            continue
        offset = int(high_date.iloc[i])
        window_start = i - window + 1
        high_date_series.iloc[i] = rs_line.index[window_start + offset]
    
    return high, high_date_series


def compute_rs_line_at_52w_high(rs_line: pd.Series, rs_line_52w_high: pd.Series) -> pd.Series:
    """오늘 RS Line 이 52주 신고가 (rolling max) 와 같은가."""
    return rs_line == rs_line_52w_high


def compute_rs_line_uptrend(rs_line: pd.Series, window: int) -> pd.Series:
    """rs_line > rolling_mean(window) → 우상향 판정.
    
    window 미만은 NaN.
    """
    rolling_mean = rs_line.rolling(window=window, min_periods=window).mean()
    return rs_line > rolling_mean


def compute_rs_line_in_decline_7m(
    rs_line_52w_high_date: pd.Series,
    current_dates: pd.Series,
    threshold_days: int = 140,
) -> pd.Series:
    """rs_line_52w_high_date 가 current_date 로부터 threshold_days 이상 전 → True.
    
    7개월 ≈ 140 영업일.
    high_date 가 NaN 이면 결과 NaN.
    """
    result = pd.Series([None] * len(current_dates), index=current_dates.index, dtype=object)
    for i in range(len(current_dates)):
        hd = rs_line_52w_high_date.iloc[i]
        cd = current_dates.iloc[i]
        if pd.isna(hd) or pd.isna(cd):
            continue
        # date 객체로 변환
        if isinstance(hd, pd.Timestamp):
            hd = hd.date()
        if isinstance(cd, pd.Timestamp):
            cd = cd.date()
        diff_days = (cd - hd).days
        result.iloc[i] = diff_days >= threshold_days
    return result
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_rs_line.py -v`
Expected: 10 passed

- [ ] **Step 5: 전체 회귀**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 88 passed

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/indicators/compute/rs_line.py tests/test_indicators_rs_line.py
git commit -m "feat(indicators): compute/rs_line - 비율 + booleans + 52w_high_date"
```

---

## Task 5: compute/rs_rating.py — 1년 수익률 백분위 (TDD)

**Files:**
- Create: `kr_pipeline/indicators/compute/rs_rating.py`
- Create: `tests/test_indicators_rs_rating.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_indicators_rs_rating.py
import pandas as pd
import numpy as np
import pytest
from kr_pipeline.indicators.compute.rs_rating import (
    compute_1y_return,
    assign_rs_rating_percentiles,
)


def test_1y_return_basic():
    """1년 수익률 = (close[t] / close[t-window]) - 1"""
    s = pd.Series([100.0, 110.0, 120.0, 130.0, 140.0])
    result = compute_1y_return(s, window=3)
    # index 3: close[3]/close[0] - 1 = 130/100 - 1 = 0.3
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[2])
    assert abs(result.iloc[3] - 0.3) < 0.001
    assert abs(result.iloc[4] - 0.4) < 0.001  # 140/100-1


def test_1y_return_insufficient_history():
    """history 부족 시 NaN"""
    s = pd.Series([100.0, 110.0])
    result = compute_1y_return(s, window=252)
    assert result.isna().all()


def test_assign_percentiles_basic():
    """3개 종목 1년 수익률: 30%, 10%, 50% → 백분위"""
    # ticker -> 1y_return
    returns = pd.Series([0.3, 0.1, 0.5], index=["A", "B", "C"])
    result = assign_rs_rating_percentiles(returns)
    # C (50%) 1등, A (30%) 2등, B (10%) 3등
    # N=3. rank 1 → ((3-1)/3)*99 = 66, rank 2 → ((3-2)/3)*99 = 33, rank 3 → 0
    # 또는 percentile rank: C=99, A=49, B=0 (정의에 따라 다름)
    # 우리 정의: ((N - rank) / N) * 99, rank 1-based
    assert result["C"] == 66  # ((3-1)/3)*99 = 66.0 → 66
    assert result["A"] == 33  # ((3-2)/3)*99 = 33.0 → 33
    assert result["B"] == 0   # ((3-3)/3)*99 = 0


def test_assign_percentiles_excludes_nan():
    """NaN 수익률 종목은 universe 에서 빠지고 결과도 NaN"""
    returns = pd.Series([0.3, np.nan, 0.5, 0.1], index=["A", "B", "C", "D"])
    result = assign_rs_rating_percentiles(returns)
    # B 는 NaN 입력 → NaN 출력
    assert pd.isna(result["B"])
    # 나머지 3개로 백분위: C=66, A=33, D=0
    assert result["C"] == 66
    assert result["A"] == 33
    assert result["D"] == 0


def test_assign_percentiles_handles_ties():
    """같은 수익률 → 같은 백분위 (평균 rank 사용)"""
    returns = pd.Series([0.3, 0.3, 0.1], index=["A", "B", "C"])
    result = assign_rs_rating_percentiles(returns)
    # A, B 동률 1.5등 → ((3-1.5)/3)*99 = 49.5 → 49 또는 50 (rounding 정책)
    # C 3등 → 0
    assert result["A"] == result["B"]
    assert result["C"] == 0
    assert result["A"] >= 49 and result["A"] <= 50
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_rs_rating.py -v`
Expected: ImportError

- [ ] **Step 3: 구현**

```python
# kr_pipeline/indicators/compute/rs_rating.py
"""RS Rating: universe 단위 1년 수익률 백분위 (0~99)."""
import numpy as np
import pandas as pd


def compute_1y_return(adj_close: pd.Series, window: int = 252) -> pd.Series:
    """1년 수익률 = adj_close[t] / adj_close[t-window] - 1.
    
    window 미만은 NaN.
    """
    return adj_close.pct_change(periods=window)


def assign_rs_rating_percentiles(returns: pd.Series) -> pd.Series:
    """universe 의 1년 수익률 → 백분위 (0~99) 매핑.
    
    NaN 입력 종목은 NaN 출력 (universe 에서 제외).
    동률은 평균 rank.
    공식: ((N - rank) / N) * 99 → 최고가 99, 최저가 0
    """
    valid_mask = returns.notna()
    valid = returns[valid_mask]
    n = len(valid)
    if n == 0:
        return pd.Series([np.nan] * len(returns), index=returns.index)
    
    # rank descending (1등이 가장 높은 수익률)
    ranks = valid.rank(ascending=False, method="average")
    # 백분위
    percentiles = ((n - ranks) / n) * 99
    # 0~99 정수로
    rs_rating = percentiles.round().astype(int)
    
    # 원 index 로 복원, NaN 종목은 NaN
    result = pd.Series([np.nan] * len(returns), index=returns.index)
    result.loc[valid_mask] = rs_rating
    return result
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_rs_rating.py -v`
Expected: 5 passed

- [ ] **Step 5: 전체 회귀**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 93 passed

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/indicators/compute/rs_rating.py tests/test_indicators_rs_rating.py
git commit -m "feat(indicators): compute/rs_rating - 1년 수익률 universe 백분위"
```

---

## Task 6: compute/minervini.py — 8 조건 c1-c7 (TDD)

**Files:**
- Create: `kr_pipeline/indicators/compute/minervini.py`
- Create: `tests/test_indicators_minervini.py`

c8 (rs_rating ≥ 70) 와 minervini_pass 는 Phase C 의 단일 SQL UPDATE 에서 처리 (rs_rating 가 Phase B 에서 채워진 후). 본 모듈은 c1-c7 만 계산.

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_indicators_minervini.py
import pandas as pd
import numpy as np
import pytest
from kr_pipeline.indicators.compute.minervini import (
    compute_minervini_c1_to_c7,
)


def _input_df(close, sma50, sma150, sma200, w52h, w52l):
    """테스트 입력 DataFrame 생성."""
    return pd.DataFrame({
        "adj_close": close,
        "sma_50": sma50,
        "sma_150": sma150,
        "sma_200": sma200,
        "w52_high": w52h,
        "w52_low": w52l,
    })


def test_c1_close_above_sma150_above_sma200():
    """C1: adj_close > sma_150 > sma_200"""
    df = _input_df(
        close=[100.0], sma50=[90.0], sma150=[95.0], sma200=[90.0],
        w52h=[120.0], w52l=[60.0],
    )
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 100 > 95 > 90 → True
    assert result["minervini_c1"].iloc[0] == True


def test_c1_fails_when_close_below_sma150():
    """close < sma_150 → C1 = False"""
    df = _input_df(close=[80.0], sma50=[90.0], sma150=[95.0], sma200=[90.0], w52h=[120.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    assert result["minervini_c1"].iloc[0] == False


def test_c2_sma150_above_sma200():
    df = _input_df(close=[100.0], sma50=[90.0], sma150=[95.0], sma200=[90.0], w52h=[120.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    assert result["minervini_c2"].iloc[0] == True


def test_c3_sma200_rising_over_22_days():
    """C3: sma_200(today) > sma_200(today - 22 days)
    
    24 영업일 시계열로 검증 (window=22).
    """
    n = 30
    sma200_series = pd.Series([100.0 + i for i in range(n)])  # 우상향
    df = pd.DataFrame({
        "adj_close": [120.0] * n,
        "sma_50": [110.0] * n,
        "sma_150": [105.0] * n,
        "sma_200": sma200_series,
        "w52_high": [150.0] * n,
        "w52_low": [80.0] * n,
    })
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # index 22 부터: sma_200[22]=122, sma_200[0]=100 → 122 > 100 → True
    assert pd.isna(result["minervini_c3"].iloc[21])  # lookback 부족
    assert result["minervini_c3"].iloc[22] == True
    assert result["minervini_c3"].iloc[29] == True


def test_c3_sma200_declining():
    n = 30
    sma200_series = pd.Series([100.0 - i for i in range(n)])  # 우하향
    df = pd.DataFrame({
        "adj_close": [120.0] * n,
        "sma_50": [110.0] * n,
        "sma_150": [105.0] * n,
        "sma_200": sma200_series,
        "w52_high": [150.0] * n,
        "w52_low": [80.0] * n,
    })
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # sma_200[22]=78, sma_200[0]=100 → 78 < 100 → False
    assert result["minervini_c3"].iloc[22] == False


def test_c4_sma50_above_sma150_above_sma200():
    df = _input_df(close=[120.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    assert result["minervini_c4"].iloc[0] == True


def test_c5_close_above_sma50():
    df = _input_df(close=[120.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    assert result["minervini_c5"].iloc[0] == True


def test_c6_close_25pct_above_52w_low():
    """close >= w52_low * 1.25"""
    df = _input_df(close=[125.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[100.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 125 >= 100 * 1.25 (=125) → True
    assert result["minervini_c6"].iloc[0] == True


def test_c6_fails_when_too_close_to_52w_low():
    df = _input_df(close=[120.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[100.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 120 < 125 → False
    assert result["minervini_c6"].iloc[0] == False


def test_c7_close_within_25pct_of_52w_high():
    """close >= w52_high * 0.75"""
    df = _input_df(close=[120.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 120 >= 150 * 0.75 (=112.5) → True
    assert result["minervini_c7"].iloc[0] == True


def test_c7_fails_when_too_far_from_52w_high():
    df = _input_df(close=[100.0], sma50=[110.0], sma150=[100.0], sma200=[90.0], w52h=[150.0], w52l=[60.0])
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # 100 < 112.5 → False
    assert result["minervini_c7"].iloc[0] == False


def test_null_input_produces_null_condition():
    """SMA 가 NaN 이면 관련 조건도 NaN (NULL)"""
    df = _input_df(
        close=[100.0], sma50=[np.nan], sma150=[95.0], sma200=[90.0],
        w52h=[120.0], w52l=[60.0],
    )
    result = compute_minervini_c1_to_c7(df, sma_200_lookback=22)
    # c5 = close > sma_50; sma_50=NaN → c5 = NaN
    assert pd.isna(result["minervini_c5"].iloc[0])
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_minervini.py -v`
Expected: ImportError

- [ ] **Step 3: 구현**

```python
# kr_pipeline/indicators/compute/minervini.py
"""미너비니 Trend Template 조건 c1-c7 계산 (c8 = rs_rating >= 70, pass = ALL 은 SQL 에서).

모든 입력은 수정종가 기준 컬럼이어야 함.
"""
import numpy as np
import pandas as pd


def compute_minervini_c1_to_c7(df: pd.DataFrame, sma_200_lookback: int = 22) -> pd.DataFrame:
    """
    입력 df 컬럼: adj_close, sma_50, sma_150, sma_200, w52_high, w52_low
    출력: minervini_c1 ~ minervini_c7 boolean 컬럼 (NaN 가능)
    
    NaN 입력 시 조건도 NaN (pandas 비교 의미).
    """
    out = pd.DataFrame(index=df.index)
    
    close = df["adj_close"]
    sma50 = df["sma_50"]
    sma150 = df["sma_150"]
    sma200 = df["sma_200"]
    w52h = df["w52_high"]
    w52l = df["w52_low"]
    
    # C1: close > sma_150 > sma_200
    out["minervini_c1"] = (close > sma150) & (sma150 > sma200)
    # C2: sma_150 > sma_200
    out["minervini_c2"] = sma150 > sma200
    # C3: sma_200(today) > sma_200(today - 22)
    sma200_lagged = sma200.shift(sma_200_lookback)
    out["minervini_c3"] = sma200 > sma200_lagged
    # C4: sma_50 > sma_150 > sma_200
    out["minervini_c4"] = (sma50 > sma150) & (sma150 > sma200)
    # C5: close > sma_50
    out["minervini_c5"] = close > sma50
    # C6: close >= w52_low * 1.25
    out["minervini_c6"] = close >= w52l * 1.25
    # C7: close >= w52_high * 0.75
    out["minervini_c7"] = close >= w52h * 0.75
    
    # NaN 보존: 입력 중 하나라도 NaN 이면 조건도 NaN (pandas 비교 결과는 False 이지만, 우리는 NaN 으로)
    for c, cols in [
        ("minervini_c1", [close, sma150, sma200]),
        ("minervini_c2", [sma150, sma200]),
        ("minervini_c3", [sma200, sma200_lagged]),
        ("minervini_c4", [sma50, sma150, sma200]),
        ("minervini_c5", [close, sma50]),
        ("minervini_c6", [close, w52l]),
        ("minervini_c7", [close, w52h]),
    ]:
        # 어느 입력이라도 NaN 인 행은 조건도 NaN (object dtype 으로 변환)
        nan_mask = pd.concat([col.isna() for col in cols], axis=1).any(axis=1)
        out[c] = out[c].astype(object)
        out.loc[nan_mask, c] = np.nan
    
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_minervini.py -v`
Expected: 12 passed

- [ ] **Step 5: 전체 회귀**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 105 passed

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/indicators/compute/minervini.py tests/test_indicators_minervini.py
git commit -m "feat(indicators): compute/minervini - 8조건 c1-c7 (c8+pass는 SQL)"
```

---

## Task 7: load.py — DB SELECT 헬퍼

**Files:**
- Create: `kr_pipeline/indicators/load.py`

- [ ] **Step 1: 구현**

```python
# kr_pipeline/indicators/load.py
"""indicators 파이프라인 입력 SELECT 헬퍼."""
from datetime import date

import pandas as pd
from psycopg import Connection


def load_daily_prices(
    conn: Connection,
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """한 종목의 일봉 (date, adj_close)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, adj_close
              FROM daily_prices
             WHERE ticker = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (ticker, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["adj_close"] = df["adj_close"].astype(float)
    return df


def load_index_daily(
    conn: Connection,
    index_code: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """지수 일봉 (date, close)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, close
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
        df["close"] = df["close"].astype(float)
    return df


def load_weekly_prices(conn: Connection, ticker: str, start: date, end: date) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT week_end_date AS date, adj_close
              FROM weekly_prices
             WHERE ticker = %s AND week_end_date BETWEEN %s AND %s
             ORDER BY week_end_date
            """,
            (ticker, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["adj_close"] = df["adj_close"].astype(float)
    return df


def load_weekly_index(conn: Connection, index_code: str, start: date, end: date) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT week_end_date AS date, close
              FROM weekly_index
             WHERE index_code = %s AND week_end_date BETWEEN %s AND %s
             ORDER BY week_end_date
            """,
            (index_code, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["close"] = df["close"].astype(float)
    return df


def load_active_tickers_with_market(conn: Connection, limit: int | None = None) -> list[tuple[str, str]]:
    """[(ticker, market), ...] — RS Line 벤치마크 결정용."""
    with conn.cursor() as cur:
        sql = "SELECT ticker, market FROM stocks WHERE delisted_at IS NULL ORDER BY ticker"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return [(r[0], r[1]) for r in cur.fetchall()]


def get_daily_prices_min_date(conn: Connection) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(date) FROM daily_prices")
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def get_weekly_prices_min_date(conn: Connection) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(week_end_date) FROM weekly_prices")
        row = cur.fetchone()
        return row[0] if row and row[0] else None
```

- [ ] **Step 2: 임포트 확인**

```bash
uv run python -c "from kr_pipeline.indicators.load import load_daily_prices, load_index_daily, load_weekly_prices, load_weekly_index, load_active_tickers_with_market, get_daily_prices_min_date, get_weekly_prices_min_date; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: 전체 테스트 회귀**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 105 passed

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/indicators/load.py
git commit -m "feat(indicators): load - DB SELECT 헬퍼"
```

---

## Task 8: store.py — UPSERT (TDD)

**Files:**
- Create: `kr_pipeline/indicators/store.py`
- Create: `tests/test_indicators_store.py`

Phase A 가 채우는 컬럼 (adj_close, SMA, 52w, RS Line, c1-c7) 만 UPSERT. rs_rating, c8, pass 는 Phase B/C 에서 별도 UPDATE.

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_indicators_store.py
from datetime import date

from kr_pipeline.indicators.store import (
    upsert_daily_indicators_phase_a,
    update_daily_indicators_rs_rating,
    update_daily_indicators_minervini_pass,
)


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_phase_a_inserts_new_row(db):
    _seed_stock(db)
    rows = [{
        "ticker": "005930",
        "date": date(2026, 5, 15),
        "adj_close": 70000.0,
        "sma_10": 69000.0, "sma_21": 68000.0, "sma_50": 65000.0,
        "sma_150": 60000.0, "sma_200": 55000.0,
        "w52_high": 80000.0, "w52_low": 50000.0,
        "pct_from_52w_high": -12.5, "pct_from_52w_low": 40.0,
        "rs_line": 0.0040, "rs_line_52w_high": 0.0050, "rs_line_52w_high_date": date(2026, 1, 15),
        "rs_line_at_52w_high": False,
        "rs_line_uptrend_6w": True, "rs_line_uptrend_13w": True,
        "rs_line_in_decline_7m": False,
        "minervini_c1": True, "minervini_c2": True, "minervini_c3": True,
        "minervini_c4": True, "minervini_c5": True, "minervini_c6": True,
        "minervini_c7": True,
    }]
    affected = upsert_daily_indicators_phase_a(db, rows)
    assert affected == 1
    
    with db.cursor() as cur:
        cur.execute("SELECT adj_close, sma_50, minervini_c1, rs_rating FROM daily_indicators WHERE ticker='005930' AND date='2026-05-15'")
        row = cur.fetchone()
    assert row[0] == 70000.0
    assert row[1] == 65000.0
    assert row[2] == True
    assert row[3] is None   # rs_rating 은 Phase B 에서


def test_upsert_phase_a_updates_on_conflict(db):
    _seed_stock(db)
    rows_v1 = [{
        "ticker": "005930", "date": date(2026, 5, 15), "adj_close": 70000.0,
        "sma_10": None, "sma_21": None, "sma_50": None, "sma_150": None, "sma_200": None,
        "w52_high": None, "w52_low": None, "pct_from_52w_high": None, "pct_from_52w_low": None,
        "rs_line": None, "rs_line_52w_high": None, "rs_line_52w_high_date": None,
        "rs_line_at_52w_high": None, "rs_line_uptrend_6w": None, "rs_line_uptrend_13w": None,
        "rs_line_in_decline_7m": None,
        "minervini_c1": None, "minervini_c2": None, "minervini_c3": None,
        "minervini_c4": None, "minervini_c5": None, "minervini_c6": None, "minervini_c7": None,
    }]
    upsert_daily_indicators_phase_a(db, rows_v1)
    
    rows_v2 = [dict(rows_v1[0], adj_close=71000.0, sma_50=65000.0)]
    upsert_daily_indicators_phase_a(db, rows_v2)
    
    with db.cursor() as cur:
        cur.execute("SELECT adj_close, sma_50 FROM daily_indicators WHERE ticker='005930'")
        assert cur.fetchone() == (71000.0, 65000.0)


def test_update_rs_rating_sets_value(db):
    _seed_stock(db)
    rows = [dict(
        ticker="005930", date=date(2026, 5, 15), adj_close=70000.0,
        sma_10=None, sma_21=None, sma_50=None, sma_150=None, sma_200=None,
        w52_high=None, w52_low=None, pct_from_52w_high=None, pct_from_52w_low=None,
        rs_line=None, rs_line_52w_high=None, rs_line_52w_high_date=None,
        rs_line_at_52w_high=None, rs_line_uptrend_6w=None, rs_line_uptrend_13w=None,
        rs_line_in_decline_7m=None,
        minervini_c1=None, minervini_c2=None, minervini_c3=None,
        minervini_c4=None, minervini_c5=None, minervini_c6=None, minervini_c7=None,
    )]
    upsert_daily_indicators_phase_a(db, rows)
    
    affected = update_daily_indicators_rs_rating(db, [("005930", date(2026, 5, 15), 85)])
    assert affected == 1
    
    with db.cursor() as cur:
        cur.execute("SELECT rs_rating FROM daily_indicators WHERE ticker='005930'")
        assert cur.fetchone() == (85,)


def test_update_minervini_pass_uses_sql(db):
    """SQL UPDATE 가 minervini_c8 와 pass 를 계산하는지."""
    _seed_stock(db)
    # 모든 c1-c7 True, rs_rating 85 시드
    rows = [dict(
        ticker="005930", date=date(2026, 5, 15), adj_close=70000.0,
        sma_10=None, sma_21=None, sma_50=65000.0, sma_150=60000.0, sma_200=55000.0,
        w52_high=80000.0, w52_low=50000.0, pct_from_52w_high=-12.5, pct_from_52w_low=40.0,
        rs_line=None, rs_line_52w_high=None, rs_line_52w_high_date=None,
        rs_line_at_52w_high=None, rs_line_uptrend_6w=None, rs_line_uptrend_13w=None,
        rs_line_in_decline_7m=None,
        minervini_c1=True, minervini_c2=True, minervini_c3=True,
        minervini_c4=True, minervini_c5=True, minervini_c6=True, minervini_c7=True,
    )]
    upsert_daily_indicators_phase_a(db, rows)
    update_daily_indicators_rs_rating(db, [("005930", date(2026, 5, 15), 85)])
    
    affected = update_daily_indicators_minervini_pass(db, date(2026, 5, 15), date(2026, 5, 15))
    assert affected == 1
    
    with db.cursor() as cur:
        cur.execute("SELECT minervini_c8, minervini_pass FROM daily_indicators WHERE ticker='005930'")
        c8, pass_ = cur.fetchone()
    assert c8 == True       # rs_rating 85 >= 70
    assert pass_ == True    # 8 모두 True


def test_minervini_pass_false_when_any_condition_false(db):
    """c1-c7 중 하나라도 False 면 pass=False"""
    _seed_stock(db)
    rows = [dict(
        ticker="005930", date=date(2026, 5, 15), adj_close=70000.0,
        sma_10=None, sma_21=None, sma_50=None, sma_150=None, sma_200=None,
        w52_high=None, w52_low=None, pct_from_52w_high=None, pct_from_52w_low=None,
        rs_line=None, rs_line_52w_high=None, rs_line_52w_high_date=None,
        rs_line_at_52w_high=None, rs_line_uptrend_6w=None, rs_line_uptrend_13w=None,
        rs_line_in_decline_7m=None,
        minervini_c1=False, minervini_c2=True, minervini_c3=True,
        minervini_c4=True, minervini_c5=True, minervini_c6=True, minervini_c7=True,
    )]
    upsert_daily_indicators_phase_a(db, rows)
    update_daily_indicators_rs_rating(db, [("005930", date(2026, 5, 15), 85)])
    update_daily_indicators_minervini_pass(db, date(2026, 5, 15), date(2026, 5, 15))
    
    with db.cursor() as cur:
        cur.execute("SELECT minervini_pass FROM daily_indicators WHERE ticker='005930'")
        assert cur.fetchone() == (False,)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_store.py -v`
Expected: ImportError

- [ ] **Step 3: 구현**

```python
# kr_pipeline/indicators/store.py
"""daily_indicators / weekly_indicators UPSERT + Phase 단위 UPDATE."""
from datetime import date
from psycopg import Connection


PHASE_A_COLUMNS_DAILY = [
    "ticker", "date", "adj_close",
    "sma_10", "sma_21", "sma_50", "sma_150", "sma_200",
    "w52_high", "w52_low", "pct_from_52w_high", "pct_from_52w_low",
    "rs_line", "rs_line_52w_high", "rs_line_52w_high_date",
    "rs_line_at_52w_high", "rs_line_uptrend_6w", "rs_line_uptrend_13w",
    "rs_line_in_decline_7m",
    "minervini_c1", "minervini_c2", "minervini_c3",
    "minervini_c4", "minervini_c5", "minervini_c6", "minervini_c7",
]


def upsert_daily_indicators_phase_a(conn: Connection, rows: list[dict]) -> int:
    """Phase A 결과 UPSERT. rs_rating, c8, pass 는 건드리지 않음."""
    if not rows:
        return 0
    
    cols = PHASE_A_COLUMNS_DAILY
    placeholders = ", ".join(["%s"] * len(cols))
    cols_sql = ", ".join(cols)
    update_sql = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ("ticker", "date")])
    
    sql = f"""
        INSERT INTO daily_indicators ({cols_sql}, updated_at)
        VALUES ({placeholders}, NOW())
        ON CONFLICT (ticker, date) DO UPDATE
           SET {update_sql}, updated_at = NOW()
    """
    
    tuples = [tuple(r.get(c) for c in cols) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, tuples)
        return cur.rowcount


def update_daily_indicators_rs_rating(conn: Connection, rows: list[tuple]) -> int:
    """rs_rating 만 UPDATE.
    
    rows: [(ticker, date, rs_rating_int_or_None), ...]
    """
    if not rows:
        return 0
    
    with conn.cursor() as cur:
        # TEMP TABLE + JOIN UPDATE (Fix #3 패턴, 빠름)
        cur.execute("""
            CREATE TEMP TABLE _rs_updates (
                ticker VARCHAR(10),
                date DATE,
                rs_rating SMALLINT,
                PRIMARY KEY (ticker, date)
            ) ON COMMIT DROP
        """)
        cur.executemany(
            "INSERT INTO _rs_updates (ticker, date, rs_rating) VALUES (%s, %s, %s)",
            rows,
        )
        cur.execute("""
            UPDATE daily_indicators d
               SET rs_rating = u.rs_rating, updated_at = NOW()
              FROM _rs_updates u
             WHERE d.ticker = u.ticker AND d.date = u.date
        """)
        return cur.rowcount


def update_daily_indicators_minervini_pass(
    conn: Connection,
    start_date: date,
    end_date: date,
) -> int:
    """단일 SQL UPDATE 로 c8 (rs_rating >= 70) 와 minervini_pass (c1..c8 ALL TRUE) 계산."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daily_indicators
               SET minervini_c8 = (rs_rating >= 70),
                   minervini_pass = (
                       minervini_c1 IS TRUE AND minervini_c2 IS TRUE AND
                       minervini_c3 IS TRUE AND minervini_c4 IS TRUE AND
                       minervini_c5 IS TRUE AND minervini_c6 IS TRUE AND
                       minervini_c7 IS TRUE AND (rs_rating >= 70)
                   ),
                   updated_at = NOW()
             WHERE date BETWEEN %s AND %s
            """,
            (start_date, end_date),
        )
        return cur.rowcount


# Weekly 동일 패턴
PHASE_A_COLUMNS_WEEKLY = [
    "ticker", "week_end_date", "adj_close",
    "sma_10w", "sma_30w", "sma_40w",
    "w52_high", "w52_low", "pct_from_52w_high", "pct_from_52w_low",
    "rs_line", "rs_line_52w_high", "rs_line_52w_high_date",
    "rs_line_at_52w_high", "rs_line_uptrend_6w", "rs_line_uptrend_13w",
    "rs_line_in_decline_7m",
    "minervini_c1", "minervini_c2", "minervini_c3",
    "minervini_c4", "minervini_c5", "minervini_c6", "minervini_c7",
]


def upsert_weekly_indicators_phase_a(conn: Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = PHASE_A_COLUMNS_WEEKLY
    placeholders = ", ".join(["%s"] * len(cols))
    cols_sql = ", ".join(cols)
    update_sql = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ("ticker", "week_end_date")])
    sql = f"""
        INSERT INTO weekly_indicators ({cols_sql}, updated_at)
        VALUES ({placeholders}, NOW())
        ON CONFLICT (ticker, week_end_date) DO UPDATE
           SET {update_sql}, updated_at = NOW()
    """
    tuples = [tuple(r.get(c) for c in cols) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, tuples)
        return cur.rowcount


def update_weekly_indicators_rs_rating(conn: Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE _rs_updates_w (
                ticker VARCHAR(10),
                week_end_date DATE,
                rs_rating SMALLINT,
                PRIMARY KEY (ticker, week_end_date)
            ) ON COMMIT DROP
        """)
        cur.executemany(
            "INSERT INTO _rs_updates_w (ticker, week_end_date, rs_rating) VALUES (%s, %s, %s)",
            rows,
        )
        cur.execute("""
            UPDATE weekly_indicators w
               SET rs_rating = u.rs_rating, updated_at = NOW()
              FROM _rs_updates_w u
             WHERE w.ticker = u.ticker AND w.week_end_date = u.week_end_date
        """)
        return cur.rowcount


def update_weekly_indicators_minervini_pass(
    conn: Connection,
    start_date: date,
    end_date: date,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE weekly_indicators
               SET minervini_c8 = (rs_rating >= 70),
                   minervini_pass = (
                       minervini_c1 IS TRUE AND minervini_c2 IS TRUE AND
                       minervini_c3 IS TRUE AND minervini_c4 IS TRUE AND
                       minervini_c5 IS TRUE AND minervini_c6 IS TRUE AND
                       minervini_c7 IS TRUE AND (rs_rating >= 70)
                   ),
                   updated_at = NOW()
             WHERE week_end_date BETWEEN %s AND %s
            """,
            (start_date, end_date),
        )
        return cur.rowcount
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_store.py -v`
Expected: 5 passed

- [ ] **Step 5: 전체 회귀**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 110 passed

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/indicators/store.py tests/test_indicators_store.py
git commit -m "feat(indicators): store - Phase A UPSERT + B/C UPDATE"
```

---

## Task 9: modes.py — 오케스트레이션 (TDD)

**Files:**
- Create: `kr_pipeline/indicators/modes.py`
- Create: `tests/test_indicators_modes.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_indicators_modes.py
from datetime import date
from freezegun import freeze_time

from kr_pipeline.indicators.modes import Mode, Target, compute_date_range, LOOKBACK_DAYS, LOOKBACK_WEEKS


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.FULL_REFRESH.value == "full-refresh"


def test_target_enum_values():
    assert Target.DAILY.value == "daily"
    assert Target.WEEKLY.value == "weekly"


@freeze_time("2026-05-18")
def test_daily_incremental_window_30():
    """daily incremental: end=today, start=today - 30 - 252 lookback"""
    start, end, ups_start = compute_date_range(Target.DAILY, Mode.INCREMENTAL, window=30)
    today = date(2026, 5, 18)
    assert end == today
    assert start == today - __import__("datetime").timedelta(days=30 + LOOKBACK_DAYS)
    assert ups_start == today - __import__("datetime").timedelta(days=30)


@freeze_time("2026-05-18")
def test_weekly_incremental_window_4():
    """weekly incremental: lookback 52 주"""
    start, end, ups_start = compute_date_range(Target.WEEKLY, Mode.INCREMENTAL, window=4)
    today = date(2026, 5, 18)
    assert end == today
    assert start == today - __import__("datetime").timedelta(days=(4 + LOOKBACK_WEEKS) * 7)
    assert ups_start == today - __import__("datetime").timedelta(days=4 * 7)


def test_backfill_uses_db_min(monkeypatch):
    """backfill: db 의 min date 부터, upsert 시작 = start"""
    from kr_pipeline.indicators import modes
    monkeypatch.setattr(modes, "_get_db_min_date", lambda conn, t: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        start, end, ups_start = compute_date_range(Target.DAILY, Mode.BACKFILL, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 18)
    assert ups_start == date(2024, 1, 2)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_modes.py -v`
Expected: ImportError

- [ ] **Step 3: 구현**

```python
# kr_pipeline/indicators/modes.py
"""indicators 파이프라인 모드 분기 + 오케스트레이션."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
import logging

import numpy as np
import pandas as pd
from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.indicators.compute.sma import sma
from kr_pipeline.indicators.compute.high_low import w52_high_low, pct_from_high_low
from kr_pipeline.indicators.compute.rs_line import (
    compute_rs_line, compute_rs_line_52w_high_and_date,
    compute_rs_line_at_52w_high, compute_rs_line_uptrend,
    compute_rs_line_in_decline_7m,
)
from kr_pipeline.indicators.compute.rs_rating import compute_1y_return, assign_rs_rating_percentiles
from kr_pipeline.indicators.compute.minervini import compute_minervini_c1_to_c7
from kr_pipeline.indicators.load import (
    load_daily_prices, load_index_daily, load_weekly_prices, load_weekly_index,
    load_active_tickers_with_market,
    get_daily_prices_min_date, get_weekly_prices_min_date,
)
from kr_pipeline.indicators.store import (
    upsert_daily_indicators_phase_a, update_daily_indicators_rs_rating,
    update_daily_indicators_minervini_pass,
    upsert_weekly_indicators_phase_a, update_weekly_indicators_rs_rating,
    update_weekly_indicators_minervini_pass,
)


log = logging.getLogger("kr_pipeline.indicators")

LOOKBACK_DAYS = 252       # 52w high/low + 1y return
LOOKBACK_WEEKS = 52


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full-refresh"


class Target(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)


def _get_db_min_date(conn: Connection, target: Target) -> date:
    if target == Target.DAILY:
        d = get_daily_prices_min_date(conn)
    else:
        d = get_weekly_prices_min_date(conn)
    return d if d else date.today()


def compute_date_range(
    target: Target,
    mode: Mode,
    *,
    window: int = 30,
    conn: Connection | None = None,
) -> tuple[date, date, date]:
    """(load_start, load_end, upsert_start) 반환.
    
    load 는 lookback 포함, upsert 는 window 부분만.
    """
    today = date.today()
    
    if mode == Mode.INCREMENTAL:
        if target == Target.DAILY:
            load_start = today - timedelta(days=window + LOOKBACK_DAYS)
            upsert_start = today - timedelta(days=window)
        else:
            load_start = today - timedelta(days=(window + LOOKBACK_WEEKS) * 7)
            upsert_start = today - timedelta(days=window * 7)
        return load_start, today, upsert_start
    
    if mode in (Mode.BACKFILL, Mode.FULL_REFRESH):
        assert conn is not None
        load_start = _get_db_min_date(conn, target)
        return load_start, today, load_start
    
    raise ValueError(f"Unknown mode: {mode}")


def _market_to_index_code(market: str) -> str:
    """KOSPI → '1001', KOSDAQ → '2001'."""
    return "1001" if market == "KOSPI" else "2001"


def _process_ticker_daily(
    conn: Connection,
    ticker: str,
    market: str,
    load_start: date,
    load_end: date,
    upsert_start: date,
) -> int:
    """한 종목의 일봉 지표 Phase A 처리."""
    df_daily = load_daily_prices(conn, ticker, load_start, load_end)
    if df_daily.empty:
        return 0
    
    index_code = _market_to_index_code(market)
    df_idx = load_index_daily(conn, index_code, load_start, load_end)
    if df_idx.empty:
        return 0
    
    # join on date
    df = df_daily.merge(df_idx.rename(columns={"close": "index_close"}), on="date", how="left")
    df = df.set_index("date").sort_index()
    
    adj_close = df["adj_close"]
    
    # SMAs
    sma_10 = sma(adj_close, 10)
    sma_21 = sma(adj_close, 21)
    sma_50 = sma(adj_close, 50)
    sma_150 = sma(adj_close, 150)
    sma_200 = sma(adj_close, 200)
    
    # 52w
    w52h, w52l = w52_high_low(adj_close, window=252)
    pct_h, pct_l = pct_from_high_low(adj_close, w52h, w52l)
    
    # RS Line
    rs_line = compute_rs_line(adj_close, df["index_close"])
    rs_line_high, rs_line_high_date = compute_rs_line_52w_high_and_date(rs_line, window=252)
    rs_at_high = compute_rs_line_at_52w_high(rs_line, rs_line_high)
    rs_up_6w = compute_rs_line_uptrend(rs_line, window=30)   # 6주 ≈ 30영업일
    rs_up_13w = compute_rs_line_uptrend(rs_line, window=65)  # 13주 ≈ 65영업일
    current_dates = pd.Series(df.index, index=df.index)
    rs_decline = compute_rs_line_in_decline_7m(rs_line_high_date, current_dates, threshold_days=140)
    
    # 1y return (rs_rating 입력)
    one_y_ret = compute_1y_return(adj_close, window=252)
    
    # Minervini c1-c7
    mn_df = pd.DataFrame({
        "adj_close": adj_close,
        "sma_50": sma_50, "sma_150": sma_150, "sma_200": sma_200,
        "w52_high": w52h, "w52_low": w52l,
    }, index=df.index)
    mn = compute_minervini_c1_to_c7(mn_df, sma_200_lookback=22)
    
    # Build row dicts, filter to upsert_start..load_end
    rows = []
    one_y_returns_for_phase_b = {}  # date -> 1y_return
    for d in df.index:
        if d < upsert_start:
            continue
        row = {
            "ticker": ticker,
            "date": d,
            "adj_close": float(adj_close.loc[d]),
            "sma_10": _as_float(sma_10.loc[d]),
            "sma_21": _as_float(sma_21.loc[d]),
            "sma_50": _as_float(sma_50.loc[d]),
            "sma_150": _as_float(sma_150.loc[d]),
            "sma_200": _as_float(sma_200.loc[d]),
            "w52_high": _as_float(w52h.loc[d]),
            "w52_low": _as_float(w52l.loc[d]),
            "pct_from_52w_high": _as_float(pct_h.loc[d]),
            "pct_from_52w_low": _as_float(pct_l.loc[d]),
            "rs_line": _as_float(rs_line.loc[d]),
            "rs_line_52w_high": _as_float(rs_line_high.loc[d]),
            "rs_line_52w_high_date": rs_line_high_date.loc[d] if pd.notna(rs_line_high_date.loc[d]) else None,
            "rs_line_at_52w_high": _as_bool(rs_at_high.loc[d]),
            "rs_line_uptrend_6w": _as_bool(rs_up_6w.loc[d]),
            "rs_line_uptrend_13w": _as_bool(rs_up_13w.loc[d]),
            "rs_line_in_decline_7m": _as_bool(rs_decline.loc[d]),
            "minervini_c1": _as_bool(mn["minervini_c1"].loc[d]),
            "minervini_c2": _as_bool(mn["minervini_c2"].loc[d]),
            "minervini_c3": _as_bool(mn["minervini_c3"].loc[d]),
            "minervini_c4": _as_bool(mn["minervini_c4"].loc[d]),
            "minervini_c5": _as_bool(mn["minervini_c5"].loc[d]),
            "minervini_c6": _as_bool(mn["minervini_c6"].loc[d]),
            "minervini_c7": _as_bool(mn["minervini_c7"].loc[d]),
        }
        rows.append(row)
        one_y_returns_for_phase_b[d] = _as_float(one_y_ret.loc[d])
    
    if not rows:
        return 0
    affected = upsert_daily_indicators_phase_a(conn, rows)
    conn.commit()
    # store 1y returns 임시 cache (Phase B 입력)
    _phase_b_cache.setdefault(ticker, {}).update(one_y_returns_for_phase_b)
    return affected


# 임시 module-level cache for Phase B input (Phase A 가 채워둠)
_phase_b_cache: dict[str, dict[date, float | None]] = {}


def _as_float(v) -> float | None:
    if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
        return None
    return float(v)


def _as_bool(v) -> bool | None:
    if v is None or pd.isna(v):
        return None
    return bool(v)


def _run_phase_b_daily(conn: Connection, upsert_start: date, upsert_end: date) -> int:
    """날짜별 RS Rating 계산 → UPDATE."""
    # 모든 ticker 의 1y_return을 date 별로 모음
    by_date: dict[date, dict[str, float | None]] = {}
    for ticker, date_to_ret in _phase_b_cache.items():
        for d, r in date_to_ret.items():
            if d < upsert_start or d > upsert_end:
                continue
            by_date.setdefault(d, {})[ticker] = r
    
    update_rows = []
    for d, ticker_to_ret in by_date.items():
        returns = pd.Series(ticker_to_ret, dtype=float)
        rs = assign_rs_rating_percentiles(returns)
        for ticker, rating in rs.items():
            if pd.isna(rating):
                update_rows.append((ticker, d, None))
            else:
                update_rows.append((ticker, d, int(rating)))
    
    affected = update_daily_indicators_rs_rating(conn, update_rows)
    conn.commit()
    return affected


def _run_sanity_checks_daily(conn: Connection, upsert_end: date) -> list[str]:
    """sanity 검증 (spec §7)."""
    warnings = []
    with conn.cursor() as cur:
        # 1. 커버리지
        cur.execute("SELECT COUNT(*) FROM daily_indicators WHERE date = %s", (upsert_end,))
        ind_count = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM daily_prices WHERE date = %s", (upsert_end,))
        prc_count = cur.fetchone()[0] or 0
        if prc_count > 0:
            ratio = ind_count / prc_count
            if ratio < 0.95:
                warnings.append(f"coverage_low: 지표 행 {ind_count}/{prc_count} ({ratio*100:.1f}%, 임계 95%)")
        
        # 2. SMA NULL 비율
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE sma_200 IS NULL), COUNT(*) 
              FROM daily_indicators WHERE date = %s
        """, (upsert_end,))
        null_count, total = cur.fetchone()
        if total > 0:
            null_ratio = (null_count or 0) / total
            if null_ratio > 0.30:
                warnings.append(f"sma_200_null_ratio_high: {null_ratio*100:.1f}% (임계 30%)")
        
        # 3. RS Rating 분포
        cur.execute("""
            SELECT MAX(rs_rating), MIN(rs_rating), COUNT(rs_rating) 
              FROM daily_indicators WHERE date = %s
        """, (upsert_end,))
        mx, mn, cnt = cur.fetchone()
        if cnt and cnt > 1000:
            if mx != 99 or mn != 0:
                warnings.append(f"rs_rating_distribution_odd: max={mx}, min={mn}, count={cnt}")
        
        # 4. 미너비니 통과율
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE minervini_pass = TRUE), COUNT(*) 
              FROM daily_indicators WHERE date = %s AND minervini_pass IS NOT NULL
        """, (upsert_end,))
        pass_cnt, eval_cnt = cur.fetchone()
        if eval_cnt and eval_cnt > 0:
            ratio = (pass_cnt or 0) / eval_cnt
            if ratio == 0 or ratio > 0.50:
                warnings.append(f"minervini_pass_rate_odd: {ratio*100:.1f}% (정상 1-15%)")
    return warnings


def run_daily(
    conn: Connection,
    mode: Mode,
    *,
    window: int = 30,
    limit_tickers: int | None = None,
) -> RunStats:
    """일봉 지표 파이프라인 실행."""
    global _phase_b_cache
    _phase_b_cache = {}  # reset
    
    load_start, load_end, upsert_start = compute_date_range(
        Target.DAILY, mode, window=window, conn=conn,
    )
    log.info(f"daily indicators mode={mode.value} load={load_start}..{load_end} upsert={upsert_start}..{load_end}")
    
    tickers = load_active_tickers_with_market(conn, limit=limit_tickers)
    log.info(f"daily indicators tickers: {len(tickers)}")
    
    rows_total = 0
    failures: list[tuple[str, str]] = []
    
    with run_tracking(
        conn,
        pipeline="indicators",
        mode=f"daily-{mode.value}",
        params={"window": window, "limit_tickers": limit_tickers,
                "load_start": str(load_start), "load_end": str(load_end), 
                "upsert_start": str(upsert_start)},
    ) as state:
        # Phase A
        log.info("Phase A: per-ticker time-series indicators")
        for i, (ticker, market) in enumerate(tickers, 1):
            try:
                rows_total += _process_ticker_daily(conn, ticker, market, load_start, load_end, upsert_start)
            except Exception as e:
                failures.append((ticker, str(e)))
                conn.rollback()
            if i % 100 == 0:
                log.info(f"Phase A progress: {i}/{len(tickers)} (failures: {len(failures)})")
        
        # End-of-run retry for Phase A
        if failures:
            log.warning(f"Phase A retrying {len(failures)} failed tickers")
            retry_failures = []
            ticker_to_market = {t: m for t, m in tickers}
            for ticker, _ in failures:
                try:
                    rows_total += _process_ticker_daily(conn, ticker, ticker_to_market[ticker], load_start, load_end, upsert_start)
                except Exception as e:
                    retry_failures.append((ticker, str(e)))
                    conn.rollback()
            failures = retry_failures
        
        # Phase B
        log.info("Phase B: per-date RS Rating")
        rs_affected = _run_phase_b_daily(conn, upsert_start, load_end)
        log.info(f"Phase B: {rs_affected} rs_rating cells updated")
        
        # Phase C
        log.info("Phase C: minervini c8 + pass (SQL UPDATE)")
        mn_affected = update_daily_indicators_minervini_pass(conn, upsert_start, load_end)
        conn.commit()
        log.info(f"Phase C: {mn_affected} rows updated")
        
        # Sanity
        warnings = _run_sanity_checks_daily(conn, load_end)
        state["warnings"].extend(warnings)
        state["rows_affected"] = rows_total
    
    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)


# Weekly 동일 패턴 (compute 호출 시 window 가 주봉 기준)
def _process_ticker_weekly(
    conn: Connection,
    ticker: str,
    market: str,
    load_start: date,
    load_end: date,
    upsert_start: date,
) -> int:
    df_weekly = load_weekly_prices(conn, ticker, load_start, load_end)
    if df_weekly.empty:
        return 0
    index_code = _market_to_index_code(market)
    df_idx = load_weekly_index(conn, index_code, load_start, load_end)
    if df_idx.empty:
        return 0
    
    df = df_weekly.merge(df_idx.rename(columns={"close": "index_close"}), on="date", how="left")
    df = df.set_index("date").sort_index()
    adj_close = df["adj_close"]
    
    sma_10w_s = sma(adj_close, 10)
    sma_30w_s = sma(adj_close, 30)
    sma_40w_s = sma(adj_close, 40)
    w52h, w52l = w52_high_low(adj_close, window=52)
    pct_h, pct_l = pct_from_high_low(adj_close, w52h, w52l)
    rs_line = compute_rs_line(adj_close, df["index_close"])
    rs_line_high, rs_line_high_date = compute_rs_line_52w_high_and_date(rs_line, window=52)
    rs_at_high = compute_rs_line_at_52w_high(rs_line, rs_line_high)
    rs_up_6w = compute_rs_line_uptrend(rs_line, window=6)
    rs_up_13w = compute_rs_line_uptrend(rs_line, window=13)
    current_dates = pd.Series(df.index, index=df.index)
    rs_decline = compute_rs_line_in_decline_7m(rs_line_high_date, current_dates, threshold_days=28*7)
    one_y_ret = compute_1y_return(adj_close, window=52)
    
    mn_df = pd.DataFrame({
        "adj_close": adj_close,
        "sma_50": sma_10w_s, "sma_150": sma_30w_s, "sma_200": sma_40w_s,
        "w52_high": w52h, "w52_low": w52l,
    }, index=df.index)
    mn = compute_minervini_c1_to_c7(mn_df, sma_200_lookback=5)  # 5주 ≈ 1개월 (책 정합)
    
    rows = []
    one_y_returns_for_phase_b = {}
    for d in df.index:
        if d < upsert_start:
            continue
        row = {
            "ticker": ticker, "week_end_date": d, "adj_close": float(adj_close.loc[d]),
            "sma_10w": _as_float(sma_10w_s.loc[d]),
            "sma_30w": _as_float(sma_30w_s.loc[d]),
            "sma_40w": _as_float(sma_40w_s.loc[d]),
            "w52_high": _as_float(w52h.loc[d]),
            "w52_low": _as_float(w52l.loc[d]),
            "pct_from_52w_high": _as_float(pct_h.loc[d]),
            "pct_from_52w_low": _as_float(pct_l.loc[d]),
            "rs_line": _as_float(rs_line.loc[d]),
            "rs_line_52w_high": _as_float(rs_line_high.loc[d]),
            "rs_line_52w_high_date": rs_line_high_date.loc[d] if pd.notna(rs_line_high_date.loc[d]) else None,
            "rs_line_at_52w_high": _as_bool(rs_at_high.loc[d]),
            "rs_line_uptrend_6w": _as_bool(rs_up_6w.loc[d]),
            "rs_line_uptrend_13w": _as_bool(rs_up_13w.loc[d]),
            "rs_line_in_decline_7m": _as_bool(rs_decline.loc[d]),
            "minervini_c1": _as_bool(mn["minervini_c1"].loc[d]),
            "minervini_c2": _as_bool(mn["minervini_c2"].loc[d]),
            "minervini_c3": _as_bool(mn["minervini_c3"].loc[d]),
            "minervini_c4": _as_bool(mn["minervini_c4"].loc[d]),
            "minervini_c5": _as_bool(mn["minervini_c5"].loc[d]),
            "minervini_c6": _as_bool(mn["minervini_c6"].loc[d]),
            "minervini_c7": _as_bool(mn["minervini_c7"].loc[d]),
        }
        rows.append(row)
        one_y_returns_for_phase_b[d] = _as_float(one_y_ret.loc[d])
    
    if not rows:
        return 0
    affected = upsert_weekly_indicators_phase_a(conn, rows)
    conn.commit()
    _phase_b_cache.setdefault(ticker, {}).update(one_y_returns_for_phase_b)
    return affected


def _run_phase_b_weekly(conn: Connection, upsert_start: date, upsert_end: date) -> int:
    by_date: dict[date, dict[str, float | None]] = {}
    for ticker, date_to_ret in _phase_b_cache.items():
        for d, r in date_to_ret.items():
            if d < upsert_start or d > upsert_end:
                continue
            by_date.setdefault(d, {})[ticker] = r
    
    update_rows = []
    for d, ticker_to_ret in by_date.items():
        returns = pd.Series(ticker_to_ret, dtype=float)
        rs = assign_rs_rating_percentiles(returns)
        for ticker, rating in rs.items():
            update_rows.append((ticker, d, None if pd.isna(rating) else int(rating)))
    affected = update_weekly_indicators_rs_rating(conn, update_rows)
    conn.commit()
    return affected


def run_weekly(
    conn: Connection,
    mode: Mode,
    *,
    window: int = 4,
    limit_tickers: int | None = None,
) -> RunStats:
    global _phase_b_cache
    _phase_b_cache = {}
    
    load_start, load_end, upsert_start = compute_date_range(
        Target.WEEKLY, mode, window=window, conn=conn,
    )
    log.info(f"weekly indicators mode={mode.value} load={load_start}..{load_end} upsert={upsert_start}..{load_end}")
    
    tickers = load_active_tickers_with_market(conn, limit=limit_tickers)
    log.info(f"weekly indicators tickers: {len(tickers)}")
    
    rows_total = 0
    failures: list[tuple[str, str]] = []
    
    with run_tracking(
        conn,
        pipeline="indicators",
        mode=f"weekly-{mode.value}",
        params={"window": window, "limit_tickers": limit_tickers,
                "load_start": str(load_start), "load_end": str(load_end), 
                "upsert_start": str(upsert_start)},
    ) as state:
        for i, (ticker, market) in enumerate(tickers, 1):
            try:
                rows_total += _process_ticker_weekly(conn, ticker, market, load_start, load_end, upsert_start)
            except Exception as e:
                failures.append((ticker, str(e)))
                conn.rollback()
            if i % 100 == 0:
                log.info(f"Phase A progress: {i}/{len(tickers)} (failures: {len(failures)})")
        
        if failures:
            ticker_to_market = {t: m for t, m in tickers}
            retry_failures = []
            for ticker, _ in failures:
                try:
                    rows_total += _process_ticker_weekly(conn, ticker, ticker_to_market[ticker], load_start, load_end, upsert_start)
                except Exception as e:
                    retry_failures.append((ticker, str(e)))
                    conn.rollback()
            failures = retry_failures
        
        rs_affected = _run_phase_b_weekly(conn, upsert_start, load_end)
        log.info(f"Phase B weekly: {rs_affected} updated")
        
        mn_affected = update_weekly_indicators_minervini_pass(conn, upsert_start, load_end)
        conn.commit()
        log.info(f"Phase C weekly: {mn_affected} updated")
        
        state["rows_affected"] = rows_total
    
    return RunStats(rows_affected=rows_total, failures=failures)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_modes.py -v`
Expected: 5 passed

- [ ] **Step 5: 전체 회귀**

Run: `uv run pytest 2>&1 | tail -3`
Expected: 115 passed

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/indicators/modes.py tests/test_indicators_modes.py
git commit -m "feat(indicators): modes - 3 phase 오케스트레이션 (daily, weekly)"
```

---

## Task 10: __main__.py — argparse 진입점

**Files:**
- Create: `kr_pipeline/indicators/__main__.py`

- [ ] **Step 1: 구현**

```python
# kr_pipeline/indicators/__main__.py
"""indicators 파이프라인 진입점."""
import argparse
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.indicators.modes import Mode, Target, run_daily, run_weekly


log = logging.getLogger("kr_pipeline.indicators")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.indicators")
    p.add_argument("--target", required=True, choices=[t.value for t in Target])
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--window-days", type=int, default=30, help="일봉 incremental 윈도우")
    p.add_argument("--window-weeks", type=int, default=4, help="주봉 incremental 윈도우")
    p.add_argument("--limit-tickers", type=int, default=None, help="테스트용 종목 수 제한")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    
    target = Target(args.target)
    mode = Mode(args.mode)
    
    with connect(cfg.database_url) as conn:
        if target == Target.DAILY:
            stats = run_daily(conn, mode, window=args.window_days, limit_tickers=args.limit_tickers)
        else:
            stats = run_weekly(conn, mode, window=args.window_weeks, limit_tickers=args.limit_tickers)
        
        log.info(
            f"DONE indicators target={target.value} mode={mode.value} "
            f"rows_affected={stats.rows_affected} failures={len(stats.failures)} warnings={len(stats.warnings)}"
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

- [ ] **Step 2: 헬프 확인**

```bash
uv run python -m kr_pipeline.indicators --help
```
Expected: argparse usage with --target {daily,weekly}, --mode {backfill,incremental,full-refresh}.

- [ ] **Step 3: 테스트**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 115 passed.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/indicators/__main__.py
git commit -m "feat(indicators): 진입점 (argparse)"
```

---

## Task 11: 통합 테스트 + 라이브 스모크

**Files:**
- Create: `tests/test_indicators_integration.py`

- [ ] **Step 1: 통합 테스트 작성**

```python
# tests/test_indicators_integration.py
"""indicators end-to-end 통합 테스트. 실제 Postgres + #1/#1.5 입력 데이터."""
from datetime import date, timedelta

import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.indicators.modes import Mode, Target, run_daily


pytestmark = pytest.mark.integration


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM daily_indicators")
        cur.execute("DELETE FROM weekly_indicators")
        cur.execute("DELETE FROM daily_prices")
        cur.execute("DELETE FROM index_daily")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('INDTEST1', 'INDTEST2')")
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'indicators'")
    conn.commit()


def _seed_300_days_data(conn):
    """300 일치 일봉 + 지수 (lookback 252 일 통과용)."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('INDTEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('INDTEST2', 'T2', 'KOSPI') ON CONFLICT DO NOTHING")
        base = date(2025, 1, 2)
        for i in range(300):
            d = base + timedelta(days=i)
            if d.weekday() >= 5:  # 주말 skip
                continue
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('INDTEST1', %s, 100, 110, 90, 100, %s, 1000, 100000)""",
                (d, 100.0 + i * 0.1),   # 우상향
            )
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('INDTEST2', %s, 200, 220, 180, 200, %s, 2000, 400000)""",
                (d, 200.0 - i * 0.05),  # 약한 우하향
            )
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES ('1001', %s, 2500, 2520, 2480, %s, 1000, 1000000)""",
                (d, 2500.0 + i * 0.01),
            )
    conn.commit()


def test_daily_backfill_end_to_end(test_db_url):
    """일봉 시드 → backfill → 3 phase 완료, minervini_pass 계산 확인."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_300_days_data(conn)
        
        try:
            stats = run_daily(conn, Mode.BACKFILL, limit_tickers=2)
            
            assert stats.rows_affected > 0
            
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM daily_indicators WHERE ticker LIKE 'INDTEST%'")
                total_rows = cur.fetchone()[0]
                assert total_rows > 250  # 충분한 행
                
                # SMA(200) 마지막 행은 채워져 있어야
                cur.execute("""
                    SELECT sma_200 FROM daily_indicators 
                     WHERE ticker = 'INDTEST1' ORDER BY date DESC LIMIT 1
                """)
                last_sma = cur.fetchone()[0]
                assert last_sma is not None
                
                # rs_rating 마지막 날 둘 다 계산됨
                cur.execute("""
                    SELECT ticker, rs_rating FROM daily_indicators 
                     WHERE date = (SELECT MAX(date) FROM daily_indicators WHERE ticker LIKE 'INDTEST%')
                       AND ticker LIKE 'INDTEST%'
                """)
                rs_rows = cur.fetchall()
                rs_dict = {r[0]: r[1] for r in rs_rows}
                # INDTEST1 우상향 → rs_rating 더 높음
                assert rs_dict["INDTEST1"] >= rs_dict["INDTEST2"]
                
                # pipeline_runs 기록
                cur.execute("""
                    SELECT pipeline, mode, status, rows_affected FROM pipeline_runs 
                     WHERE pipeline = 'indicators' ORDER BY id DESC LIMIT 1
                """)
                row = cur.fetchone()
                assert row[0] == "indicators"
                assert row[2] == "success"
                assert row[3] == total_rows or row[3] > 0
        finally:
            _cleanup(conn)


def test_idempotent_backfill_twice(test_db_url):
    """같은 backfill 두 번 → 결과 동일 (멱등)."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_300_days_data(conn)
        
        try:
            run_daily(conn, Mode.BACKFILL, limit_tickers=2)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM daily_indicators WHERE ticker LIKE 'INDTEST%'")
                first_count = cur.fetchone()[0]
            
            run_daily(conn, Mode.BACKFILL, limit_tickers=2)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM daily_indicators WHERE ticker LIKE 'INDTEST%'")
                second_count = cur.fetchone()[0]
            
            assert first_count == second_count
        finally:
            _cleanup(conn)
```

- [ ] **Step 2: 통합 테스트 실행**

Run: `uv run pytest tests/test_indicators_integration.py -v -m integration 2>&1 | tail -10`
Expected: 2 passed

- [ ] **Step 3: 전체 회귀 (두 번 연속)**

```bash
uv run pytest 2>&1 | tail -3
uv run pytest 2>&1 | tail -3
```
Expected: 117 passed twice (idempotent).

- [ ] **Step 4: 라이브 일봉 backfill 스모크**

```bash
uv run python -m kr_pipeline.indicators --target=daily --mode=backfill --limit-tickers=10 2>&1 | tail -15
```

Expected: 
- 정상 종료
- DONE log line
- 가능성 있는 sanity warning (coverage_low: 10 종목만 처리됐고 active=2,550)

DB 검증:
```bash
psql postgresql://localhost/kr_pipeline -c "SELECT COUNT(*) FROM daily_indicators"
psql postgresql://localhost/kr_pipeline -c "SELECT COUNT(*) FROM daily_indicators WHERE sma_200 IS NOT NULL"
psql postgresql://localhost/kr_pipeline -c "SELECT * FROM daily_indicators ORDER BY date DESC LIMIT 3"
psql postgresql://localhost/kr_pipeline -c "SELECT pipeline, mode, status, rows_affected FROM pipeline_runs ORDER BY id DESC LIMIT 3"
```

Expected: daily_indicators 행 있음, sma_200 일부 채워져 있음 (충분한 daily_prices 가 있는 종목만).

- [ ] **Step 5: 라이브 주봉 backfill 스모크**

```bash
uv run python -m kr_pipeline.indicators --target=weekly --mode=backfill --limit-tickers=10 2>&1 | tail -15
```

- [ ] **Step 6: 커밋**

```bash
git add tests/test_indicators_integration.py
git commit -m "test(indicators): end-to-end 통합 테스트 (backfill, 멱등)"
```

---

## Task 12: Cron + README

**Files:**
- Modify: `scripts/cron.example` (append)
- Modify: `README.md` (append)

- [ ] **Step 1: `scripts/cron.example` 끝에 추가**

```cron

# 평일 19:00 — 일봉 지표 (일봉 적재 18:30 의 30분 후)
0 19 * * 1-5  cd $PROJECT_DIR && uv run python -m kr_pipeline.indicators --target=daily --mode=incremental --window-days=30 >> $LOG_DIR/indicators.log 2>&1

# 매주 토요일 04:00 — 주봉 지표 (주봉 적재 03:00 의 1시간 후)
0  4 * * 6    cd $PROJECT_DIR && uv run python -m kr_pipeline.indicators --target=weekly --mode=incremental --window-weeks=4 >> $LOG_DIR/indicators.log 2>&1

# 매월 1일 03:00 — 일봉 지표 full-refresh (일봉 02:00 후)
0  3 1 * *    cd $PROJECT_DIR && uv run python -m kr_pipeline.indicators --target=daily --mode=full-refresh >> $LOG_DIR/indicators.log 2>&1

# 매월 1일 05:00 — 주봉 지표 full-refresh (주봉 04:00 후)
0  5 1 * *    cd $PROJECT_DIR && uv run python -m kr_pipeline.indicators --target=weekly --mode=full-refresh >> $LOG_DIR/indicators.log 2>&1
```

- [ ] **Step 2: `README.md` 실행 섹션 끝에 추가**

```markdown
- 지표 일봉 백필: `uv run python -m kr_pipeline.indicators --target=daily --mode=backfill`
- 지표 일봉 증분: `uv run python -m kr_pipeline.indicators --target=daily --mode=incremental --window-days=30`
- 지표 일봉 재적재: `uv run python -m kr_pipeline.indicators --target=daily --mode=full-refresh`
- 지표 주봉 백필: `uv run python -m kr_pipeline.indicators --target=weekly --mode=backfill`
- 지표 주봉 증분: `uv run python -m kr_pipeline.indicators --target=weekly --mode=incremental --window-weeks=4`
- 지표 주봉 재적재: `uv run python -m kr_pipeline.indicators --target=weekly --mode=full-refresh`
```

- [ ] **Step 3: `README.md` 운영 점검 쿼리 SQL 블록 끝에 추가**

```sql

-- 미너비니 통과 + RS Rating 80 이상 종목 (#4 분석 대상)
SELECT i.date, s.ticker, s.name, s.sector, i.rs_rating, i.adj_close
  FROM daily_indicators i
  JOIN stocks s USING (ticker)
 WHERE i.date = (SELECT MAX(date) FROM daily_indicators)
   AND i.minervini_pass = TRUE
   AND i.rs_rating >= 80
 ORDER BY i.rs_rating DESC;

-- 미너비니 8 조건 중 통과 개수 분포 (최근 영업일)
SELECT 
  (CASE WHEN minervini_c1 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c2 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c3 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c4 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c5 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c6 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c7 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c8 THEN 1 ELSE 0 END) AS conditions_passed,
  COUNT(*) AS stock_count
FROM daily_indicators
WHERE date = (SELECT MAX(date) FROM daily_indicators)
GROUP BY 1 ORDER BY 1 DESC;
```

- [ ] **Step 4: 커밋**

```bash
git add scripts/cron.example README.md
git commit -m "docs(indicators): cron + README 운영 쿼리"
```

---

## Task 13: 최종 Goal State 검증

- [ ] **Step 1: 전체 테스트**

```bash
uv run pytest 2>&1 | tail -5
```
Expected: 117 passed, 1 warning.

- [ ] **Step 2: 통합 테스트만**

```bash
uv run pytest -m integration -v 2>&1 | tail -10
```
Expected: 6 passed (1 ohlcv + 3 weekly + 2 indicators).

- [ ] **Step 3: 라이브 일봉 indicators backfill (10 종목)**

```bash
uv run python -m kr_pipeline.indicators --target=daily --mode=backfill --limit-tickers=10 2>&1 | tail -10
```
Expected: 정상 종료.

- [ ] **Step 4: DB 상태**

```bash
psql postgresql://localhost/kr_pipeline -c "
SELECT 'daily_indicators' AS t, COUNT(*) FROM daily_indicators
UNION ALL SELECT 'weekly_indicators', COUNT(*) FROM weekly_indicators
UNION ALL SELECT 'pipeline_runs indicators', COUNT(*) FROM pipeline_runs WHERE pipeline='indicators'
"
psql postgresql://localhost/kr_pipeline -c "SELECT id, pipeline, mode, status, rows_affected FROM pipeline_runs ORDER BY id DESC LIMIT 3"
```

Expected: daily_indicators 행 존재, pipeline_runs indicators 적어도 1 success.

- [ ] **Step 5: git status 깨끗**

```bash
git status
```
Expected: clean working tree.

- [ ] **Step 6: 종료 보고**

```
Indicators 파이프라인 (서브프로젝트 #2) 완료.
- daily + weekly 양쪽 6 가지 실행 패턴 (3 모드 × 2 타깃)
- 117 passed (#1 35 + #1.5 33 + 2 fixes + #2 47)
- 라이브 backfill 스모크 통과
- DB 상태: daily_indicators N행, weekly_indicators M행, pipeline_runs indicators success
다음: V2 (거래량 지표) 또는 #3 (UI)
```

---

## Self-Review (계획 작성자 메모)

- ✅ Spec §2 가격 컨벤션 — 모든 compute 함수 시그니처 `adj_close` 명시. raw close 안 씀.
- ✅ Spec §3 결정 사항 — 모두 task 에 매핑됨.
- ✅ Spec §5 DB 스키마 — Task 1 에서 schema.sql 변경.
- ✅ Spec §6 데이터 흐름 — Task 9 modes.py 에 3 phase 처리.
- ✅ Spec §7 에러 처리 — Phase A 종목 단위 재시도, sanity checks, run_tracking 멱등.
- ✅ Spec §8 테스팅 전략 — 7 개 테스트 파일 ~47 개 테스트.
- ⚠️ Placeholder 없음 — 모든 코드 완전.
- ⚠️ 타입 일관성:
  - `compute_rs_line_in_decline_7m` 의 `current_dates` 가 `pd.Series` (날짜 인덱스) — modes.py 에서 `pd.Series(df.index, index=df.index)` 로 전달
  - `Mode` enum / `Target` enum — modes.py 와 __main__.py 일관
  - `RunStats` — #1, #1.5 와 동일 구조
- ⚠️ 알려진 트레이드오프:
  - `_phase_b_cache` 가 module-level mutable global — 한 run 안에서만 쓰이고 매 run 시작 시 초기화. 동시 실행 안 함 가정.
  - Phase B 가 한 번의 호출에 모든 (ticker, date) 의 1y_return 을 메모리에 모음 — 2,500 × 500일 = 125만 entry, ~10MB. 메모리 부담 작음.
  - 주봉 RS Rating 의 lookback 52 주는 종목별 weekly_prices 가 52주 미만이면 NULL. 신규 상장 정상 처리.

자율 실행자는 위 ⚠️ 항목을 인지하고 진행할 것.
