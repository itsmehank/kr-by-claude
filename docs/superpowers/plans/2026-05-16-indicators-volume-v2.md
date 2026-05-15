# 지표 V2 - 거래량 지표 추가 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `daily_indicators` / `weekly_indicators` 테이블에 거래량 지표 컬럼 추가. split-adjusted volume + 5 derived indicators (daily) + 3 (weekly). 기존 #2 의 modes/load/store 흐름에 투명하게 통합.

**Architecture:** #2 의 확장. `kr_pipeline/indicators/compute/volume.py` 신규 + 기존 load/store/modes 컬럼 통합. 새 진입점/모드 없음. 단일 ALTER TABLE 마이그레이션.

**Tech Stack:** Python 3.11+, uv, pandas, numpy, pytest (모두 기존 설치)

**Spec:** [`../specs/2026-05-16-indicators-volume-v2-design.md`](../specs/2026-05-16-indicators-volume-v2-design.md)

---

## ⚙️ Autonomous Execution Protocol

**자율 실행 모드.**

### Goal State

다음 조건을 **모두** 만족하면 종료:

1. 본 계획의 모든 task 체크박스 완료
2. `uv run pytest tests/` — exit 0. 117 → ~131 (testing +14)
3. 스모크: `uv run python -m kr_pipeline.indicators --target=daily --mode=backfill --limit-tickers=10` 성공, `daily_indicators.volume`, `volume_ratio_50d` 등 비-NULL 행 확인
4. `git status` clean
5. `pipeline_runs` 최근 indicators 엔트리 success

### 실행 루프 & Stuck Rules

#2 와 동일. 같은 에러 3회 반복 → 보고. 환경 문제 → 보고. 그 외 스스로 진단.

---

## 사전 조건

- #1, #1.5, #2 완료 (HEAD `41de83e` 또는 이후). 117 tests passing.
- PostgreSQL kr_pipeline / kr_test DB 에 #2 스키마 적용 완료
- `daily_prices` / `weekly_prices` 에 `close, volume` 데이터 (이미 있음)

---

## 파일 구조 (참조)

```
kr_pipeline/
├── db/
│   └── schema.sql                    # ← 끝에 ALTER TABLE 4 줄 + 인덱스 2 줄
├── indicators/
│   ├── compute/
│   │   └── volume.py                 # ← 신규
│   ├── load.py                       # ← close, volume SELECT 추가
│   ├── store.py                      # ← PHASE_A_COLUMNS_* 에 컬럼 추가
│   └── modes.py                      # ← _process_ticker_daily/weekly volume 통합
└── (나머지 변경 없음)

tests/
└── test_indicators_volume.py         # ← 신규
```

---

## Task 1: DB 스키마 — ALTER TABLE 컬럼 추가

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (append)

- [ ] **Step 1: `schema.sql` 끝에 추가**

```sql

-- ====== Indicators V2: Volume (#2-V2) ======

ALTER TABLE daily_indicators
    ADD COLUMN IF NOT EXISTS volume                    NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS avg_volume_50d            NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS volume_ratio_50d          NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS pocket_pivot_flag         BOOLEAN,
    ADD COLUMN IF NOT EXISTS volume_dry_up_flag        BOOLEAN,
    ADD COLUMN IF NOT EXISTS up_down_volume_ratio_50d  NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS distribution_day_flag     BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_daily_indicators_pocket_pivot
    ON daily_indicators(date) WHERE pocket_pivot_flag = TRUE;
CREATE INDEX IF NOT EXISTS idx_daily_indicators_distribution
    ON daily_indicators(date) WHERE distribution_day_flag = TRUE;

ALTER TABLE weekly_indicators
    ADD COLUMN IF NOT EXISTS volume                    NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS avg_volume_10w            NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS volume_ratio_10w          NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS up_down_volume_ratio_10w  NUMERIC(10,4);
```

- [ ] **Step 2: 두 DB 에 적용**

```bash
psql postgresql://localhost/kr_pipeline -f kr_pipeline/db/schema.sql
psql postgresql://localhost/kr_test -f kr_pipeline/db/schema.sql
```

Expected: `ALTER TABLE`, `CREATE INDEX` 출력, 에러 없음.

- [ ] **Step 3: 검증**

```bash
psql postgresql://localhost/kr_pipeline -c "\d daily_indicators" | grep -E "volume|pocket|distribution"
psql postgresql://localhost/kr_pipeline -c "\d weekly_indicators" | grep -E "volume"
```

