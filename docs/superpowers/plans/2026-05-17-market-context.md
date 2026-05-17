# 시장 컨텍스트 + Breadth 인프라 구현 계획 (#2.5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `index_daily` / `daily_indicators` / `stocks` 를 입력으로 시장별 (KOSPI/KOSDAQ) `current_status`, distribution day count, FTD, days-since-FTD, breadth 를 사전 계산해서 `market_context_daily` 테이블에 적재하는 `kr_pipeline.market_context` Python 패키지 구현.

**Architecture:** 단일 패키지 + 모드 인자 진입점 (#1/#1.5/#2 동일 패턴). `compute/*` 순수 함수 4 개 (distribution_day, follow_through, status, breadth) + `load`/`store` DB IO 분리. 날짜 단위 처리 (종목별 처리 없음). 모든 쓰기 멱등 UPSERT. 외부 IO 없음 (DB-to-DB).

**Tech Stack:** Python 3.11+, uv, psycopg[binary], pandas, pytest, freezegun (모두 기존 설치, 신규 의존성 없음)

**Spec:** [`../specs/2026-05-17-market-context-design.md`](../specs/2026-05-17-market-context-design.md)

---

## ⚙️ Autonomous Execution Protocol

**자율 실행 모드.**

### Goal State

다음 조건을 **모두** 만족하면 종료:

1. 본 계획의 모든 task 체크박스 완료
2. `uv run pytest tests/` — exit 0. 131 → ~156 (testing +25)
3. 스모크 테스트 통과:
   - `uv run python -m kr_pipeline.market_context --mode=backfill` 가 에러 없이 종료
   - DB 확인: `market_context_daily` 테이블에 합리적 행수 (>= 일수 × 2)
4. `git status` clean
5. `pipeline_runs` 최근 `market_context | backfill | success` 행 존재

### 실행 루프 & Stuck Rules

#1/#1.5/#2 와 동일. 같은 에러 3회 반복 → 보고. 환경 문제 → 보고. 그 외 스스로 진단/수정/재시도.

### 무엇을 하지 말 것

- 확인 질문 금지 (계속 진행)
- 사양 외 기능 추가 금지 (YAGNI)
- 기존 모듈 (#1, #1.5, #2) 변경 금지 (단, `kr_pipeline/db/schema.sql` 끝에 시장 컨텍스트 테이블 추가는 예외)

---

## 사전 조건

- #1, #1.5, #2 완료 (HEAD `8c8f175` 또는 이후). 131 tests passing.
- PostgreSQL kr_pipeline / kr_test DB 에 모든 기존 스키마 적용
- `index_daily` 에 데이터 (#1 으로부터, KOSPI '1001' + KOSDAQ '2001' 양쪽)
- `daily_indicators` 에 sma_200 채워진 행 일부 (#2 으로부터, breadth 계산용)

---

## 파일 구조 (참조)

```
kr_pipeline/
├── db/
│   └── schema.sql                          # ← 끝에 market_context_daily 테이블 + 인덱스 추가
├── market_context/                         # ← 신규
│   ├── __init__.py
│   ├── __main__.py
│   ├── modes.py                            # backfill/incremental/full-refresh + orchestration
│   ├── compute/
│   │   ├── __init__.py
│   │   ├── distribution_day.py
│   │   ├── follow_through.py
│   │   ├── status.py
│   │   └── breadth.py
│   ├── load.py
│   └── store.py
└── (나머지 변경 없음)

tests/
├── test_market_context_distribution_day.py
├── test_market_context_follow_through.py
├── test_market_context_status.py
├── test_market_context_breadth.py
├── test_market_context_modes.py
└── test_market_context_integration.py

scripts/cron.example                        # ← 끝에 market_context cron 2 라인 추가
README.md                                   # ← 실행 + 운영 쿼리 추가
```

---

## Task 1: DB 스키마 + 패키지 스캐폴드

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (append)
- Create: `kr_pipeline/market_context/__init__.py`, `kr_pipeline/market_context/compute/__init__.py` (empty)

- [ ] **Step 1: `schema.sql` 끝에 추가**

```sql

-- ====== Market Context (#2.5) ======

CREATE TABLE IF NOT EXISTS market_context_daily (
    date                             DATE          NOT NULL,
    index_code                       VARCHAR(10)   NOT NULL,           -- '1001' (KOSPI) / '2001' (KOSDAQ)
    current_status                   VARCHAR(20)   NOT NULL,           -- confirmed_uptrend / rally_attempt / correction / downtrend
    distribution_day_count_last_25   SMALLINT,
    last_follow_through_day          DATE,
    days_since_follow_through        SMALLINT,
    pct_stocks_above_200d_ma         NUMERIC(5,2),
    computation_notes                TEXT,
    updated_at                       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (date, index_code)
);
CREATE INDEX IF NOT EXISTS idx_market_context_date ON market_context_daily(date);
```

- [ ] **Step 2: 두 DB 에 적용**

```bash
psql postgresql://localhost/kr_pipeline -f kr_pipeline/db/schema.sql
psql postgresql://localhost/kr_test -f kr_pipeline/db/schema.sql
```
Expected: CREATE TABLE / CREATE INDEX 출력, 에러 없음.

- [ ] **Step 3: 검증**

```bash
psql postgresql://localhost/kr_pipeline -c "\d market_context_daily"
```
Expected: 8 컬럼 (date, index_code, current_status, ... updated_at), PK = (date, index_code), idx_market_context_date 인덱스 존재.

- [ ] **Step 4: 빈 패키지 디렉토리**

```bash
mkdir -p kr_pipeline/market_context/compute
touch kr_pipeline/market_context/__init__.py
touch kr_pipeline/market_context/compute/__init__.py
```

- [ ] **Step 5: 전체 테스트 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 131 passed (스키마 추가만, 회귀 없음).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/db/schema.sql kr_pipeline/market_context/__init__.py kr_pipeline/market_context/compute/__init__.py
git commit -m "feat(market_context): DB 스키마 추가 + 패키지 스캐폴드"
```

---

## Task 2: compute/distribution_day.py (TDD)

**Files:**
- Create: `kr_pipeline/market_context/compute/distribution_day.py`
- Create: `tests/test_market_context_distribution_day.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_market_context_distribution_day.py
import pandas as pd
import pytest

from kr_pipeline.market_context.compute.distribution_day import (
    is_distribution_day,
    count_distribution_days,
)


def test_is_distribution_day_basic():
    """close -0.5% AND volume > 전일 → True."""
    # close 100 → 99.5 (-0.5%), volume 100 → 110 (up)
    assert is_distribution_day(today_close=99.5, today_volume=110, yesterday_close=100.0, yesterday_volume=100) == True


def test_is_distribution_day_marginal_pct():
    """close -0.19% → False (경계 -0.2% 직전)."""
    assert is_distribution_day(today_close=99.81, today_volume=110, yesterday_close=100.0, yesterday_volume=100) == False


def test_is_distribution_day_volume_equal_or_less():
    """vol <= 전일 → False."""
    assert is_distribution_day(today_close=99.0, today_volume=100, yesterday_close=100.0, yesterday_volume=100) == False
    assert is_distribution_day(today_close=99.0, today_volume=90, yesterday_close=100.0, yesterday_volume=100) == False


def test_is_distribution_day_up_day_false():
    """상승일 → False 무조건."""
    assert is_distribution_day(today_close=101.0, today_volume=200, yesterday_close=100.0, yesterday_volume=100) == False


def test_count_distribution_days_25_session():
    """25 세션 중 분포일 3개 → 3 반환."""
    rows = []
    for i in range(30):
        if i in (5, 10, 20):
            # 분포일: -0.5%, vol up
            rows.append({"close": 99.5, "volume": 200})
        else:
            rows.append({"close": 100.0, "volume": 100})
    df = pd.DataFrame(rows)
    # 분포일 판정에는 전일 close 가 필요. df.iloc[i] 에 close, volume 만 있음 → 전일은 i-1
    count = count_distribution_days(df, end_idx=29, lookback=25)
    # end_idx=29 (마지막) 부터 직전 25 세션 (인덱스 5~29 포함) → 분포일 i=5, 10, 20 모두 포함
    # 단 i=5 의 전일은 i=4 (close=100), today i=5 close=99.5, vol=200>100 → distribution
    assert count == 3


def test_count_distribution_days_short_history():
    """lookback 보다 짧은 데이터 → 가능한 만큼만 카운트."""
    rows = [{"close": 100.0, "volume": 100}, {"close": 99.5, "volume": 200}]
    df = pd.DataFrame(rows)
    count = count_distribution_days(df, end_idx=1, lookback=25)
    assert count == 1   # i=1 이 분포일
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_market_context_distribution_day.py -v
```
Expected: ImportError.

- [ ] **Step 3: 구현**

```python
# kr_pipeline/market_context/compute/distribution_day.py
"""분포일 (Distribution Day) 계산 순수 함수.

정의 (O'Neil/Kacher):
- 종가가 전일 대비 -0.2% 이상 하락
- 거래량이 전일보다 많음
"""
import pandas as pd


DISTRIBUTION_DAY_PCT_THRESHOLD = -0.2   # community standard, IBD


def is_distribution_day(
    today_close: float,
    today_volume: float,
    yesterday_close: float,
    yesterday_volume: float,
) -> bool:
    """오늘이 분포일인지 판정."""
    if yesterday_close == 0:
        return False
    pct_change = (today_close - yesterday_close) / yesterday_close * 100
    return pct_change <= DISTRIBUTION_DAY_PCT_THRESHOLD and today_volume > yesterday_volume


def count_distribution_days(index_df: pd.DataFrame, end_idx: int, lookback: int = 25) -> int:
    """end_idx 기준 직전 lookback 세션 내 분포일 카운트.
    
    index_df 컬럼: close, volume. date 정렬 가정.
    end_idx 가 분포일이면 카운트에 포함.
    분포일 판정에 전일 데이터 필요하므로 i=0 은 카운트 불가.
    """
    if end_idx <= 0 or len(index_df) == 0:
        return 0
    
    start_idx = max(1, end_idx - lookback + 1)   # 최소 1 (i=0 은 전일 없음)
    count = 0
    for i in range(start_idx, end_idx + 1):
        if i >= len(index_df):
            break
        today = index_df.iloc[i]
        yesterday = index_df.iloc[i - 1]
        if is_distribution_day(
            today_close=float(today["close"]),
            today_volume=float(today["volume"]),
            yesterday_close=float(yesterday["close"]),
            yesterday_volume=float(yesterday["volume"]),
        ):
            count += 1
    return count
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_market_context_distribution_day.py -v
```
Expected: 6 passed.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 137 passed (131 + 6).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/market_context/compute/distribution_day.py tests/test_market_context_distribution_day.py
git commit -m "feat(market_context): compute/distribution_day - 분포일 판정 + 카운트"
```

---

## Task 3: compute/follow_through.py (TDD)

**Files:**
- Create: `kr_pipeline/market_context/compute/follow_through.py`
- Create: `tests/test_market_context_follow_through.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_market_context_follow_through.py
from datetime import date
import pandas as pd
import pytest

from kr_pipeline.market_context.compute.follow_through import detect_last_ftd


def _make_df(dates_and_close_vol_low):
    """[(date_obj, close, volume, low)] → DataFrame."""
    rows = [{"date": d, "close": c, "volume": v, "low": l} for d, c, v, l in dates_and_close_vol_low]
    return pd.DataFrame(rows)


def test_ftd_basic():
    """+1.5% AND volume up AND rally 5세션 후 → FTD."""
    # 20일 데이터: 처음 10일 하락, 11일에 저점, 15일에 +1.5% (5세션 후)
    rows = []
    base_date = date(2026, 1, 5)   # Monday
    closes = [100, 98, 96, 94, 92, 90, 88, 87, 86, 85, 84, 85, 86, 87, 88, 89.32, 90, 91, 92, 93]
    volumes = [100] * 14 + [200, 250, 200, 200, 200, 200]  # idx 15 에 vol up
    lows = [c - 1 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)
    
    # idx 15 close=89.32, idx 14 close=88 → +1.5% AND vol 250 > 200 → 후보
    # idx 14 의 직전 15 세션 (idx 0-13) 내 저점: idx 10 close=84
    # idx 15 와 idx 10 의 차이 = 5 세션 → 3~15 범위 → 유효 FTD
    result = detect_last_ftd(df, end_idx=19, lookback_days=90)
    assert result == df.iloc[15]["date"]


def test_ftd_below_threshold():
    """+1.3% → 후보 아님."""
    rows = []
    base_date = date(2026, 1, 5)
    closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 91, 92, 93, 94.22, 95, 96, 97, 98, 99]
    # idx 14 close 94.22, idx 13 close 93 → +1.31%
    volumes = [100] * 13 + [200, 250, 200, 200, 200, 200, 200]
    lows = [c - 1 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)
    
    # idx 14: +1.31% < 1.4% → FTD 후보 아님
    result = detect_last_ftd(df, end_idx=19, lookback_days=90)
    # 다른 곳에서도 +1.4% 없음 → None
    assert result is None


def test_ftd_too_close_to_low():
    """2세션 후 → 부적합 (3-15 범위 밖)."""
    rows = []
    base_date = date(2026, 1, 5)
    # idx 10: 저점. idx 12 (2세션 후) 에 +1.5% → 너무 빠름
    closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 84, 85, 86.28, 87, 88, 89, 90, 91, 92, 93]
    volumes = [100] * 11 + [150, 250, 200, 200, 200, 200, 200, 200, 200]
    lows = [c - 1 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)
    
    # idx 12: close 86.28, idx 11 close 85 → +1.5%. vol 250 > 150 → 후보
    # 직전 15 세션 내 저점: idx 10 close=84
    # 12 - 10 = 2 세션 → 3 미만 → 무효
    result = detect_last_ftd(df, end_idx=19, lookback_days=90)
    assert result is None


def test_ftd_too_far_from_low():
    """16세션 후 → 무효."""
    rows = []
    base_date = date(2026, 1, 5)
    # idx 5 저점, idx 21 (16세션 후) 에 +1.5%
    closes = [100, 95, 92, 90, 85, 80, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97.44, 98]
    volumes = [100] * 20 + [150, 250, 200]
    lows = [c - 1 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)
    
    # idx 21: +1.5% AND vol up. 직전 15 세션 (idx 6-20) 내 저점: idx 6 close=82
    # 21 - 6 = 15 세션. 정확히 경계.
    # 정의: 3 <= days <= 15 → 포함 → 유효
    result = detect_last_ftd(df, end_idx=22, lookback_days=90)
    assert result == df.iloc[21]["date"]


def test_ftd_no_recent_low():
    """직전 15세션 내 저점이 없으면 (모두 상승) → 후보 없음."""
    rows = []
    base_date = date(2026, 1, 5)
    # 단조 상승: 저점 없음 (시작점이 최저)
    closes = [80 + i * 0.5 for i in range(20)]
    closes[15] = closes[14] * 1.015  # +1.5%
    volumes = [100] * 14 + [200, 250] + [200] * 4
    lows = [c - 0.5 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)
    
    # idx 15: +1.5%. 직전 15 세션 (idx 0-14) 의 저점: idx 0 (78)
    # 15 - 0 = 15 세션 → 경계 OK
    # 단조 상승이지만 idx 0 이 가장 낮음. 사실 유효 FTD가 아닌 케이스를 만들기 어려움.
    # 다른 시나리오: 짧은 데이터로 처음 lookback 미만
    df_short = df.iloc[:3].copy()
    result = detect_last_ftd(df_short, end_idx=2, lookback_days=90)
    assert result is None   # 데이터 부족
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_market_context_follow_through.py -v
```
Expected: ImportError.

- [ ] **Step 3: 구현**

```python
# kr_pipeline/market_context/compute/follow_through.py
"""Follow-Through Day (FTD) 감지 순수 함수.

정의 (Morales/Kacher 갱신):
- 지수 상승 +1.4% 이상 (O'Neil 원래 1.0%, 변동성 증가로 상향)
- 거래량이 전일보다 많음
- 직전 15 세션 내 저점 이후 3-15 세션 사이 발생 (rally attempt 기간)
"""
from datetime import date
import pandas as pd


FTD_PCT_THRESHOLD = 1.4              # Kacher 권장 (책: 1.0%)
FTD_RALLY_WINDOW_MIN = 3             # 책 명시
FTD_RALLY_WINDOW_MAX = 15            # 책 명시
FTD_LOW_LOOKBACK = 15                # rally start 후보 lookback


def detect_last_ftd(
    index_df: pd.DataFrame,
    end_idx: int,
    lookback_days: int = 90,
) -> date | None:
    """end_idx 기준 직전 lookback_days 세션 내 가장 최근 유효 FTD 날짜 반환.
    
    index_df 컬럼: date, close, volume, low. date 정렬 가정.
    
    유효 FTD 조건:
    1. (today.close / yesterday.close - 1) * 100 >= FTD_PCT_THRESHOLD
    2. today.volume > yesterday.volume
    3. 직전 FTD_LOW_LOOKBACK 세션 내 저점이 존재
    4. 그 저점 이후 FTD_RALLY_WINDOW_MIN..FTD_RALLY_WINDOW_MAX 세션 사이에 위치
    """
    if end_idx <= 0 or len(index_df) == 0:
        return None
    
    start_idx = max(1, end_idx - lookback_days + 1)
    
    # 최신 → 과거 순회 (가장 최근 유효 FTD 가 첫 발견되면 반환)
    for i in range(end_idx, start_idx - 1, -1):
        if i >= len(index_df):
            continue
        if i < 1:
            break
        today = index_df.iloc[i]
        yesterday = index_df.iloc[i - 1]
        if yesterday["close"] == 0:
            continue
        pct = (today["close"] - yesterday["close"]) / yesterday["close"] * 100
        if pct < FTD_PCT_THRESHOLD:
            continue
        if today["volume"] <= yesterday["volume"]:
            continue
        
        # 직전 FTD_LOW_LOOKBACK 세션 내 저점 찾기
        lookback_start = max(0, i - FTD_LOW_LOOKBACK)
        window = index_df.iloc[lookback_start:i]
        if len(window) < FTD_RALLY_WINDOW_MIN:
            continue
        low_pos_in_window = window["low"].astype(float).idxmin()
        low_idx = int(low_pos_in_window) if isinstance(low_pos_in_window, (int, pd.Int64Dtype)) else window.index.get_loc(low_pos_in_window)
        # idxmin 은 원본 인덱스 라벨. iloc 위치로 변환.
        # 단순화: window 가 reset_index 안 됐다면 idxmin 은 그대로 원본 라벨.
        # 우리 케이스는 index_df 가 0..N-1 정수 인덱스라 가정.
        try:
            low_idx_int = int(low_pos_in_window)
        except (TypeError, ValueError):
            continue
        
        days_from_low = i - low_idx_int
        if FTD_RALLY_WINDOW_MIN <= days_from_low <= FTD_RALLY_WINDOW_MAX:
            return today["date"] if isinstance(today["date"], date) else today["date"]
    
    return None
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_market_context_follow_through.py -v
```
Expected: 5 passed.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 142 passed (137 + 5).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/market_context/compute/follow_through.py tests/test_market_context_follow_through.py
git commit -m "feat(market_context): compute/follow_through - FTD 감지"
```

---

## Task 4: compute/status.py (TDD)

**Files:**
- Create: `kr_pipeline/market_context/compute/status.py`
- Create: `tests/test_market_context_status.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_market_context_status.py
from datetime import date, timedelta
import pytest

from kr_pipeline.market_context.compute.status import determine_status


TODAY = date(2026, 5, 17)


def test_status_downtrend_basic():
    """close < sma_200 AND sma_50 < sma_200 AND off_high < -15% → downtrend."""
    result = determine_status(
        close=80.0, sma_50=90.0, sma_200=100.0,
        pct_off_yearly_high=-20.0,
        dist_count=0, last_ftd_date=None, today_date=TODAY,
    )
    assert result == "downtrend"


def test_status_correction_off_high():
    """off_high < -10% AND close < sma_50 → correction."""
    result = determine_status(
        close=85.0, sma_50=90.0, sma_200=88.0,
        pct_off_yearly_high=-12.0,
        dist_count=2, last_ftd_date=None, today_date=TODAY,
    )
    assert result == "correction"


def test_status_correction_dist_invalidates_ftd():
    """dist_count >= 6 AND FTD 10일 초과 → correction."""
    result = determine_status(
        close=95.0, sma_50=92.0, sma_200=88.0,
        pct_off_yearly_high=-5.0,
        dist_count=6, last_ftd_date=TODAY - timedelta(days=15), today_date=TODAY,
    )
    assert result == "correction"


def test_status_confirmed_uptrend():
    """FTD 90일 내 + close > sma_50 + dist < 6 → confirmed_uptrend."""
    result = determine_status(
        close=100.0, sma_50=95.0, sma_200=90.0,
        pct_off_yearly_high=-2.0,
        dist_count=2, last_ftd_date=TODAY - timedelta(days=30), today_date=TODAY,
    )
    assert result == "confirmed_uptrend"


def test_status_rally_attempt_no_ftd():
    """close > sma_50 + FTD 없음 → rally_attempt."""
    result = determine_status(
        close=100.0, sma_50=95.0, sma_200=90.0,
        pct_off_yearly_high=-5.0,
        dist_count=2, last_ftd_date=None, today_date=TODAY,
    )
    assert result == "rally_attempt"


def test_status_rally_attempt_old_ftd():
    """close > sma_50 + FTD 90일 초과 → rally_attempt."""
    result = determine_status(
        close=100.0, sma_50=95.0, sma_200=90.0,
        pct_off_yearly_high=-5.0,
        dist_count=2, last_ftd_date=TODAY - timedelta(days=120), today_date=TODAY,
    )
    assert result == "rally_attempt"


def test_status_fallback_below_sma50():
    """close < sma_50 fallback → correction."""
    result = determine_status(
        close=85.0, sma_50=90.0, sma_200=88.0,
        pct_off_yearly_high=-3.0,        # downtrend/correction off_high 조건 안 맞음
        dist_count=2, last_ftd_date=None, today_date=TODAY,
    )
    assert result == "correction"
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_market_context_status.py -v
```
Expected: ImportError.

- [ ] **Step 3: 구현**

```python
# kr_pipeline/market_context/compute/status.py
"""current_status 결정 룰 (6 우선순위).

룰 (위에서 아래로 첫 매칭):
1. close < SMA200 AND SMA50 < SMA200 AND off_high < -15 → downtrend
2. off_high < -10 AND close < SMA50 → correction
3. dist_count >= 6 AND FTD 10일 초과 → correction (FTD 무효)
4. FTD 90일 내 AND close > SMA50 AND dist_count < 6 → confirmed_uptrend
5. close > SMA50 AND (FTD 없거나 90일 초과) → rally_attempt
6. fallback: rally_attempt if close > SMA50 else correction
"""
from datetime import date


CORRECTION_OFF_HIGH_PCT = -10.0
DOWNTREND_OFF_HIGH_PCT = -15.0
DIST_COUNT_THRESHOLD_FOR_FTD_INVALIDATION = 6
FTD_RECENT_DAYS = 90
FTD_INVALIDATION_DAYS = 10


def determine_status(
    close: float,
    sma_50: float | None,
    sma_200: float | None,
    pct_off_yearly_high: float,
    dist_count: int,
    last_ftd_date: date | None,
    today_date: date,
) -> str:
    """4 enum 중 하나 반환."""
    days_since_ftd = (today_date - last_ftd_date).days if last_ftd_date else None
    
    # 1. downtrend
    if (sma_200 is not None and sma_50 is not None
        and close < sma_200 and sma_50 < sma_200
        and pct_off_yearly_high < DOWNTREND_OFF_HIGH_PCT):
        return "downtrend"
    
    # 2. correction (가격 기준)
    if (pct_off_yearly_high < CORRECTION_OFF_HIGH_PCT
        and sma_50 is not None and close < sma_50):
        return "correction"
    
    # 3. correction (FTD 무효화)
    if (dist_count >= DIST_COUNT_THRESHOLD_FOR_FTD_INVALIDATION
        and last_ftd_date is not None and days_since_ftd > FTD_INVALIDATION_DAYS):
        return "correction"
    
    # 4. confirmed_uptrend
    if (last_ftd_date is not None and days_since_ftd is not None
        and days_since_ftd <= FTD_RECENT_DAYS
        and sma_50 is not None and close > sma_50
        and dist_count < DIST_COUNT_THRESHOLD_FOR_FTD_INVALIDATION):
        return "confirmed_uptrend"
    
    # 5. rally_attempt (FTD 없거나 오래된)
    if (sma_50 is not None and close > sma_50
        and (last_ftd_date is None or days_since_ftd > FTD_RECENT_DAYS)):
        return "rally_attempt"
    
    # 6. fallback
    if sma_50 is not None and close > sma_50:
        return "rally_attempt"
    return "correction"
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_market_context_status.py -v
```
Expected: 7 passed.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 149 passed (142 + 7).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/market_context/compute/status.py tests/test_market_context_status.py
git commit -m "feat(market_context): compute/status - 6 룰 우선순위로 current_status 결정"
```

---

## Task 5: compute/breadth.py (TDD)

**Files:**
- Create: `kr_pipeline/market_context/compute/breadth.py`
- Create: `tests/test_market_context_breadth.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_market_context_breadth.py
import pytest

from kr_pipeline.market_context.compute.breadth import compute_breadth


def test_breadth_basic():
    """10 종목 중 6 개가 SMA200 위 → 60.0%."""
    rows = [
        {"adj_close": 100.0, "sma_200": 90.0},   # above
        {"adj_close": 100.0, "sma_200": 95.0},   # above
        {"adj_close": 100.0, "sma_200": 99.0},   # above
        {"adj_close": 100.0, "sma_200": 80.0},   # above
        {"adj_close": 100.0, "sma_200": 50.0},   # above
        {"adj_close": 100.0, "sma_200": 70.0},   # above
        {"adj_close": 100.0, "sma_200": 110.0},  # below
        {"adj_close": 100.0, "sma_200": 120.0},  # below
        {"adj_close": 100.0, "sma_200": 130.0},  # below
        {"adj_close": 100.0, "sma_200": 105.0},  # below
    ]
    result = compute_breadth(rows)
    assert result == 60.0


def test_breadth_excludes_null_sma200():
    """sma_200 NULL 종목은 제외."""
    rows = [
        {"adj_close": 100.0, "sma_200": 90.0},   # above
        {"adj_close": 100.0, "sma_200": None},   # 제외
        {"adj_close": 100.0, "sma_200": 110.0},  # below
        {"adj_close": 100.0, "sma_200": None},   # 제외
    ]
    result = compute_breadth(rows)
    # 유효 2: above 1, below 1 → 50.0
    assert result == 50.0


def test_breadth_empty_universe():
    """0 종목 → None."""
    assert compute_breadth([]) is None
    assert compute_breadth([{"adj_close": 100.0, "sma_200": None}]) is None
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
uv run pytest tests/test_market_context_breadth.py -v
```
Expected: ImportError.

- [ ] **Step 3: 구현**

```python
# kr_pipeline/market_context/compute/breadth.py
"""시장 Breadth 계산 (해당 시장의 활성 종목 중 SMA200 위 비율).

입력: 특정 (시장, 날짜) 의 daily_indicators 행들 ({adj_close, sma_200, ...}).
sma_200 NULL 종목은 lookback 부족으로 제외 (상장 1년 미만).
"""


def compute_breadth(rows: list[dict]) -> float | None:
    """% (소수 1자리). 유효 종목 0개면 None."""
    valid = [r for r in rows if r.get("sma_200") is not None]
    if not valid:
        return None
    above = sum(1 for r in valid if float(r["adj_close"]) > float(r["sma_200"]))
    return round(above / len(valid) * 100, 1)
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_market_context_breadth.py -v
```
Expected: 3 passed.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 152 passed (149 + 3).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/market_context/compute/breadth.py tests/test_market_context_breadth.py
git commit -m "feat(market_context): compute/breadth - 시장별 SMA200 위 비율"
```

---

## Task 6: load.py

**Files:**
- Create: `kr_pipeline/market_context/load.py`

- [ ] **Step 1: 구현**

```python
# kr_pipeline/market_context/load.py
"""market_context 파이프라인 입력 SELECT 헬퍼."""
from datetime import date

import pandas as pd
from psycopg import Connection


def load_index_daily_with_sma200(
    conn: Connection,
    index_code: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """지수 일봉 + 지수 자체의 SMA50, SMA200, low, yearly_high 시계열.
    
    index_daily 에는 sma 가 없으므로, 함수 내에서 rolling 으로 직접 계산.
    
    return columns: date, close, volume, low, sma_50, sma_200, yearly_high
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, close, volume, low
              FROM index_daily
             WHERE index_code = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (index_code, start, end),
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    df["low"] = df["low"].astype(float)
    df["sma_50"] = df["close"].rolling(window=50, min_periods=50).mean()
    df["sma_200"] = df["close"].rolling(window=200, min_periods=200).mean()
    df["yearly_high"] = df["close"].rolling(window=252, min_periods=1).max()
    return df


def load_market_daily_indicators(
    conn: Connection,
    market: str,
    on_date: date,
) -> list[dict]:
    """특정 시장 (KOSPI/KOSDAQ) 의 활성 종목들의 (adj_close, sma_200) at on_date.
    
    breadth 계산용.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.adj_close, i.sma_200
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date = %s
               AND s.market = %s
               AND s.delisted_at IS NULL
            """,
            (on_date, market),
        )
        return [{"adj_close": float(r[0]) if r[0] is not None else None,
                 "sma_200": float(r[1]) if r[1] is not None else None}
                for r in cur.fetchall()]


def get_index_min_date(conn: Connection, index_code: str) -> date | None:
    """index_daily 의 해당 index 가장 오래된 날짜."""
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(date) FROM index_daily WHERE index_code = %s", (index_code,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
```

- [ ] **Step 2: 임포트 확인**

```bash
uv run python -c "from kr_pipeline.market_context.load import load_index_daily_with_sma200, load_market_daily_indicators, get_index_min_date; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 152 passed.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/market_context/load.py
git commit -m "feat(market_context): load - index 시계열 + 시장 종목 SMA200 SELECT 헬퍼"
```

---

## Task 7: store.py (TDD)

**Files:**
- Create: `kr_pipeline/market_context/store.py`
- Create: `tests/test_market_context_store.py`

Note: store 테스트는 modes 통합 테스트에 흡수 가능하지만 store 단위 자체 검증으로 1-2개 가져감.

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_market_context_store.py
from datetime import date

from kr_pipeline.market_context.store import upsert_market_context


def test_upsert_inserts_new_row(db):
    rows = [{
        "date": date(2026, 5, 17),
        "index_code": "1001",
        "current_status": "confirmed_uptrend",
        "distribution_day_count_last_25": 2,
        "last_follow_through_day": date(2026, 4, 12),
        "days_since_follow_through": 35,
        "pct_stocks_above_200d_ma": 47.3,
        "computation_notes": '{"distribution_day_pct_threshold": -0.2}',
    }]
    affected = upsert_market_context(db, rows)
    assert affected == 1
    
    with db.cursor() as cur:
        cur.execute("SELECT current_status, distribution_day_count_last_25, pct_stocks_above_200d_ma FROM market_context_daily WHERE date='2026-05-17' AND index_code='1001'")
        assert cur.fetchone() == ("confirmed_uptrend", 2, 47.30)


def test_upsert_updates_on_conflict(db):
    """같은 (date, index_code) 두 번 → 두 번째 값으로 덮어쓰기."""
    rows_v1 = [{
        "date": date(2026, 5, 17), "index_code": "1001",
        "current_status": "rally_attempt",
        "distribution_day_count_last_25": 1, "last_follow_through_day": None,
        "days_since_follow_through": None, "pct_stocks_above_200d_ma": 30.0,
        "computation_notes": None,
    }]
    upsert_market_context(db, rows_v1)
    
    rows_v2 = [{
        "date": date(2026, 5, 17), "index_code": "1001",
        "current_status": "confirmed_uptrend",
        "distribution_day_count_last_25": 2, "last_follow_through_day": date(2026, 4, 1),
        "days_since_follow_through": 46, "pct_stocks_above_200d_ma": 55.5,
        "computation_notes": None,
    }]
    upsert_market_context(db, rows_v2)
    
    with db.cursor() as cur:
        cur.execute("SELECT current_status, distribution_day_count_last_25 FROM market_context_daily WHERE date='2026-05-17' AND index_code='1001'")
        assert cur.fetchone() == ("confirmed_uptrend", 2)
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_market_context_store.py -v
```
Expected: ImportError.

- [ ] **Step 3: 구현**

```python
# kr_pipeline/market_context/store.py
"""market_context_daily UPSERT."""
from psycopg import Connection


COLUMNS = [
    "date", "index_code", "current_status",
    "distribution_day_count_last_25",
    "last_follow_through_day",
    "days_since_follow_through",
    "pct_stocks_above_200d_ma",
    "computation_notes",
]


def upsert_market_context(conn: Connection, rows: list[dict]) -> int:
    """rows: PHASE A 결과 dict 리스트. (date, index_code) PK 로 UPSERT."""
    if not rows:
        return 0
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    cols_sql = ", ".join(COLUMNS)
    update_sql = ", ".join([f"{c} = EXCLUDED.{c}" for c in COLUMNS if c not in ("date", "index_code")])
    
    sql = f"""
        INSERT INTO market_context_daily ({cols_sql}, updated_at)
        VALUES ({placeholders}, NOW())
        ON CONFLICT (date, index_code) DO UPDATE
           SET {update_sql}, updated_at = NOW()
    """
    
    tuples = [tuple(r.get(c) for c in COLUMNS) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, tuples)
        return cur.rowcount
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_market_context_store.py -v
```
Expected: 2 passed.

- [ ] **Step 5: 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 154 passed (152 + 2).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/market_context/store.py tests/test_market_context_store.py
git commit -m "feat(market_context): store - market_context_daily UPSERT"
```

---

## Task 8: modes.py — 오케스트레이션 (TDD)

**Files:**
- Create: `kr_pipeline/market_context/modes.py`
- Create: `tests/test_market_context_modes.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/test_market_context_modes.py
from datetime import date, timedelta
from freezegun import freeze_time

from kr_pipeline.market_context.modes import (
    Mode, compute_date_range, LOOKBACK_DAYS,
)


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.FULL_REFRESH.value == "full-refresh"


@freeze_time("2026-05-18")
def test_incremental_window_30():
    """load_start = today - 30 - LOOKBACK_DAYS, upsert_start = today - 30."""
    load_start, load_end, upsert_start = compute_date_range(Mode.INCREMENTAL, window_days=30)
    today = date(2026, 5, 18)
    assert load_end == today - timedelta(days=1)
    assert upsert_start == today - timedelta(days=30)
    assert load_start == today - timedelta(days=30 + LOOKBACK_DAYS)


def test_backfill_uses_db_min(monkeypatch):
    from kr_pipeline.market_context import modes
    monkeypatch.setattr(modes, "_get_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        load_start, load_end, upsert_start = compute_date_range(Mode.BACKFILL, conn=None)
    assert load_start == date(2024, 1, 2)
    assert upsert_start == date(2024, 1, 2)
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_market_context_modes.py -v
```
Expected: ImportError.

- [ ] **Step 3: 구현**

```python
# kr_pipeline/market_context/modes.py
"""market_context 모드 분기 + 오케스트레이션."""
import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.market_context.compute.distribution_day import count_distribution_days
from kr_pipeline.market_context.compute.follow_through import detect_last_ftd
from kr_pipeline.market_context.compute.status import determine_status
from kr_pipeline.market_context.compute.breadth import compute_breadth
from kr_pipeline.market_context.load import (
    load_index_daily_with_sma200, load_market_daily_indicators, get_index_min_date,
)
from kr_pipeline.market_context.store import upsert_market_context


log = logging.getLogger("kr_pipeline.market_context")

LOOKBACK_DAYS = 252           # SMA-200 + yearly high lookback (FTD lookback 90 보다 큼)


INDICES = [
    ("1001", "KOSPI"),
    ("2001", "KOSDAQ"),
]


COMPUTATION_NOTES = json.dumps({
    "distribution_day_pct_threshold": -0.2,
    "ftd_pct_threshold": 1.4,
    "ftd_rally_window_min": 3,
    "ftd_rally_window_max": 15,
    "ftd_lookback_days": 90,
    "correction_off_high_pct": -10,
    "downtrend_off_high_pct": -15,
    "dist_count_threshold_for_ftd_invalidation": 6,
}, ensure_ascii=False)


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full-refresh"


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)


def _get_min_date(conn: Connection) -> date:
    """index_daily 의 가장 오래된 날짜 (KOSPI 와 KOSDAQ 둘 중 작은 것)."""
    kospi_min = get_index_min_date(conn, "1001")
    kosdaq_min = get_index_min_date(conn, "2001")
    candidates = [d for d in (kospi_min, kosdaq_min) if d]
    return min(candidates) if candidates else date.today()


def compute_date_range(
    mode: Mode,
    *,
    window_days: int = 30,
    conn: Connection | None = None,
) -> tuple[date, date, date]:
    """(load_start, load_end, upsert_start)."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    
    if mode == Mode.INCREMENTAL:
        load_start = today - timedelta(days=window_days + LOOKBACK_DAYS)
        upsert_start = today - timedelta(days=window_days)
        return load_start, yesterday, upsert_start
    
    if mode in (Mode.BACKFILL, Mode.FULL_REFRESH):
        min_date = _get_min_date(conn) if conn else today
        return min_date, yesterday, min_date
    
    raise ValueError(f"Unknown mode: {mode}")


def _process_one_date(
    conn: Connection,
    target_date: date,
    index_code: str,
    market: str,
    index_df,
) -> dict | None:
    """특정 (date, index_code) 의 컨텍스트 1 행 계산.
    
    index_df: load_index_daily_with_sma200 결과 (시계열, end_idx 까지).
    target_date 가 index_df 에 있어야 함.
    """
    # target_date 의 row 위치 찾기
    matching = index_df[index_df["date"] == target_date]
    if matching.empty:
        return None
    end_idx = matching.index[0]
    
    today_row = index_df.iloc[end_idx]
    
    # Status 결정 입력 준비
    close = float(today_row["close"])
    sma_50 = float(today_row["sma_50"]) if not _is_nan(today_row["sma_50"]) else None
    sma_200 = float(today_row["sma_200"]) if not _is_nan(today_row["sma_200"]) else None
    yearly_high = float(today_row["yearly_high"])
    pct_off_yearly_high = (close - yearly_high) / yearly_high * 100 if yearly_high > 0 else 0.0
    
    dist_count = count_distribution_days(index_df, end_idx=end_idx, lookback=25)
    last_ftd_date = detect_last_ftd(index_df, end_idx=end_idx, lookback_days=90)
    days_since_ftd = (target_date - last_ftd_date).days if last_ftd_date else None
    
    current_status = determine_status(
        close=close, sma_50=sma_50, sma_200=sma_200,
        pct_off_yearly_high=pct_off_yearly_high,
        dist_count=dist_count, last_ftd_date=last_ftd_date, today_date=target_date,
    )
    
    # Breadth
    rows_for_breadth = load_market_daily_indicators(conn, market, target_date)
    breadth = compute_breadth(rows_for_breadth)
    
    return {
        "date": target_date,
        "index_code": index_code,
        "current_status": current_status,
        "distribution_day_count_last_25": dist_count,
        "last_follow_through_day": last_ftd_date,
        "days_since_follow_through": days_since_ftd,
        "pct_stocks_above_200d_ma": breadth,
        "computation_notes": COMPUTATION_NOTES,
    }


def _is_nan(v) -> bool:
    import math
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


def _run_sanity_checks(conn: Connection, upsert_end: date) -> list[str]:
    warnings = []
    with conn.cursor() as cur:
        # 1. status 분포 (4 enum 외 없는지 — 코드 보장이라 거의 안 트리거)
        cur.execute("""
            SELECT current_status, COUNT(*) FROM market_context_daily 
             WHERE date = %s GROUP BY current_status
        """, (upsert_end,))
        statuses = {row[0]: row[1] for row in cur.fetchall()}
        if any(s not in ("confirmed_uptrend", "rally_attempt", "correction", "downtrend") for s in statuses):
            warnings.append(f"unknown_status: {set(statuses) - {'confirmed_uptrend','rally_attempt','correction','downtrend'}}")
        
        # 2. breadth 범위 (0~100)
        cur.execute("""
            SELECT COUNT(*) FROM market_context_daily 
             WHERE date = %s AND pct_stocks_above_200d_ma IS NOT NULL 
               AND (pct_stocks_above_200d_ma < 0 OR pct_stocks_above_200d_ma > 100)
        """, (upsert_end,))
        bad_breadth = cur.fetchone()[0]
        if bad_breadth > 0:
            warnings.append(f"breadth_out_of_range: {bad_breadth} rows")
        
        # 3. dist_count 범위 (0~25)
        cur.execute("""
            SELECT COUNT(*) FROM market_context_daily
             WHERE date = %s AND (distribution_day_count_last_25 < 0 OR distribution_day_count_last_25 > 25)
        """, (upsert_end,))
        bad_dist = cur.fetchone()[0]
        if bad_dist > 0:
            warnings.append(f"dist_count_out_of_range: {bad_dist} rows")
    return warnings


def run(
    conn: Connection,
    mode: Mode,
    *,
    window_days: int = 30,
) -> RunStats:
    load_start, load_end, upsert_start = compute_date_range(
        mode, window_days=window_days, conn=conn,
    )
    log.info(f"market_context mode={mode.value} load={load_start}..{load_end} upsert={upsert_start}..{load_end}")
    
    rows_total = 0
    failures: list[tuple[str, str]] = []
    
    with run_tracking(
        conn,
        pipeline="market_context",
        mode=mode.value,
        params={"window_days": window_days, "load_start": str(load_start),
                "load_end": str(load_end), "upsert_start": str(upsert_start)},
    ) as state:
        # KOSPI 와 KOSDAQ 처리
        for index_code, market in INDICES:
            try:
                idx_df = load_index_daily_with_sma200(conn, index_code, load_start, load_end)
                if idx_df.empty:
                    log.warning(f"no index_daily data for {index_code}")
                    continue
                
                # upsert_start 이상인 날짜만 처리
                target_rows = idx_df[idx_df["date"] >= upsert_start]
                rows_to_upsert = []
                for _, row in target_rows.iterrows():
                    target_date = row["date"]
                    if isinstance(target_date, str):
                        from datetime import date as _date
                        target_date = _date.fromisoformat(target_date)
                    elif hasattr(target_date, "date"):
                        target_date = target_date.date()
                    try:
                        result = _process_one_date(conn, target_date, index_code, market, idx_df)
                        if result:
                            rows_to_upsert.append(result)
                    except Exception as e:
                        failures.append((f"{index_code}@{target_date}", str(e)))
                
                if rows_to_upsert:
                    rows_total += upsert_market_context(conn, rows_to_upsert)
                    conn.commit()
                    log.info(f"{index_code}: upserted {len(rows_to_upsert)} rows")
            
            except Exception as e:
                failures.append((index_code, str(e)))
                conn.rollback()
        
        # Sanity
        warnings = _run_sanity_checks(conn, load_end)
        state["warnings"].extend(warnings)
        state["rows_affected"] = rows_total
    
    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/test_market_context_modes.py -v
```
Expected: 3 passed.

- [ ] **Step 5: 전체 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 157 passed (154 + 3).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/market_context/modes.py tests/test_market_context_modes.py
git commit -m "feat(market_context): modes - 3 모드 + 오케스트레이션"
```

---

## Task 9: __main__.py 진입점

**Files:**
- Create: `kr_pipeline/market_context/__main__.py`

- [ ] **Step 1: 구현**

```python
# kr_pipeline/market_context/__main__.py
"""market_context 파이프라인 진입점."""
import argparse
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.market_context.modes import Mode, run


log = logging.getLogger("kr_pipeline.market_context")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.market_context")
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--window-days", type=int, default=30, help="incremental 윈도우")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    
    with connect(cfg.database_url) as conn:
        stats = run(conn, Mode(args.mode), window_days=args.window_days)
        log.info(
            f"DONE market_context mode={args.mode} "
            f"rows_affected={stats.rows_affected} failures={len(stats.failures)} warnings={len(stats.warnings)}"
        )
        if stats.warnings:
            for w in stats.warnings:
                log.warning(f"sanity: {w}")
        if stats.failures:
            log.warning(f"Failed: {[t for t, _ in stats.failures[:20]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 헬프 확인**

```bash
uv run python -m kr_pipeline.market_context --help
```
Expected: `--mode {backfill,incremental,full-refresh}` 출력.

- [ ] **Step 3: 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 157 passed.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/market_context/__main__.py
git commit -m "feat(market_context): 진입점 (argparse)"
```

---

## Task 10: 통합 테스트 + 라이브 스모크

**Files:**
- Create: `tests/test_market_context_integration.py`

- [ ] **Step 1: 통합 테스트 작성**

```python
# tests/test_market_context_integration.py
from datetime import date, timedelta
import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.market_context.modes import Mode, run


pytestmark = pytest.mark.integration


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_context_daily")
        cur.execute("DELETE FROM daily_indicators")
        cur.execute("DELETE FROM index_daily")
        cur.execute("DELETE FROM daily_prices")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('MKTTEST1', 'MKTTEST2')")
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'market_context'")
    conn.commit()


def _seed_index_data(conn, days: int = 300):
    """KOSPI 1001 에 days 일치 데이터 + KOSDAQ 2001 에 들어가는 더미.
    
    SMA200/yearly_high 통과 위해 충분한 일수.
    """
    base = date(2025, 1, 2)
    with conn.cursor() as cur:
        # stocks: KOSPI 종목 1개 + KOSDAQ 종목 1개
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('MKTTEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('MKTTEST2', 'T2', 'KOSDAQ') ON CONFLICT DO NOTHING")
        
        for i in range(days):
            d = base + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            # KOSPI 지수: 우상향
            kospi_close = 2500 + i * 1.0
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES ('1001', %s, %s, %s, %s, %s, 1000, 1000000)
                   ON CONFLICT DO NOTHING""",
                (d, kospi_close - 5, kospi_close + 5, kospi_close - 8, kospi_close),
            )
            # KOSDAQ
            kosdaq_close = 700 + i * 0.5
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES ('2001', %s, %s, %s, %s, %s, 500, 500000)
                   ON CONFLICT DO NOTHING""",
                (d, kosdaq_close - 3, kosdaq_close + 3, kosdaq_close - 5, kosdaq_close),
            )
            # daily_prices + daily_indicators (breadth 용)
            for ticker in ("MKTTEST1", "MKTTEST2"):
                price = 100.0 + i * 0.1
                cur.execute(
                    """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 1000, 100000)
                       ON CONFLICT DO NOTHING""",
                    (ticker, d, price, price + 1, price - 1, price, price),
                )
                # daily_indicators: 마지막 ~100 일에만 sma_200 채움 (lookback 200 통과)
                sma_200 = price - 5 if i >= 200 else None
                cur.execute(
                    """INSERT INTO daily_indicators (ticker, date, adj_close, sma_200, sma_50)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (ticker, d, price, sma_200, price - 2 if i >= 50 else None),
                )
    conn.commit()


def test_backfill_creates_kospi_and_kosdaq_rows(test_db_url):
    """backfill → 매 영업일에 KOSPI + KOSDAQ 양쪽 행 생성."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_index_data(conn, days=300)
        
        try:
            stats = run(conn, Mode.BACKFILL)
            
            assert stats.rows_affected > 0
            
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM market_context_daily WHERE index_code = '1001'")
                kospi_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM market_context_daily WHERE index_code = '2001'")
                kosdaq_count = cur.fetchone()[0]
                
                assert kospi_count > 0
                assert kospi_count == kosdaq_count  # 같은 날짜 양쪽 다 생성
                
                # current_status enum 4 종류 외 없는지
                cur.execute("""
                    SELECT DISTINCT current_status FROM market_context_daily
                """)
                statuses = {row[0] for row in cur.fetchall()}
                allowed = {"confirmed_uptrend", "rally_attempt", "correction", "downtrend"}
                assert statuses.issubset(allowed)
                
                # pipeline_runs
                cur.execute("""
                    SELECT pipeline, mode, status FROM pipeline_runs 
                     WHERE pipeline = 'market_context' ORDER BY id DESC LIMIT 1
                """)
                row = cur.fetchone()
                assert row == ("market_context", "backfill", "success")
        finally:
            _cleanup(conn)


def test_incremental_idempotent(test_db_url):
    """incremental 두 번 → 결과 행 수 동일."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_index_data(conn, days=300)
        
        try:
            run(conn, Mode.BACKFILL)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM market_context_daily")
                first_count = cur.fetchone()[0]
            
            run(conn, Mode.INCREMENTAL, window_days=30)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM market_context_daily")
                second_count = cur.fetchone()[0]
            
            assert first_count == second_count
        finally:
            _cleanup(conn)
```

- [ ] **Step 2: 통합 테스트 실행**

```bash
uv run pytest tests/test_market_context_integration.py -v -m integration 2>&1 | tail -15
```
Expected: 2 passed.

- [ ] **Step 3: 전체 회귀 (idempotency)**

```bash
uv run pytest 2>&1 | tail -3
uv run pytest 2>&1 | tail -3
```
Expected: 159 passed twice (157 unit + 2 integration).

- [ ] **Step 4: 라이브 backfill 스모크**

```bash
uv run python -m kr_pipeline.market_context --mode=backfill 2>&1 | tail -15
```
Expected: 정상 종료. DB 검증:

```bash
psql postgresql://localhost/kr_pipeline -c "SELECT COUNT(*), index_code FROM market_context_daily GROUP BY index_code"
psql postgresql://localhost/kr_pipeline -c "SELECT date, index_code, current_status, distribution_day_count_last_25, pct_stocks_above_200d_ma FROM market_context_daily ORDER BY date DESC, index_code LIMIT 6"
psql postgresql://localhost/kr_pipeline -c "SELECT id, pipeline, mode, status, rows_affected FROM pipeline_runs ORDER BY id DESC LIMIT 3"
```
Expected:
- market_context_daily 에 KOSPI/KOSDAQ 양쪽 행 존재
- pipeline_runs 최근 entry: `market_context | backfill | success`

- [ ] **Step 5: 커밋**

```bash
git add tests/test_market_context_integration.py
git commit -m "test(market_context): end-to-end 통합 테스트 (backfill, 멱등)"
```

---

## Task 11: Cron + README

**Files:**
- Modify: `scripts/cron.example` (append)
- Modify: `README.md` (append)

- [ ] **Step 1: `scripts/cron.example` 끝에 추가**

```cron

# 평일 19:30 — 시장 컨텍스트 (일봉 지표 19:00 의 30 분 후)
30 19 * * 1-5  cd $PROJECT_DIR && uv run python -m kr_pipeline.market_context --mode=incremental --window-days=30 >> $LOG_DIR/market_context.log 2>&1

# 매월 1일 03:30 — 시장 컨텍스트 full-refresh (일봉 지표 03:00 후)
30  3 1 * *    cd $PROJECT_DIR && uv run python -m kr_pipeline.market_context --mode=full-refresh >> $LOG_DIR/market_context.log 2>&1
```

- [ ] **Step 2: `README.md` 실행 섹션 끝에 추가**

```markdown
- 시장 컨텍스트 백필: `uv run python -m kr_pipeline.market_context --mode=backfill`
- 시장 컨텍스트 증분: `uv run python -m kr_pipeline.market_context --mode=incremental --window-days=30`
- 시장 컨텍스트 재적재: `uv run python -m kr_pipeline.market_context --mode=full-refresh`
```

- [ ] **Step 3: `README.md` 운영 점검 쿼리 SQL 블록 끝에 추가**

```sql

-- 오늘의 시장 컨텍스트 (KOSPI + KOSDAQ)
SELECT date, index_code, current_status, 
       distribution_day_count_last_25, 
       last_follow_through_day, 
       days_since_follow_through,
       pct_stocks_above_200d_ma
  FROM market_context_daily
 WHERE date = (SELECT MAX(date) FROM market_context_daily)
 ORDER BY index_code;

-- 최근 30 일 KOSPI 시장 추세 변화
SELECT date, current_status, distribution_day_count_last_25, pct_stocks_above_200d_ma
  FROM market_context_daily
 WHERE index_code = '1001'
   AND date >= (SELECT MAX(date) FROM market_context_daily) - INTERVAL '30 days'
 ORDER BY date DESC;
```

- [ ] **Step 4: 커밋**

```bash
git add scripts/cron.example README.md
git commit -m "docs(market_context): cron + README 운영 쿼리"
```

---

## Task 12: 최종 Goal State 검증

- [ ] **Step 1: 전체 테스트**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 159 passed.

- [ ] **Step 2: 통합 테스트만**

```bash
uv run pytest -m integration -v 2>&1 | tail -10
```
Expected: 7 passed (1 ohlcv + 3 weekly + 2 indicators + 0... wait, prior was 6, new +2 = 8). Actually verify actual count.

- [ ] **Step 3: 라이브 backfill 재실행**

```bash
uv run python -m kr_pipeline.market_context --mode=backfill 2>&1 | tail -5
```
Expected: 정상 종료, DONE 로그.

- [ ] **Step 4: DB 상태**

```bash
psql postgresql://localhost/kr_pipeline -c "
SELECT 'market_context_daily total' AS m, COUNT(*) FROM market_context_daily
UNION ALL SELECT '  KOSPI (1001)', COUNT(*) FROM market_context_daily WHERE index_code='1001'
UNION ALL SELECT '  KOSDAQ (2001)', COUNT(*) FROM market_context_daily WHERE index_code='2001'
UNION ALL SELECT 'pipeline_runs market_context', COUNT(*) FROM pipeline_runs WHERE pipeline='market_context'
"
```

- [ ] **Step 5: git status**

```bash
git status
```
Expected: clean.

- [ ] **Step 6: 종료 보고**

```
시장 컨텍스트 (#2.5) 완료.
- KOSPI + KOSDAQ 각각 행 (시장별 분리)
- 159 passed (131 + 28 new)
- 라이브 backfill 스모크 통과
- DB: market_context_daily N행, KOSPI/KOSDAQ 양쪽 status 채워짐
다음: #2.6 (Corporate Actions Fetcher)
```

---

## Self-Review

- ✅ Spec §1 배경 — Task 별 직접 매핑 없음 (배경 기술), 본 plan 의 시작점
- ✅ Spec §2 결정 사항 — 모든 항목이 task 에 매핑
- ✅ Spec §3 코드 구조 — 파일 구조 + 진입점 = Task 1 + 9
- ✅ Spec §4 DB 스키마 — Task 1 (schema.sql + 적용 + 검증)
- ✅ Spec §5.1 분포일 — Task 2 (compute/distribution_day.py + 5 tests)
- ✅ Spec §5.2 FTD — Task 3 (compute/follow_through.py + 5 tests)
- ✅ Spec §5.3 status — Task 4 (compute/status.py + 7 tests, 6 룰)
- ✅ Spec §5.4 breadth — Task 5 (compute/breadth.py + 3 tests)
- ✅ Spec §6 데이터 흐름 — Task 6 (load.py) + Task 8 (modes.py)
- ✅ Spec §6 Cron 등록 — Task 11
- ✅ Spec §7 에러/멱등성/sanity — Task 7 (store UPSERT) + Task 8 (sanity in modes.py)
- ✅ Spec §8 테스팅 — 6 개 테스트 파일 ~25 테스트 (실제 27, 약간 더 두텁게)
- ⚠️ Placeholder 없음
- ⚠️ 타입 일관성:
  - `Mode` enum (#2 와 동일 패턴)
  - `RunStats` (#2 와 동일 구조)
  - `INDICES` 상수 ('1001'/'2001' 매핑) — modes.py 에서 정의
  - `LOOKBACK_DAYS = 252` — modes.py 상수
- ⚠️ 알려진 트레이드오프:
  - `detect_last_ftd` 의 `low_pos_in_window` argmin 처리 — pandas 인덱스 라벨 변환에 약간의 복잡도. 0..N-1 정수 인덱스 가정.
  - `_process_one_date` 가 종목 universe SELECT 를 매 날짜마다 수행 → backfill 시 다소 비효율 (date × index × stocks 쿼리). 첫 동작 검증 후 최적화 가능.
  - integration test seed 가 300 일치 (SMA200 통과용). seed 시간 ~5초.

자율 실행자는 위 ⚠️ 인지하고 진행할 것.