Expected: 일봉에 volume/avg_volume_50d/volume_ratio_50d/pocket_pivot_flag/volume_dry_up_flag/up_down_volume_ratio_50d/distribution_day_flag 컬럼 보임. 주봉에 volume/avg_volume_10w/volume_ratio_10w/up_down_volume_ratio_10w.

- [ ] **Step 4: 기존 테스트 회귀**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: 117 passed (no regression, schema 만 변경).

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/db/schema.sql
git commit -m "feat(indicators-v2): DB 스키마 - 거래량 컬럼 추가"
```

---

## Task 2: compute/volume.py + 단위 테스트 (TDD)

**Files:**
- Create: `kr_pipeline/indicators/compute/volume.py`
- Create: `tests/test_indicators_volume.py`

- [ ] **Step 1: 테스트 작성 (~14)**

```python
# tests/test_indicators_volume.py
import pandas as pd
import numpy as np
import pytest
from kr_pipeline.indicators.compute.volume import (
    split_adjusted_volume,
    avg_volume,
    volume_ratio,
    pocket_pivot,
    volume_dry_up,
    up_down_volume_ratio,
    distribution_day,
)


# split-adjusted volume
def test_split_adjusted_volume_basic():
    """split_factor = close / adj_close"""
    close = pd.Series([100.0, 100.0, 50.0])    # 2:1 분할 후 50
    adj_close = pd.Series([50.0, 50.0, 50.0])  # back-adjusted (all 50)
    volume = pd.Series([1000.0, 1000.0, 2000.0])
    result = split_adjusted_volume(volume, close, adj_close)
    # 분할 전: split_factor=2 → adj_vol = 1000*2 = 2000
    # 분할 후: split_factor=1 → adj_vol = 2000*1 = 2000
    assert result.iloc[0] == 2000.0
    assert result.iloc[1] == 2000.0
    assert result.iloc[2] == 2000.0   # 연속


def test_split_adjusted_volume_no_split():
    """close == adj_close → split_factor=1, adj_vol = volume"""
    close = pd.Series([100.0, 110.0, 120.0])
    adj_close = pd.Series([100.0, 110.0, 120.0])
    volume = pd.Series([1000.0, 1100.0, 1200.0])
    result = split_adjusted_volume(volume, close, adj_close)
    assert list(result) == [1000.0, 1100.0, 1200.0]


# avg_volume / volume_ratio
def test_avg_volume_basic():
    """50일 rolling mean"""
    v = pd.Series([100.0] * 60)
    result = avg_volume(v, window=50)
    assert pd.isna(result.iloc[48])
    assert result.iloc[49] == 100.0
    assert result.iloc[59] == 100.0


def test_avg_volume_insufficient_history_returns_nan():
    v = pd.Series([100.0] * 30)
    result = avg_volume(v, window=50)
    assert result.isna().all()


def test_volume_ratio_basic():
    """ratio = volume / avg"""
    v = pd.Series([100.0, 200.0, 300.0])
    avg = pd.Series([100.0, 100.0, 100.0])
    result = volume_ratio(v, avg)
    assert list(result) == [1.0, 2.0, 3.0]


# pocket pivot
def test_pocket_pivot_basic():
    """is_up_day AND vol >= max(past 10 down vol) AND close > sma_50"""
    # 3일: 모두 상승, sma_50 < close, volume 충분
    adj_close = pd.Series([100.0, 110.0, 120.0])
    is_up_day = pd.Series([True, True, True])
    sma_50 = pd.Series([90.0, 90.0, 90.0])     # 모두 close 보다 낮음
    adj_volume = pd.Series([1500.0, 1500.0, 1500.0])
    # 지난 10일 down day 없음 → max=NaN → False (climax suspect)
    result = pocket_pivot(is_up_day, adj_volume, sma_50, adj_close, lookback=10)
    # 모두 NaN (down max = NaN → comparison = NaN → 우리 정의에서 False)
    # 함수는 NaN 또는 False 반환 (구현 정책)
    for r in result:
        assert r != True


def test_pocket_pivot_with_prior_down_day():
    """down day 가 있는 경우 정상 동작"""
    # 6 days: down, up, up, up, down, up
    # idx 5 (up day): past 10 down vol max = max(vol[0]=1000, vol[4]=800) = 1000
    # adj_volume[5] = 1500 → 1500 >= 1000 → True (다른 조건 OK 가정)
    adj_close = pd.Series([100.0, 105.0, 110.0, 115.0, 110.0, 115.0])
    is_up_day = pd.Series([False, True, True, True, False, True])
    sma_50 = pd.Series([90.0] * 6)
    adj_volume = pd.Series([1000.0, 1100.0, 1200.0, 1300.0, 800.0, 1500.0])
    result = pocket_pivot(is_up_day, adj_volume, sma_50, adj_close, lookback=10)
    assert result.iloc[5] == True


def test_pocket_pivot_fails_below_sma_50():
    """close <= sma_50 → False (책 필수 조건)"""
    adj_close = pd.Series([100.0, 105.0, 110.0, 95.0])
    is_up_day = pd.Series([False, True, True, False])    # idx 3 down day
    sma_50 = pd.Series([100.0, 100.0, 100.0, 100.0])     # all = 100
    adj_volume = pd.Series([1000.0, 500.0, 500.0, 800.0])
    # idx 1 up day, adj_close=105 > sma_50=100 → 통과
    # idx 2 up day, adj_close=110 > sma_50=100 → 통과
    # 다만 down vol max 가 idx 0 (1000) → 500 >= 1000 False
    result = pocket_pivot(is_up_day, adj_volume, sma_50, adj_close, lookback=10)
    # 별 의미 없음, 다음 테스트로
    
    # 명확한 below-sma case
    adj_close2 = pd.Series([95.0, 92.0, 96.0, 98.0])
    is_up_day2 = pd.Series([False, False, True, True])   # idx 2,3 up
    sma_50_2 = pd.Series([100.0] * 4)                    # 모두 close 보다 위
    adj_volume2 = pd.Series([1500.0, 1500.0, 1500.0, 1500.0])
    result2 = pocket_pivot(is_up_day2, adj_volume2, sma_50_2, adj_close2, lookback=10)
    # idx 2: adj_close=96, sma_50=100 → close<sma → False (regardless of volume)
    assert result2.iloc[2] != True
    assert result2.iloc[3] != True


def test_pocket_pivot_uses_gte_not_gt():
    """vol == max → True (>=, per book 원문)"""
    # idx 4: down vol max = 1000 (from idx 0). adj_volume[4] = 1000 정확히 같음
    adj_close = pd.Series([100.0, 105.0, 110.0, 115.0, 120.0])
    is_up_day = pd.Series([False, True, True, True, True])
    sma_50 = pd.Series([90.0] * 5)
    adj_volume = pd.Series([1000.0, 500.0, 500.0, 500.0, 1000.0])
    result = pocket_pivot(is_up_day, adj_volume, sma_50, adj_close, lookback=10)
    # idx 4: vol=1000, down max=1000 → True (>=)
    assert result.iloc[4] == True


# volume dry up
def test_volume_dry_up_threshold_50pct():
    """adj_volume < avg_volume * 0.5"""
    adj_volume = pd.Series([400.0, 500.0, 600.0])
    avg_volume_50 = pd.Series([1000.0, 1000.0, 1000.0])
    result = volume_dry_up(adj_volume, avg_volume_50, threshold=0.5)
    assert result.iloc[0] == True   # 400 < 500
    assert result.iloc[1] == False  # 500 not < 500
    assert result.iloc[2] == False  # 600 > 500


# up/down volume ratio
def test_up_down_volume_ratio_basic():
    """5 days, 3 up (vol 100+200+300=600), 2 down (vol 50+150=200) → 600/200=3.0"""
    adj_volume = pd.Series([100.0, 50.0, 200.0, 150.0, 300.0])
    is_up_day = pd.Series([True, False, True, False, True])
    is_down_day = pd.Series([False, True, False, True, False])
    result = up_down_volume_ratio(adj_volume, is_up_day, is_down_day, window=5)
    assert pd.isna(result.iloc[3])
    assert result.iloc[4] == 3.0


def test_up_down_volume_ratio_zero_division():
    """모두 up → down_vol=0 → NaN"""
    adj_volume = pd.Series([100.0] * 5)
    is_up_day = pd.Series([True] * 5)
    is_down_day = pd.Series([False] * 5)
    result = up_down_volume_ratio(adj_volume, is_up_day, is_down_day, window=5)
    assert pd.isna(result.iloc[4])


# distribution day
def test_distribution_day_basic():
    """is_down_day AND adj_volume > avg * 1.25"""
    is_down_day = pd.Series([False, True, True, False])
    adj_volume = pd.Series([1000.0, 1300.0, 1100.0, 1500.0])
    avg_volume_50 = pd.Series([1000.0] * 4)
    result = distribution_day(is_down_day, adj_volume, avg_volume_50, threshold=1.25)
    assert result.iloc[0] == False   # not down day
    assert result.iloc[1] == True    # down + 1300 > 1250
    assert result.iloc[2] == False   # down + 1100 not > 1250
    assert result.iloc[3] == False   # not down


def test_distribution_day_threshold_1_25x():
    """경계 case: vol == 1.25x → False (> not >=)"""
    is_down_day = pd.Series([True, True])
    adj_volume = pd.Series([1250.0, 1250.001])
    avg_volume_50 = pd.Series([1000.0, 1000.0])
    result = distribution_day(is_down_day, adj_volume, avg_volume_50, threshold=1.25)
    assert result.iloc[0] == False    # exactly 1.25x → not >
    assert result.iloc[1] == True     # slightly above
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_indicators_volume.py -v`
Expected: ImportError.

- [ ] **Step 3: `compute/volume.py` 구현**

```python
"""거래량 지표 (split-adjusted) 순수 함수.

모든 함수의 입력은 split-adjusted volume (adj_volume) 기준.
adj_volume = volume * (close / adj_close) 로 사전 계산.
"""
import numpy as np
import pandas as pd


def split_adjusted_volume(volume: pd.Series, close: pd.Series, adj_close: pd.Series) -> pd.Series:
    """split-adjusted volume = volume * (close / adj_close).
    
    분할 전: close > adj_close → factor > 1 → adj_volume 증가 (post-split scale)
    분할 후: close == adj_close → factor = 1 → adj_volume = volume
    """
    split_factor = close / adj_close
    return volume * split_factor


def avg_volume(adj_volume: pd.Series, window: int) -> pd.Series:
    """rolling mean. window 미만 NaN."""
    return adj_volume.rolling(window=window, min_periods=window).mean()


def volume_ratio(adj_volume: pd.Series, avg_volume_series: pd.Series) -> pd.Series:
    """volume / avg. avg=0 / NaN → NaN."""
    avg_safe = avg_volume_series.where(avg_volume_series > 0)
    return adj_volume / avg_safe


def pocket_pivot(
    is_up_day: pd.Series,
    adj_volume: pd.Series,
    sma_50: pd.Series,
    adj_close: pd.Series,
    lookback: int = 10,
) -> pd.Series:
    """Morales & Kacher PP:
      (1) 상승일
      (2) 오늘 거래량 >= 지난 lookback 일 중 하락일들의 거래량 최대값
      (3) 종가 > sma_50
    
    Edge case: 지난 lookback 일에 down day 없으면 max=NaN → False (climax suspect).
    """
    # 하락일에만 volume 값을 유지, 다른 날은 NaN
    down_day_mask = ~is_up_day & adj_volume.notna()    # 단순화: not up = down or flat. 정확히 down 만 원하면 별도 인자
    # 우리 use case: is_up_day=True for up, False for down or flat. flat day 거래량도 보수적으로 max 후보에 포함 가능
    # 하지만 책 원문은 "down day" 명시 → is_up_day=False AND adj_close < prev_adj_close
    # 호출자가 is_down_day 도 제공하는 게 깔끔. 본 구현은 is_up_day 만 받음 → not is_up_day 사용
    
    down_day_vols = adj_volume.where(~is_up_day)
    # shift(1): 어제까지의 lookback (오늘 거래량은 비교 대상이지 max 후보가 아님)
    past_down_max = down_day_vols.rolling(window=lookback, min_periods=1).max().shift(1)
    
    # 조건 평가
    cond_up = is_up_day
    cond_vol = adj_volume >= past_down_max
    cond_sma = adj_close > sma_50
    
    return (cond_up & cond_vol & cond_sma).fillna(False)


def volume_dry_up(
    adj_volume: pd.Series,
    avg_volume_series: pd.Series,
    threshold: float = 0.5,
) -> pd.Series:
    """adj_volume < avg_volume * threshold.
    
    threshold 0.5 는 community standard (책 명시 아님).
    """
    return adj_volume < (avg_volume_series * threshold)


def up_down_volume_ratio(
    adj_volume: pd.Series,
    is_up_day: pd.Series,
    is_down_day: pd.Series,
    window: int,
) -> pd.Series:
    """up_vol_sum / down_vol_sum over rolling window.
    
    down_vol_sum=0 (window 안에 down day 없음) → NaN.
    O'Neil A/D rating 의 simplification (proprietary 공식과는 다름).
    """
    up_vol = adj_volume.where(is_up_day, 0).rolling(window=window, min_periods=window).sum()
    down_vol = adj_volume.where(is_down_day, 0).rolling(window=window, min_periods=window).sum()
    return up_vol / down_vol.where(down_vol > 0)


def distribution_day(
    is_down_day: pd.Series,
    adj_volume: pd.Series,
    avg_volume_series: pd.Series,
    threshold: float = 1.25,
) -> pd.Series:
    """is_down_day AND adj_volume > avg_volume * threshold.
    
    1.25 는 IBD/community 임계 (책 명시 아님).
    종목 레벨에서 단순 is_down_day 사용. 시장 레벨 -0.2% 임계는 #4 에서 별도 처리.
    """
    return (is_down_day & (adj_volume > (avg_volume_series * threshold))).fillna(False)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_indicators_volume.py -v`
Expected: 14 passed (or whatever count actually written, all pass).

- [ ] **Step 5: 전체 회귀 확인**

Run: `uv run pytest 2>&1 | tail -3`
Expected: ~131 passed (117 + 14).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/indicators/compute/volume.py tests/test_indicators_volume.py
git commit -m "feat(indicators-v2): compute/volume - 거래량 지표 7 함수 + 14 tests"
```

---

## Task 3: load.py 업데이트 — close, volume 가져오기

**Files:**
- Modify: `kr_pipeline/indicators/load.py`

기존 `load_daily_prices` 는 `(date, adj_close)` 만 SELECT. V2 는 split adjustment 위해 `close`, `volume` 도 필요.

- [ ] **Step 1: `load_daily_prices` 수정**

Read current `kr_pipeline/indicators/load.py`. Modify `load_daily_prices` 의 SQL 을:

```python
def load_daily_prices(
    conn: Connection,
    ticker: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """한 종목의 일봉 (date, adj_close, close, volume).
    
    V2: split-adjusted volume 계산 위해 close, volume 도 가져옴.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, adj_close, close, volume
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
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
    return df
```

- [ ] **Step 2: `load_weekly_prices` 수정 (동일 패턴)**

```python
def load_weekly_prices(conn: Connection, ticker: str, start: date, end: date) -> pd.DataFrame:
    """한 종목의 주봉 (date, adj_close, close, volume). V2: close, volume 추가."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT week_end_date AS date, adj_close, close, volume
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
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
    return df
```

다른 함수 (`load_index_daily`, `load_weekly_index`, `load_active_tickers_with_market`, `get_daily_prices_min_date`, `get_weekly_prices_min_date`) 는 변경 없음.

- [ ] **Step 3: 임포트 확인**

```bash
uv run python -c "from kr_pipeline.indicators.load import load_daily_prices, load_weekly_prices; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: 회귀 확인**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: ~131 passed.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/indicators/load.py
git commit -m "feat(indicators-v2): load - close, volume SELECT 추가"
```

---

## Task 4: store.py 업데이트 — 새 컬럼 추가

**Files:**
- Modify: `kr_pipeline/indicators/store.py`

`PHASE_A_COLUMNS_DAILY` 와 `PHASE_A_COLUMNS_WEEKLY` 에 V2 컬럼 추가.

- [ ] **Step 1: `PHASE_A_COLUMNS_DAILY` 끝에 추가**

Read `kr_pipeline/indicators/store.py`. Find `PHASE_A_COLUMNS_DAILY = [...]` list. After the last item (currently `"minervini_c7"`), add 7 V2 columns. Final list:

```python
PHASE_A_COLUMNS_DAILY = [
    "ticker", "date", "adj_close",
    "sma_10", "sma_21", "sma_50", "sma_150", "sma_200",
    "w52_high", "w52_low", "pct_from_52w_high", "pct_from_52w_low",
    "rs_line", "rs_line_52w_high", "rs_line_52w_high_date",
    "rs_line_at_52w_high", "rs_line_uptrend_6w", "rs_line_uptrend_13w",
    "rs_line_in_decline_7m",
    "minervini_c1", "minervini_c2", "minervini_c3",
    "minervini_c4", "minervini_c5", "minervini_c6", "minervini_c7",
    # V2: 거래량 지표
    "volume",
    "avg_volume_50d",
    "volume_ratio_50d",
    "pocket_pivot_flag",
    "volume_dry_up_flag",
    "up_down_volume_ratio_50d",
    "distribution_day_flag",
]
```

- [ ] **Step 2: `PHASE_A_COLUMNS_WEEKLY` 끝에 추가**

```python
PHASE_A_COLUMNS_WEEKLY = [
    "ticker", "week_end_date", "adj_close",
    "sma_10w", "sma_30w", "sma_40w",
    "w52_high", "w52_low", "pct_from_52w_high", "pct_from_52w_low",
    "rs_line", "rs_line_52w_high", "rs_line_52w_high_date",
    "rs_line_at_52w_high", "rs_line_uptrend_6w", "rs_line_uptrend_13w",
    "rs_line_in_decline_7m",
    "minervini_c1", "minervini_c2", "minervini_c3",
    "minervini_c4", "minervini_c5", "minervini_c6", "minervini_c7",
    # V2: 거래량 지표
    "volume",
    "avg_volume_10w",
    "volume_ratio_10w",
    "up_down_volume_ratio_10w",
]
```

`upsert_daily_indicators_phase_a` 와 `upsert_weekly_indicators_phase_a` 자체는 컬럼 리스트를 동적으로 사용하므로 변경 불필요. 다만 `r.get(c)` 호출 시 row dict 에 새 키 없으면 `None` 반환 → 안전. (modes.py 가 이 키들을 채워 줄 것).

- [ ] **Step 3: 회귀 확인**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: ~131 passed. 기존 store 테스트는 V2 컬럼이 row dict 에 없으면 None 으로 들어가야 통과해야 함.

기존 store 테스트가 V2 컬럼을 row dict 에 안 넣고 호출 → 함수가 `r.get(c)` 로 None 받음 → INSERT 시 V2 컬럼 NULL → 통과. 만약 테스트 실패하면 `r.get(c)` 패턴이 정상인지 확인.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/indicators/store.py
git commit -m "feat(indicators-v2): store - PHASE_A_COLUMNS 에 거래량 컬럼 추가"
```

---

## Task 5: modes.py 통합 — Phase A 에 volume 계산 추가

**Files:**
- Modify: `kr_pipeline/indicators/modes.py`

`_process_ticker_daily` 와 `_process_ticker_weekly` 에 거래량 계산 통합.

- [ ] **Step 1: `_process_ticker_daily` 수정**

Read `kr_pipeline/indicators/modes.py`. Find `_process_ticker_daily` function. 

**임포트 추가** (파일 상단 다른 compute import 와 함께):

```python
from kr_pipeline.indicators.compute.volume import (
    split_adjusted_volume, avg_volume, volume_ratio,
    pocket_pivot, volume_dry_up, up_down_volume_ratio, distribution_day,
)
```

**기존 `_process_ticker_daily` 내부에서**, `adj_close = df["adj_close"]` 라인 다음에 split-adjusted volume 계산 추가:

```python
adj_close = df["adj_close"]

# V2: split-adjusted volume + 거래량 지표 계산
close = df["close"]
volume_raw = df["volume"]
adj_volume = split_adjusted_volume(volume_raw, close, adj_close)
avg_vol_50 = avg_volume(adj_volume, window=50)
vol_ratio_50 = volume_ratio(adj_volume, avg_vol_50)

is_up = adj_close > adj_close.shift(1)
is_down = adj_close < adj_close.shift(1)

# SMAs 계산 후에 pp 사용 (sma_50 필요). 기존 코드에서 sma_50 = sma(adj_close, 50) 가 있음.
# pp 는 sma_50 계산 다음에 위치시킴.
```

기존 코드의 SMA 블록 다음에 (sma_50 정의 후) pocket_pivot 등 추가:

```python
# 기존: sma_10, sma_21, sma_50, sma_150, sma_200, w52h, w52l, ...
sma_10 = sma(adj_close, 10)
sma_21 = sma(adj_close, 21)
sma_50 = sma(adj_close, 50)
sma_150 = sma(adj_close, 150)
sma_200 = sma(adj_close, 200)
# ... 기존 코드 ...

# V2 거래량 지표 (sma_50 사용)
pp_flag = pocket_pivot(is_up, adj_volume, sma_50, adj_close, lookback=10)
vdu_flag = volume_dry_up(adj_volume, avg_vol_50, threshold=0.5)
ud_ratio_50 = up_down_volume_ratio(adj_volume, is_up, is_down, window=50)
dist_flag = distribution_day(is_down, adj_volume, avg_vol_50, threshold=1.25)
```

**row dict 생성 부분** (for d in df.index: row = {...}) 에 V2 키들 추가:

```python
row = {
    # ... 기존 모든 키들 ...
    "minervini_c7": _as_bool(mn["minervini_c7"].loc[d]),
    # V2 거래량 지표
    "volume": _as_float(adj_volume.loc[d]),
    "avg_volume_50d": _as_float(avg_vol_50.loc[d]),
    "volume_ratio_50d": _as_float(vol_ratio_50.loc[d]),
    "pocket_pivot_flag": _as_bool(pp_flag.loc[d]),
    "volume_dry_up_flag": _as_bool(vdu_flag.loc[d]),
    "up_down_volume_ratio_50d": _as_float(ud_ratio_50.loc[d]),
    "distribution_day_flag": _as_bool(dist_flag.loc[d]),
}
```

- [ ] **Step 2: `_process_ticker_weekly` 수정 (동일 패턴, 주봉 window=10)**

같은 패턴으로 weekly 도 통합. 주봉은 pp/vdu/dist 제외, 3 지표만:

```python
adj_close = df["adj_close"]
close = df["close"]
volume_raw = df["volume"]
adj_volume = split_adjusted_volume(volume_raw, close, adj_close)
avg_vol_10w = avg_volume(adj_volume, window=10)
vol_ratio_10w = volume_ratio(adj_volume, avg_vol_10w)

is_up = adj_close > adj_close.shift(1)
is_down = adj_close < adj_close.shift(1)
ud_ratio_10w = up_down_volume_ratio(adj_volume, is_up, is_down, window=10)
```

row dict 추가:
```python
"volume": _as_float(adj_volume.loc[d]),
"avg_volume_10w": _as_float(avg_vol_10w.loc[d]),
"volume_ratio_10w": _as_float(vol_ratio_10w.loc[d]),
"up_down_volume_ratio_10w": _as_float(ud_ratio_10w.loc[d]),
```

- [ ] **Step 3: 회귀 테스트**

```bash
uv run pytest 2>&1 | tail -3
```
Expected: ~131 passed. 기존 integration test 가 새 컬럼 검증 없이도 통과해야 함.

- [ ] **Step 4: 통합 테스트 확장 (선택)**

`tests/test_indicators_integration.py::test_daily_backfill_end_to_end` 마지막 assert 부분에 추가:

```python
# V2 컬럼 검증
cur.execute("""
    SELECT volume, avg_volume_50d, volume_ratio_50d 
      FROM daily_indicators 
     WHERE ticker = 'INDTEST1' AND volume IS NOT NULL
     ORDER BY date DESC LIMIT 1
""")
row = cur.fetchone()
assert row is not None  # 적어도 한 행은 volume 채워짐
assert row[0] > 0       # adj_volume positive
```

- [ ] **Step 5: 라이브 일봉 스모크**

```bash
uv run python -m kr_pipeline.indicators --target=daily --mode=backfill --limit-tickers=10 2>&1 | tail -10
```
Expected: 정상 종료. 

DB 검증:
```bash
psql postgresql://localhost/kr_pipeline -c "
SELECT COUNT(*) total,
       COUNT(*) FILTER (WHERE volume IS NOT NULL) with_volume,
       COUNT(*) FILTER (WHERE pocket_pivot_flag = TRUE) pp_count,
       COUNT(*) FILTER (WHERE distribution_day_flag = TRUE) dist_count
  FROM daily_indicators
"
psql postgresql://localhost/kr_pipeline -c "
SELECT ticker, date, volume, avg_volume_50d, volume_ratio_50d, pocket_pivot_flag
  FROM daily_indicators 
 WHERE volume IS NOT NULL 
 ORDER BY date DESC LIMIT 5
"
```

Expected: 일부 행 (lookback 통과한 종목) 에서 volume / avg_volume 등 값 보임. 데이터 양이 적어서 (140 일봉 행) avg_volume_50d 는 NULL 일 수도 있지만 volume 자체는 모든 행 NOT NULL.

- [ ] **Step 6: 라이브 주봉 스모크**

```bash
uv run python -m kr_pipeline.indicators --target=weekly --mode=backfill --limit-tickers=10 2>&1 | tail -10
```

DB 검증:
```bash
psql postgresql://localhost/kr_pipeline -c "
SELECT ticker, week_end_date, volume, avg_volume_10w, volume_ratio_10w
  FROM weekly_indicators 
 WHERE volume IS NOT NULL 
 ORDER BY week_end_date DESC LIMIT 5
"
```

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/indicators/modes.py tests/test_indicators_integration.py
git commit -m "feat(indicators-v2): modes - Phase A 에 거래량 지표 통합"
```

---

## Task 6: README 업데이트 + 최종 Goal State

**Files:**
- Modify: `README.md` (운영 점검 쿼리 추가)

- [ ] **Step 1: `README.md` 운영 점검 쿼리 SQL 블록 끝에 추가**

```sql

-- 오늘의 Pocket Pivot 종목 (V2)
SELECT i.date, s.ticker, s.name, s.sector, i.volume_ratio_50d, i.rs_rating
  FROM daily_indicators i
  JOIN stocks s USING (ticker)
 WHERE i.date = (SELECT MAX(date) FROM daily_indicators)
   AND i.pocket_pivot_flag = TRUE
 ORDER BY i.volume_ratio_50d DESC;

-- 최근 25 영업일 시장 distribution day 누적 (#4 시장 추세 판정 입력)
SELECT date, 
       COUNT(*) FILTER (WHERE distribution_day_flag = TRUE) AS distribution_count
  FROM daily_indicators
 WHERE date >= (SELECT MAX(date) FROM daily_indicators) - INTERVAL '40 days'
 GROUP BY date
 ORDER BY date DESC LIMIT 25;

-- Volume dry-up + RS Rating 강세 (base 형성 후보)
SELECT i.date, s.ticker, s.name, i.volume_ratio_50d, i.rs_rating
  FROM daily_indicators i
  JOIN stocks s USING (ticker)
 WHERE i.date = (SELECT MAX(date) FROM daily_indicators)
   AND i.volume_dry_up_flag = TRUE
   AND i.rs_rating >= 70
 ORDER BY i.rs_rating DESC LIMIT 20;
```

- [ ] **Step 2: 최종 Goal State 검증**

```bash
# 전체 테스트
uv run pytest 2>&1 | tail -5
```
Expected: ~131 passed.

```bash
# 통합 테스트만
uv run pytest -m integration -v 2>&1 | tail -10
```
Expected: 6 passed.

```bash
# 라이브 일봉 backfill 재실행
uv run python -m kr_pipeline.indicators --target=daily --mode=backfill --limit-tickers=10 2>&1 | tail -5
```
Expected: 정상 종료.

```bash
# DB 최종 상태
psql postgresql://localhost/kr_pipeline -c "
SELECT 'daily_indicators total' AS m, COUNT(*) FROM daily_indicators
UNION ALL SELECT 'with volume', COUNT(*) FROM daily_indicators WHERE volume IS NOT NULL
UNION ALL SELECT 'weekly_indicators total', COUNT(*) FROM weekly_indicators
UNION ALL SELECT 'with volume', COUNT(*) FROM weekly_indicators WHERE volume IS NOT NULL
"
```

```bash
# git 상태
git status
```
Expected: clean.

- [ ] **Step 3: README 커밋**

```bash
git add README.md
git commit -m "docs(indicators-v2): 운영 쿼리에 거래량 지표 추가"
```

- [ ] **Step 4: 종료 보고**

```
지표 V2 (거래량 지표) 완료.
- daily +6 컬럼 / weekly +3 컬럼 추가
- ~131 passed (117 + 14 new)
- compute/volume.py 단일 신규 파일
- 라이브 backfill 스모크 통과
- 다음: #3 (UI) 또는 #4 (자동 분석)
```

---

## Self-Review

- ✅ Spec §2 split-adjustment 컨벤션 — Task 2 의 `split_adjusted_volume` 함수 정확히 구현
- ✅ Spec §4 컬럼 추가 — Task 1 ALTER TABLE 매핑
- ✅ Spec §5 계산식 — Task 2 compute/volume.py 각 함수 verbatim
- ✅ Spec §7 코드 구조 — Task 3 load.py, Task 4 store.py, Task 5 modes.py 명확히 분리
- ✅ Spec §10 테스팅 — Task 2 ~14 단위 + Task 5 integration assertion 추가
- ⚠️ Placeholder 없음
- ⚠️ 타입 일관성:
  - 모든 compute 함수가 `pd.Series` 입출력
  - `_as_float`, `_as_bool` 변환 일관 (#2 와 동일)
  - PHASE_A_COLUMNS 추가 항목 schema.sql 컬럼명과 1:1 매칭
- ⚠️ 알려진 트레이드오프:
  - pocket_pivot 에 down day 식별이 `~is_up_day` (flat day 도 포함) — 정확히 down 만 원하면 호출자가 is_down_day 도 전달해야. 본 V2 는 is_up_day 만 사용 (단순화). flat day 거래량이 max 후보가 되어 PP 신호가 더 보수적으로 됨 — 안전 방향.
  - 분할 발생 주봉의 mid-week split 케이스 → 본 V2 보정 공식 작은 오차 가능 (spec §2 명시)

자율 실행자는 위 ⚠️ 인지하고 진행할 것.
