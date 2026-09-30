# volume_regime PR-2 (Q-5c 1·3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 봉(daily_prices·index_daily·weekly_prices)에 거래량 정의 `volume_regime` 을 기록하고, 판정 행 5테이블의 표지를 문자열에서 전용 컬럼 `volume_regime_flag` 로 옮기며, 경계일(09-25→09-28) 전일 대비 거래량 비교(분배일·FTD)를 무효화한다. 판정 규칙·숫자 변경 0.

**Architecture:** 봉 regime 은 날짜의 함수 → 저장 SQL 의 `CASE WHEN date >= %(boundary)s` 로 기록(튜플 계약 불변), 주봉은 주의 월요일/금요일과 경계 비교로 regular/extended/mixed. 판정 행 flag 는 PR-2 에서 "as_of ≥ 경계 → 'mixed'"(현행 표지 범위와 동일), PR-3 에서 창 유도로 축소. 이관은 멱등 SQL 스크립트 1개(양쪽 DB).

**Tech Stack:** Python 3 · psycopg 3 · pandas · pytest(`db` 픽스처, kr_test 리셋) · FastAPI · React/TypeScript · vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-volume-regime-design.md`

## Global Constraints

- 작업 위치: worktree `.claude/worktrees/vr-spec`, 브랜치 `issue207-volume-regime-spec`(origin/main 기준). 커밋 전 `git branch --show-current`. **`git add` 는 명시 경로만.** co-author 트레일러 금지(사용자 CLAUDE.md).
- `uv run pytest tests/` 판정 전 `pgrep -f "pytest tests/"`. 기대: 실패 0, 1 skipped, 1 deselected.
- schema.sql 변경은 kr_test(conftest 자동)·kr_pipeline(수동 psql, Task 6) 양쪽.
- 외부 접촉 0(KRX·Naver·Toss). 테스트는 `db` 픽스처 + monkeypatch.
- 경계 상수 = `kr_pipeline/common/data_regimes.py` `VOLUME_REGIME_BOUNDARY = date(2026, 9, 28)`(기존 `VOLUME_REGIME_UNVERIFIED_FROM` 개명, 구 이름은 별칭 유지). 문자열 `'regular' | 'extended' | 'mixed'`, flag `'mixed' | NULL`.
- thresholds.py 변경 0. checklist 이력 1줄(Task 8).

---

## 파일 구조

| 경로 | 책임 |
|---|---|
| `kr_pipeline/common/data_regimes.py` (modify) | 경계 상수 개명·별칭, `regime_for_date(d)`, `regime_flag_for_as_of(as_of)`(PR-2 규칙), `with_volume_regime` 삭제 |
| `kr_pipeline/db/schema.sql` (append) | 8 ALTER |
| `kr_pipeline/ohlcv/store.py` (modify) | daily_prices·index_daily upsert SQL 에 `volume_regime` CASE |
| `kr_pipeline/weekly/store.py` (modify) | weekly_prices upsert SQL 에 CASE(regular/extended/mixed) |
| `kr_pipeline/market_context/load.py`·`compute/distribution_day.py`·`compute/follow_through.py`·`modes.py` (modify) | regime 로드·경계 쌍 skip·notes |
| `kr_pipeline/llm_runner/store.py` (modify) | 3 insert: 문자열 표지 → `volume_regime_flag` |
| `kr_pipeline/trade_management/runner.py` (modify) | climax/decline insert 에 flag |
| `scripts/sql/issue207_volume_regime_migrate.sql` (new) | 소급 채움·문자열 제거·flag 이관(멱등) |
| `api/routers/signals.py`·`web/src/lib/types.ts`·`web/src/pages/SignalsPage.tsx`·`web/src/components/panels/EntrySignalCard.tsx` (modify), `web/src/lib/warningLabels.ts` (delete) | flag 노출·배지 |
| `tests/test_volume_regime_bars.py` (new) · `tests/test_volume_regime_tag.py` (rewrite) · `tests/test_market_context_boundary.py` (new) | 테스트 |
| `docs/superpowers/threshold-change-checklist.md` (append) | 이력 |

---

### Task 1: 상수·헬퍼·schema

**Files:**
- Modify: `kr_pipeline/common/data_regimes.py`
- Modify: `kr_pipeline/db/schema.sql` (append)
- Test: `tests/test_volume_regime_bars.py` (new)

**Interfaces:**
- Produces:
  ```python
  VOLUME_REGIME_BOUNDARY: date = date(2026, 9, 28)
  VOLUME_REGIME_UNVERIFIED_FROM = VOLUME_REGIME_BOUNDARY        # 별칭(PR #217 호환)
  REGIME_REGULAR, REGIME_EXTENDED, REGIME_MIXED = "regular", "extended", "mixed"
  FLAG_MIXED = "mixed"
  def regime_for_date(d: date) -> str                           # regular | extended
  def regime_flag_for_as_of(as_of) -> str | None                # PR-2 규칙: as_of ≥ 경계 → "mixed", 아니면 None (datetime/ISO 허용)
  ```
- `volume_regime_warnings`·`with_volume_regime`·`VOLUME_REGIME_TAG` 는 **삭제**(Task 5 에서 소비처 제거 후 — 이 Task 에서는 유지, Task 5 에서 삭제).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_volume_regime_bars.py
"""#207 회신 21 Q-5c 1 — 봉 단위 volume_regime + 판정 행 flag(PR-2 규칙)."""
from datetime import date, datetime, timedelta, timezone

from kr_pipeline.common.data_regimes import (
    FLAG_MIXED, REGIME_EXTENDED, REGIME_MIXED, REGIME_REGULAR, VOLUME_REGIME_BOUNDARY,
    VOLUME_REGIME_UNVERIFIED_FROM, regime_flag_for_as_of, regime_for_date,
)

B = VOLUME_REGIME_BOUNDARY


def test_constants_and_alias():
    assert VOLUME_REGIME_UNVERIFIED_FROM == B
    assert (REGIME_REGULAR, REGIME_EXTENDED, REGIME_MIXED, FLAG_MIXED) == ("regular", "extended", "mixed", "mixed")


def test_regime_for_date_boundary():
    assert regime_for_date(B - timedelta(days=1)) == "regular"
    assert regime_for_date(B) == "extended"


def test_regime_flag_for_as_of_pr2_rule():
    assert regime_flag_for_as_of(None) is None
    assert regime_flag_for_as_of(B - timedelta(days=1)) is None
    assert regime_flag_for_as_of(B) == "mixed"
    assert regime_flag_for_as_of(datetime(B.year, B.month, B.day, 9, tzinfo=timezone.utc)) == "mixed"
    assert regime_flag_for_as_of(B.isoformat()) == "mixed"


def test_schema_columns_exist(db):
    with db.cursor() as cur:
        for table in ("daily_prices", "index_daily", "weekly_prices"):
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name='volume_regime'", (table,))
            assert cur.fetchone(), table
        for table in ("weekly_classification", "trigger_evaluation_log", "entry_params",
                      "position_climax_evaluations", "position_decline_evaluations"):
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name='volume_regime_flag'", (table,))
            assert cur.fetchone(), table
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_volume_regime_bars.py -q`
Expected: FAIL — `ImportError: cannot import name 'FLAG_MIXED'`

- [ ] **Step 3: data_regimes.py 수정**

`VOLUME_REGIME_UNVERIFIED_FROM` 정의를 아래로 교체(모듈 docstring 의 "정규장 복원" 문장은 "회신 21: 애프터마켓 포함 거래량을 정의로 수용, 표지는 mixed 창만" 으로 갱신):

```python
VOLUME_REGIME_BOUNDARY: Final[date] = date(2026, 9, 28)        # KRX 일별 거래량에 애프터마켓 합산 시작(관측 추정, 회신 21)
VOLUME_REGIME_UNVERIFIED_FROM: Final[date] = VOLUME_REGIME_BOUNDARY   # PR #217 호환 별칭
REGIME_REGULAR: Final[str] = "regular"     # 정규장(09:00~15:30) 거래량
REGIME_EXTENDED: Final[str] = "extended"   # 애프터마켓(16:00~20:00) 합산 거래량
REGIME_MIXED: Final[str] = "mixed"         # 주봉: 구성 일봉 혼재
FLAG_MIXED: Final[str] = "mixed"           # 판정 행 volume_regime_flag 값(그 외 NULL)


def regime_for_date(d: date) -> str:
    """봉 날짜 → 정의. 저장 SQL 의 CASE 와 같은 규칙(테스트가 둘의 일치를 고정)."""
    return REGIME_EXTENDED if d >= VOLUME_REGIME_BOUNDARY else REGIME_REGULAR


def regime_flag_for_as_of(as_of) -> str | None:
    """판정 행 표지(PR-2 규칙): as_of ≥ 경계 → 'mixed'. PR-3 에서 계산 창 유도로 축소(new → NULL)."""
    d = _as_date(as_of)
    if d is None or d < VOLUME_REGIME_BOUNDARY:
        return None
    return FLAG_MIXED
```

- [ ] **Step 4: schema.sql 끝에 추가**

```sql

-- (2026-09-30 #207 회신 21 Q-5c) 거래량 정의 경계 — 봉 단위. regular(정규장) / extended(애프터마켓 합산, 2026-09-28~) / mixed(주봉 혼재).
-- 값은 날짜의 함수(data_regimes.VOLUME_REGIME_BOUNDARY): 저장 SQL 의 CASE 가 채우고, 소급은 scripts/sql/issue207_volume_regime_migrate.sql.
ALTER TABLE daily_prices  ADD COLUMN IF NOT EXISTS volume_regime VARCHAR(8) NOT NULL DEFAULT 'regular';
ALTER TABLE index_daily   ADD COLUMN IF NOT EXISTS volume_regime VARCHAR(8) NOT NULL DEFAULT 'regular';
ALTER TABLE weekly_prices ADD COLUMN IF NOT EXISTS volume_regime VARCHAR(8) NOT NULL DEFAULT 'regular';
-- 판정 행 표지(전용 컬럼, 회신 21 Q-5c 3): 계산 창이 경계에 걸친 판정만 'mixed', 그 외 NULL. sanity_warnings/known_warnings 와 의미 분리.
ALTER TABLE weekly_classification        ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
ALTER TABLE trigger_evaluation_log       ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
ALTER TABLE entry_params                 ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
ALTER TABLE position_climax_evaluations  ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
ALTER TABLE position_decline_evaluations ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_volume_regime_bars.py -q`
Expected: 4 passed

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/common/data_regimes.py kr_pipeline/db/schema.sql tests/test_volume_regime_bars.py
git commit -m "volume_regime — 경계 상수·regime_for_date·flag 규칙(PR-2) + 봉 3테이블 volume_regime·판정 5테이블 volume_regime_flag 컬럼"
```

---

### Task 2: 일봉·지수 저장 SQL 이 regime 기록

**Files:**
- Modify: `kr_pipeline/ohlcv/store.py` (`upsert_daily_prices`, `upsert_index_daily`)
- Test: `tests/test_volume_regime_bars.py` (append)

**Interfaces:**
- Consumes: `VOLUME_REGIME_BOUNDARY`
- Produces: 저장된 행의 `volume_regime` = `regime_for_date(date)`. 튜플 계약(13/14·8) 불변.

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_volume_regime_bars.py (append)
from kr_pipeline.ohlcv.store import upsert_daily_prices, upsert_index_daily


def _price_row(ticker, d):
    return (ticker, d, 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 1000.0, 1000, 105000, 1.5)


def test_upsert_daily_prices_writes_regime_by_date(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRB1','VRB1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM daily_prices WHERE ticker='VRB1'")
    before, at = B - timedelta(days=1), B
    upsert_daily_prices(db, [_price_row("VRB1", before), _price_row("VRB1", at)])
    with db.cursor() as cur:
        cur.execute("SELECT date, volume_regime FROM daily_prices WHERE ticker='VRB1' ORDER BY date")
        assert cur.fetchall() == [(before, "regular"), (at, "extended")]
    # 재적재(ON CONFLICT)도 같은 값 — 다른 writer 가 기본값 'regular' 로 덮지 않음
    upsert_daily_prices(db, [_price_row("VRB1", at)])
    with db.cursor() as cur:
        cur.execute("SELECT volume_regime FROM daily_prices WHERE ticker='VRB1' AND date=%s", (at,))
        assert cur.fetchone()[0] == "extended"


def test_upsert_index_daily_writes_regime_by_date(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM index_daily WHERE index_code='VRIDX'")
    upsert_index_daily(db, [("VRIDX", B - timedelta(days=1), 100.0, 101.0, 99.0, 100.5, 10, 20),
                            ("VRIDX", B, 100.0, 101.0, 99.0, 100.5, 10, 20)])
    with db.cursor() as cur:
        cur.execute("SELECT date, volume_regime FROM index_daily WHERE index_code='VRIDX' ORDER BY date")
        assert [r[1] for r in cur.fetchall()] == ["regular", "extended"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_volume_regime_bars.py -q -k regime_by_date`
Expected: FAIL — `assert [(…, 'regular'), (…, 'regular')] == …`

- [ ] **Step 3: store.py 수정**

`upsert_daily_prices` 의 INSERT 컬럼·VALUES·DO UPDATE 에 `volume_regime` 추가. 행마다 경계 날짜를 파라미터로 붙인다(`prepared` 튜플 끝에 `VOLUME_REGIME_BOUNDARY` 1개 추가, VALUES 자리 `CASE WHEN %s >= %s THEN 'extended' ELSE 'regular' END` 는 date 파라미터를 두 번 쓰지 않도록 아래처럼 표현):

```python
from kr_pipeline.common.data_regimes import VOLUME_REGIME_BOUNDARY
...
            INSERT INTO daily_prices
              (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, change_pct,
               volume_regime, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s >= %s THEN 'extended' ELSE 'regular' END, NOW())
            ON CONFLICT (ticker, date) DO UPDATE
               SET ...,
                   volume_regime = EXCLUDED.volume_regime,
                   updated_at = NOW()
```
파라미터: `(*r[:14], r[1], VOLUME_REGIME_BOUNDARY, *([r[14]] * 5))` — `r[1]` 은 date. (`prepared` 조립 줄만 바꾸면 된다.)

`upsert_index_daily`: 동일하게 `volume_regime` 컬럼 + `CASE WHEN %s >= %s …`, rows 를 `[(*r, r[1], VOLUME_REGIME_BOUNDARY) for r in rows]` 로 변환해 executemany. DO UPDATE 에 `volume_regime = EXCLUDED.volume_regime`.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_volume_regime_bars.py tests/test_ohlcv_store.py tests/test_ohlcv_modes.py -q`
Expected: 전부 passed (기존 store 테스트 회귀 0)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/ohlcv/store.py tests/test_volume_regime_bars.py
git commit -m "volume_regime — daily_prices·index_daily upsert 가 날짜 CASE 로 regime 기록(튜플 계약 불변)"
```

---

### Task 3: 주봉 regime(regular/extended/mixed)

**Files:**
- Modify: `kr_pipeline/weekly/store.py` (`upsert_weekly_prices`)
- Test: `tests/test_volume_regime_bars.py` (append)

**Interfaces:**
- Produces: `weekly_prices.volume_regime` = 주의 월요일(`week_end_date - (ISODOW-1)`) ≥ 경계 → extended · `week_end_date` < 경계 → regular · 그 외 mixed.

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_volume_regime_bars.py (append)
from kr_pipeline.weekly.store import upsert_weekly_prices


def _week_row(ticker, week_end):
    return (ticker, week_end, 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 5000.0, 5000, 525000, 5)


def test_upsert_weekly_prices_regime_regular_extended_mixed(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRW1','VRW1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM weekly_prices WHERE ticker='VRW1'")
    # 경계 2026-09-28(월). 09-25(금) 주 → regular, 10-02(금) 주(월=09-28) → extended,
    # 가상의 경계가 수요일이었다면 mixed 가 나오는지: 경계 주의 월요일 < 경계 ≤ 금요일 인 주를 만들기 위해 경계 -2 일 주 사용 불가 →
    # mixed 는 SQL 규칙 자체를 다른 경계 파라미터로 검증하기 어렵다 → 함수 단위(Task 3 Step 3 의 _weekly_regime_sql 은 파라미터화) 대신
    # 실제 경계로 regular/extended 두 경우를 고정하고, mixed 는 week_end 가 경계+2(수) 이고 월요일이 경계-5 인 주로 확인한다.
    upsert_weekly_prices(db, [_week_row("VRW1", date(2026, 9, 25)), _week_row("VRW1", date(2026, 10, 2))])
    with db.cursor() as cur:
        cur.execute("SELECT week_end_date, volume_regime FROM weekly_prices WHERE ticker='VRW1' ORDER BY 1")
        assert cur.fetchall() == [(date(2026, 9, 25), "regular"), (date(2026, 10, 2), "extended")]


def test_weekly_regime_mixed_when_week_straddles_boundary(db, monkeypatch):
    """경계를 수요일(가상)로 두면 그 주는 mixed — SQL 규칙(월요일 < 경계 ≤ week_end) 검증."""
    import kr_pipeline.weekly.store as ws
    monkeypatch.setattr(ws, "VOLUME_REGIME_BOUNDARY", date(2026, 9, 30))
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRW2','VRW2','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM weekly_prices WHERE ticker='VRW2'")
    upsert_weekly_prices(db, [_week_row("VRW2", date(2026, 10, 2))])
    with db.cursor() as cur:
        cur.execute("SELECT volume_regime FROM weekly_prices WHERE ticker='VRW2'")
        assert cur.fetchone()[0] == "mixed"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_volume_regime_bars.py -q -k weekly`
Expected: FAIL — regime 이 전부 'regular'

- [ ] **Step 3: weekly/store.py 수정**

```python
from kr_pipeline.common.data_regimes import VOLUME_REGIME_BOUNDARY
...
            INSERT INTO weekly_prices
              (ticker, week_end_date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, trading_days,
               volume_regime, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s < %s THEN 'regular'
                         WHEN (%s - (EXTRACT(ISODOW FROM %s)::int - 1)) >= %s THEN 'extended'
                         ELSE 'mixed' END,
                    NOW())
            ON CONFLICT (ticker, week_end_date) DO UPDATE
               SET ..., volume_regime = EXCLUDED.volume_regime, updated_at = NOW()
```
파라미터 변환: `[(*r, r[1], B, r[1], r[1], B) for r in rows]` (B = `VOLUME_REGIME_BOUNDARY`, 모듈 전역으로 두어 테스트가 monkeypatch 가능). `%s - int` 는 DATE − integer 라 psycopg 가 date 를 넘기면 유효.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_volume_regime_bars.py tests/test_weekly_modes.py tests/test_weekly_store.py -q`
Expected: 전부 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/weekly/store.py tests/test_volume_regime_bars.py
git commit -m "volume_regime — weekly_prices upsert 가 주의 월요일/금요일과 경계 비교로 regular·extended·mixed 기록"
```

---

### Task 4: 경계일 전일 비교 무효화(분배일·FTD)

**Files:**
- Modify: `kr_pipeline/market_context/load.py` (`load_index_daily_with_sma200` SELECT 에 `volume_regime`), `compute/distribution_day.py` (`count_distribution_days`), `compute/follow_through.py` (`find_recent_follow_through`), `modes.py` (`COMPUTATION_NOTES`)
- Test: `tests/test_market_context_boundary.py` (new)

**Interfaces:**
- Consumes: `index_df["volume_regime"]`(없으면 비교 허용 — 구 호출처·리플레이 호환)
- Produces: today/yesterday regime 이 다르면 그날은 분배일·정체일·FTD 후보에서 제외. 헬퍼 `regime_comparable(today_row, yesterday_row) -> bool` 를 `compute/__init__.py` 또는 `compute/regime.py` 에 두고 두 모듈이 공유.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_market_context_boundary.py
"""#207 회신 21 Q-5c 1 — 경계일(정의가 다른 전일) 거래량 비교 무효화."""
from datetime import date, timedelta

import pandas as pd

from kr_pipeline.market_context.compute.distribution_day import count_distribution_days
from kr_pipeline.market_context.compute.follow_through import find_recent_follow_through


def _df(rows):
    """rows = [(date, close, volume, high, low, regime)]"""
    return pd.DataFrame(rows, columns=["date", "close", "volume", "high", "low", "volume_regime"]).reset_index(drop=True)


def test_distribution_day_skipped_when_regime_differs():
    d0 = date(2026, 9, 25)
    base = [(d0, 100.0, 1000.0, 101.0, 99.0, "regular")]
    # 09-28: 하락 -1%, 거래량 증가(새 정의) → regime 다르면 분배일 아님
    diff = _df(base + [(date(2026, 9, 28), 99.0, 1500.0, 100.0, 98.5, "extended")])
    same = _df(base + [(date(2026, 9, 28), 99.0, 1500.0, 100.0, 98.5, "regular")])
    assert count_distribution_days(same, end_idx=1, lookback=25) == 1
    assert count_distribution_days(diff, end_idx=1, lookback=25) == 0


def test_distribution_day_without_regime_column_unchanged():
    df = pd.DataFrame([(100.0, 1000.0, 101.0, 99.0), (99.0, 1500.0, 100.0, 98.5)], columns=["close", "volume", "high", "low"])
    assert count_distribution_days(df, end_idx=1, lookback=25) == 1


def test_follow_through_skipped_when_regime_differs():
    rows = []
    d = date(2026, 9, 1)
    for i in range(12):                       # 하락 후 저점
        rows.append((d + timedelta(days=i), 100.0 - i, 1000.0, 101.0 - i, 99.0 - i, "regular"))
    low_day = d + timedelta(days=11)
    # 저점 후 4일째 +2% 급등·거래량 증가 = FTD 후보
    for i in range(1, 4):
        rows.append((low_day + timedelta(days=i), 89.5 + i * 0.1, 900.0, 90.0, 89.0, "regular"))
    ftd_day = low_day + timedelta(days=4)
    same = _df(rows + [(ftd_day, 92.0, 1200.0, 92.5, 90.0, "regular")])
    diff = _df(rows + [(ftd_day, 92.0, 1200.0, 92.5, 90.0, "extended")])
    n = len(same) - 1
    assert find_recent_follow_through(same, n, pct_threshold=1.0, lookback_days=25) == ftd_day
    assert find_recent_follow_through(diff, n, pct_threshold=1.0, lookback_days=25) is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_market_context_boundary.py -q`
Expected: FAIL — `assert 1 == 0` / FTD 가 반환됨

- [ ] **Step 3: 구현**

`kr_pipeline/market_context/compute/regime.py`:
```python
"""(#207 회신 21 Q-5c 1) 전일 대비 거래량 비교의 정의 정합 — today/yesterday 의 volume_regime 이 다르면 비교 불가."""
def regime_comparable(today, yesterday) -> bool:
    """행에 volume_regime 이 없으면(구 호출처·리플레이) 비교 허용."""
    try:
        a, b = today["volume_regime"], yesterday["volume_regime"]
    except (KeyError, IndexError):
        return True
    if a is None or b is None:
        return True
    return a == b
```
`distribution_day.count_distribution_days` 루프의 `today/yesterday` 추출 직후:
```python
        if not regime_comparable(today, yesterday):
            continue   # 거래량 정의 경계(09-25→09-28): 비교 불가 — 분배일·정체일 아님
```
`follow_through.find_recent_follow_through` 루프의 `yesterday["close"] == 0` 검사 다음:
```python
        if not regime_comparable(today, yesterday):
            continue
```
`load.py` SELECT 에 `volume_regime` 추가(`SELECT date, close, volume, high, low, volume_regime`). `modes.py COMPUTATION_NOTES` 에 `"volume_regime_boundary_rule": "today/yesterday volume_regime differ → not comparable (no distribution/stalling/FTD that day) — #207 회신 21"` 추가.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_market_context_boundary.py tests/test_market_context_modes.py tests/test_market_context_compute.py -q` (해당 파일명은 `ls tests | grep market_context` 로 확인)
Expected: 전부 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/market_context/compute/regime.py kr_pipeline/market_context/compute/distribution_day.py kr_pipeline/market_context/compute/follow_through.py kr_pipeline/market_context/load.py kr_pipeline/market_context/modes.py tests/test_market_context_boundary.py
git commit -m "market_context — 전일과 volume_regime 이 다른 날(경계 09-25→09-28)은 분배일·정체일·FTD 비교 제외, notes 기록"
```

---

### Task 5: 판정 행 표지를 전용 컬럼으로(문자열 표지 제거)

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py`(insert_classification·insert_backfill_classification·insert_trigger_log·insert_entry_params), `kr_pipeline/trade_management/runner.py`(climax·decline INSERT), `kr_pipeline/common/data_regimes.py`(`with_volume_regime`·`volume_regime_warnings`·`VOLUME_REGIME_TAG` 삭제)
- Test: `tests/test_volume_regime_tag.py` (rewrite)

**Interfaces:**
- Consumes: `regime_flag_for_as_of`
- Produces: 5 insert 가 `volume_regime_flag` 컬럼에 `regime_flag_for_as_of(analyzed_for_date | eval_date)` 기록. sanity_warnings/known_warnings 에는 아무것도 덧붙이지 않음.

- [ ] **Step 1: 테스트 파일 교체**

`tests/test_volume_regime_tag.py` 를 다음으로 교체(트립와이어 (4) 테스트는 그대로 유지):

```python
"""#207 회신 21 Q-5c 3 — 판정 행 표지 = 전용 컬럼 volume_regime_flag(문자열 표지 제거) + 트립와이어 (4)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from kr_pipeline.common.data_regimes import FLAG_MIXED, VOLUME_REGIME_BOUNDARY
from tests.test_llm_runner_store import _cls_result, _s9_result

B = VOLUME_REGIME_BOUNDARY
CASES = [(B - timedelta(days=5), None), (B, FLAG_MIXED)]
_LLM_META = {"duration_s": 1.0, "input_tokens": None, "output_tokens": None}


def _one(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def test_text_tag_helpers_are_gone():
    import kr_pipeline.common.data_regimes as m
    assert not hasattr(m, "with_volume_regime") and not hasattr(m, "VOLUME_REGIME_TAG")


@pytest.mark.parametrize("as_of,flag", CASES)
def test_classification_flag_column_and_clean_sanity(db, as_of, flag):
    from kr_pipeline.llm_runner.store import insert_classification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='VRF1'")
    insert_classification(db, symbol="VRF1", classified_at=datetime.now(timezone.utc), market="KOSPI",
                          result=_cls_result(), source="weekend", llm_meta=_LLM_META, analyzed_for_date=as_of)
    f, w = _one(db, "SELECT volume_regime_flag, sanity_warnings FROM weekly_classification WHERE symbol='VRF1'")
    assert f == flag and not (w or [])            # 문자열 표지 없음


@pytest.mark.parametrize("as_of,flag", CASES)
def test_trigger_log_flag_column(db, as_of, flag):
    from kr_pipeline.llm_runner.store import insert_trigger_log
    now = datetime(B.year, B.month, B.day, 9, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='VRF2'")
    insert_trigger_log(db, symbol="VRF2", evaluated_at=now, trigger_type="breakout", close=1010.0, volume=1, pivot_price=1000.0,
                       result={"decision": "wait", "confidence": 0.5, "reasoning": "t"}, prior_classification_at=now,
                       llm_meta=_LLM_META, analyzed_for_date=as_of)
    f, w = _one(db, "SELECT volume_regime_flag, sanity_warnings FROM trigger_evaluation_log WHERE symbol='VRF2'")
    assert f == flag and w is None


@pytest.mark.parametrize("as_of,flag", CASES)
def test_entry_params_flag_column_and_clean_known_warnings(db, as_of, flag):
    from kr_pipeline.llm_runner.store import insert_entry_params
    now = datetime(B.year, B.month, B.day, 1, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM entry_params WHERE symbol='VRF3'")
    insert_entry_params(db, symbol="VRF3", signal_at=now, result=_s9_result(), trigger_evaluation_at=now,
                        prior_classification_at=now, llm_meta=_LLM_META, analyzed_for_date=as_of)
    f, kw = _one(db, "SELECT volume_regime_flag, known_warnings FROM entry_params WHERE symbol='VRF3' AND signal_at=%s", now)
    assert f == flag and "volume_regime_unverified_#207" not in (kw or [])


@pytest.mark.parametrize("as_of,flag", CASES)
def test_position_evaluations_flag_column(db, as_of, flag):
    """runner.py 의 두 INSERT 문을 직접 실행하는 대신 같은 SQL 을 호출하는 헬퍼 `record_held_evaluations` 를 검증."""
    from kr_pipeline.trade_management.runner import _insert_climax_eval, _insert_decline_eval
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRF4','VRF4','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM positions WHERE symbol='VRF4'")
        cur.execute("INSERT INTO positions (symbol, entry_date, entry_price, quantity, status) VALUES ('VRF4', %s, 1000, 1, 'open') RETURNING id", (as_of,))
        pid = cur.fetchone()[0]
    _insert_climax_eval(db, position_id=pid, as_of=as_of, fired=False, suppressed=False, hold_days=1, triggers=[],
                        anchor_week=None, weeks_since=None, maturity_ok=None, p2_accel_ok=None, scope_active=None, mode="quality")
    _insert_decline_eval(db, position_id=pid, as_of=as_of, fired=False, hold_days=1, signals=[], anchor_week=None, weeks_since=None,
                         maturity_ok=None, ta_max_decline_now=None, ta_d_daily_max_decline_now=None, mode="quality", climax_also_fired=False)
    assert _one(db, "SELECT volume_regime_flag FROM position_climax_evaluations WHERE position_id=%s", pid)[0] == flag
    assert _one(db, "SELECT volume_regime_flag FROM position_decline_evaluations WHERE position_id=%s", pid)[0] == flag
    with db.cursor() as cur:
        cur.execute("DELETE FROM positions WHERE id=%s", (pid,)); cur.execute("DELETE FROM stocks WHERE ticker='VRF4'")
```
(기존 `test_tripwire4_volume_breakout_count_warns_over_max` 는 파일 끝에 그대로 둔다. positions INSERT 의 NOT NULL 컬럼은 `\d positions` 로 확인해 보정.)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_volume_regime_tag.py -q`
Expected: FAIL — `_insert_climax_eval` ImportError 등

- [ ] **Step 3: store.py 수정**

- import: `from kr_pipeline.common.data_regimes import regime_flag_for_as_of` (with_volume_regime 제거).
- `insert_classification`/`insert_backfill_classification`: `sanity_warnings = with_volume_regime(...)` 줄 삭제. INSERT 컬럼 목록에 `volume_regime_flag` 추가, VALUES `%s` 1개 추가, 파라미터 끝에 `regime_flag_for_as_of(analyzed_for_date)`.
- `insert_trigger_log`: `regime_warnings = …` 삭제; 컬럼 `sanity_warnings` 는 남기되 값은 `None`(PR #217 컬럼은 향후 가격 sanity 용으로 유지) → 실제로는 컬럼 목록에서 `sanity_warnings` 를 빼고 `volume_regime_flag` 를 넣는다(19→19 자리 유지).
- `insert_entry_params`: `n["known_warnings"] = with_volume_regime(...)` 줄 삭제; 컬럼 `volume_regime_flag` 추가 + 파라미터 `regime_flag_for_as_of(analyzed_for_date)`.

- [ ] **Step 4: runner.py 수정**

두 INSERT 를 모듈 함수로 추출(테스트 가능):
```python
def _insert_climax_eval(conn, *, position_id, as_of, fired, suppressed, hold_days, triggers, anchor_week, weeks_since,
                        maturity_ok, p2_accel_ok, scope_active, mode) -> bool:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO position_climax_evaluations
              (position_id, eval_date, fired, suppressed, hold_days, triggers, anchor_week, weeks_since, maturity_ok, p2_accel_ok,
               scope_active, mode, volume_regime_flag)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (position_id, eval_date) DO NOTHING""",
            (position_id, as_of, fired, suppressed, hold_days, json.dumps(list(triggers)), anchor_week, weeks_since,
             maturity_ok, p2_accel_ok, scope_active, mode, regime_flag_for_as_of(as_of)))
        return cur.rowcount == 1
```
`_insert_decline_eval` 동형(기존 decline INSERT 컬럼 + `volume_regime_flag`). 호출처(191·227행 부근)를 두 함수 호출로 교체.

- [ ] **Step 5: data_regimes.py 정리**

`VOLUME_REGIME_TAG`·`volume_regime_warnings`·`with_volume_regime` 삭제. `_as_date` 는 유지(`regime_flag_for_as_of` 가 사용).

- [ ] **Step 6: 통과 확인**

Run: `uv run pytest tests/test_volume_regime_tag.py tests/test_llm_runner_store.py tests/test_trade_held_climax.py tests/test_trade_held_decline.py -q`
Expected: 전부 passed

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/llm_runner/store.py kr_pipeline/trade_management/runner.py kr_pipeline/common/data_regimes.py tests/test_volume_regime_tag.py
git commit -m "volume_regime — 판정 5테이블 표지를 전용 컬럼 volume_regime_flag 로(문자열 표지·헬퍼 삭제), 보유 평가 INSERT 함수 추출"
```

---

### Task 6: 이관 SQL(소급 채움·문자열 제거·flag 이관) + 운영 적용

**Files:**
- Create: `scripts/sql/issue207_volume_regime_migrate.sql`
- Test: `tests/test_volume_regime_bars.py` (append — 스크립트를 kr_test 에 실행해 멱등 검증)

- [ ] **Step 1: 실패 테스트 추가**

```python
# tests/test_volume_regime_bars.py (append)
from pathlib import Path


def test_migration_script_is_idempotent_and_moves_tags(db):
    sql = (Path(__file__).parent.parent / "scripts" / "sql" / "issue207_volume_regime_migrate.sql").read_text(encoding="utf-8")
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRM1','VRM1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM daily_prices WHERE ticker='VRM1'"); cur.execute("DELETE FROM weekly_classification WHERE symbol='VRM1'")
        # regime 기본값 'regular' 로 강제된 경계 이후 행 + 문자열 표지가 남은 분류 행
        cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value, volume_regime) "
                    "VALUES ('VRM1', %s, 1,1,1,1,1,1,1,'regular')", (B,))
        cur.execute("INSERT INTO weekly_classification (symbol, classified_at, market, classification, pattern, source, analyzed_for_date, sanity_warnings) "
                    "VALUES ('VRM1', now(), 'KOSPI', 'watch', 'flat_base', 'weekend', %s, %s)", (B, '["x", "volume_regime_unverified_#207"]'))
    for _ in range(2):                       # 2회 실행 = 멱등
        with db.cursor() as cur:
            cur.execute(sql)
    with db.cursor() as cur:
        cur.execute("SELECT volume_regime FROM daily_prices WHERE ticker='VRM1' AND date=%s", (B,)); assert cur.fetchone()[0] == "extended"
        cur.execute("SELECT volume_regime_flag, sanity_warnings FROM weekly_classification WHERE symbol='VRM1'")
        f, w = cur.fetchone(); assert f == "mixed" and w == ["x"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_volume_regime_bars.py -q -k migration`
Expected: FAIL — FileNotFoundError

- [ ] **Step 3: 스크립트 작성**

```sql
-- scripts/sql/issue207_volume_regime_migrate.sql — #207 회신 21 Q-5c 소급(멱등). 양쪽 DB(kr_pipeline·kr_test)에 psql -f.
-- 경계 = 2026-09-28 (data_regimes.VOLUME_REGIME_BOUNDARY 와 동일해야 함 — 변경 시 이 파일도 갱신).
BEGIN;
UPDATE daily_prices  SET volume_regime = 'extended' WHERE date >= '2026-09-28' AND volume_regime <> 'extended';
UPDATE daily_prices  SET volume_regime = 'regular'  WHERE date <  '2026-09-28' AND volume_regime <> 'regular';
UPDATE index_daily   SET volume_regime = 'extended' WHERE date >= '2026-09-28' AND volume_regime <> 'extended';
UPDATE index_daily   SET volume_regime = 'regular'  WHERE date <  '2026-09-28' AND volume_regime <> 'regular';
UPDATE weekly_prices SET volume_regime = CASE WHEN week_end_date < '2026-09-28' THEN 'regular'
                                              WHEN (week_end_date - (EXTRACT(ISODOW FROM week_end_date)::int - 1)) >= '2026-09-28' THEN 'extended'
                                              ELSE 'mixed' END
 WHERE volume_regime IS DISTINCT FROM CASE WHEN week_end_date < '2026-09-28' THEN 'regular'
                                            WHEN (week_end_date - (EXTRACT(ISODOW FROM week_end_date)::int - 1)) >= '2026-09-28' THEN 'extended'
                                            ELSE 'mixed' END;
-- 판정 행: 문자열 표지 제거 + flag 이관(PR-2 규칙 as_of ≥ 경계)
UPDATE weekly_classification SET sanity_warnings = NULLIF(sanity_warnings - 'volume_regime_unverified_#207', '[]'::jsonb)
 WHERE sanity_warnings ? 'volume_regime_unverified_#207';
UPDATE trigger_evaluation_log SET sanity_warnings = NULLIF(sanity_warnings - 'volume_regime_unverified_#207', '[]'::jsonb)
 WHERE sanity_warnings ? 'volume_regime_unverified_#207';
UPDATE entry_params SET known_warnings = known_warnings - 'volume_regime_unverified_#207'
 WHERE known_warnings ? 'volume_regime_unverified_#207';
UPDATE weekly_classification        SET volume_regime_flag = 'mixed' WHERE analyzed_for_date >= '2026-09-28' AND volume_regime_flag IS NULL;
UPDATE trigger_evaluation_log       SET volume_regime_flag = 'mixed' WHERE analyzed_for_date >= '2026-09-28' AND volume_regime_flag IS NULL;
UPDATE entry_params                 SET volume_regime_flag = 'mixed' WHERE analyzed_for_date >= '2026-09-28' AND volume_regime_flag IS NULL;
UPDATE position_climax_evaluations  SET volume_regime_flag = 'mixed' WHERE eval_date >= '2026-09-28' AND volume_regime_flag IS NULL;
UPDATE position_decline_evaluations SET volume_regime_flag = 'mixed' WHERE eval_date >= '2026-09-28' AND volume_regime_flag IS NULL;
COMMIT;
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_volume_regime_bars.py -q`
Expected: 전부 passed

- [ ] **Step 5: 운영 적용(규칙 4) — 사용자 승인 후 실행**

```bash
psql postgresql://localhost/kr_pipeline -v ON_ERROR_STOP=1 -c "$(sed -n '/거래량 정의 경계 — 봉 단위/,/position_decline_evaluations ADD COLUMN IF NOT EXISTS volume_regime_flag/p' kr_pipeline/db/schema.sql)"
psql postgresql://localhost/kr_pipeline -v ON_ERROR_STOP=1 -f scripts/sql/issue207_volume_regime_migrate.sql
psql postgresql://localhost/kr_pipeline -At -c "SELECT volume_regime, count(*) FROM daily_prices WHERE date >= '2026-09-20' GROUP BY 1"
psql postgresql://localhost/kr_pipeline -At -c "SELECT count(*) FILTER (WHERE volume_regime_flag='mixed'), count(*) FILTER (WHERE sanity_warnings ? 'volume_regime_unverified_#207') FROM weekly_classification"
```
Expected: 09-28 이후 extended, 문자열 표지 0, flag 20·6·0(·climax/decline 0).
그 다음 09-28 market_context 재계산(경계일 비교 무효화 반영): `uv run python -m kr_pipeline.market_context --mode=incremental --window-days=30` (KRX 접촉 0, DB 재계산) → `market_context_daily` 09-28 행의 `distribution_day_count_last_25`·FTD 변화를 #207 에 기록.

- [ ] **Step 6: 커밋**

```bash
git add scripts/sql/issue207_volume_regime_migrate.sql tests/test_volume_regime_bars.py
git commit -m "volume_regime — 소급 채움·문자열 표지 제거·flag 이관 멱등 SQL(양쪽 DB)"
```

---

### Task 7: API·웹 — flag 노출, 배지, 문자열 매핑 삭제

**Files:**
- Modify: `api/routers/signals.py`(SELECT + 응답 필드 `volume_regime_flag`), `web/src/lib/types.ts`(EntrySignal 에 `volume_regime_flag: string | null`), `web/src/pages/SignalsPage.tsx`, `web/src/components/panels/EntrySignalCard.tsx`
- Delete: `web/src/lib/warningLabels.ts`
- Test: `tests/test_api_signals.py`(있으면 응답 필드 단언 추가; 없으면 신규 최소 테스트), vitest 는 순수 함수 없음 → build 통과로 확인

- [ ] **Step 1: 실패 테스트**

```python
# tests/test_api_signals_regime.py
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from api.deps import get_conn
from api.main import app
from kr_pipeline.common.data_regimes import VOLUME_REGIME_BOUNDARY
from tests.test_llm_runner_store import _s9_result


def test_signals_api_exposes_volume_regime_flag(db):
    from kr_pipeline.llm_runner.store import insert_entry_params
    app.dependency_overrides[get_conn] = lambda: (yield db)
    try:
        now = datetime.now(timezone.utc)
        with db.cursor() as cur:
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRA1','VRA1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
            cur.execute("DELETE FROM entry_params WHERE symbol='VRA1'")
        insert_entry_params(db, symbol="VRA1", signal_at=now, result=_s9_result(), trigger_evaluation_at=now, prior_classification_at=now,
                            llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None}, analyzed_for_date=VOLUME_REGIME_BOUNDARY)
        r = TestClient(app).get("/api/signals")
        assert r.status_code == 200
        row = next(s for s in r.json() if s["symbol"] == "VRA1")
        assert row["volume_regime_flag"] == "mixed"
    finally:
        app.dependency_overrides.pop(get_conn, None)
```
(`/api/signals` 의 실제 경로·필터 파라미터는 `api/routers/signals.py` 상단 `@router.get` 로 확인해 맞춘다.)

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_api_signals_regime.py -q` → FAIL(KeyError)

- [ ] **Step 3: API 수정** — `signals.py` SELECT 에 `ep.volume_regime_flag` 추가, 응답 모델/딕트에 `volume_regime_flag=r[<idx>]`.

- [ ] **Step 4: 웹 수정**

`types.ts` EntrySignal: `volume_regime_flag: string | null;`.
`SignalsPage.tsx`·`EntrySignalCard.tsx`: `known_warnings` 칩은 `{w}` 원문으로 되돌리고(`warningLabel` 제거), 카드 상단에
```tsx
{s.volume_regime_flag === "mixed" && (
  <span className="chip bg-amber-soft text-amber text-data-xs" title="2026-09-28 부터 KRX 일별 거래량에 애프터마켓이 합산됨. 이 판정의 거래량 창이 경계에 걸쳐 비율이 위로 편향될 수 있음(#207)">
    거래량 혼재 창
  </span>
)}
```
`warningLabels.ts` 삭제 및 import 제거.

- [ ] **Step 5: 확인** — `uv run pytest tests/test_api_signals_regime.py -q` PASS; `cd web && npm run test && npm run build`.

- [ ] **Step 6: 커밋**

```bash
git add api/routers/signals.py web/src/lib/types.ts web/src/pages/SignalsPage.tsx web/src/components/panels/EntrySignalCard.tsx tests/test_api_signals_regime.py
git rm web/src/lib/warningLabels.ts
git commit -m "volume_regime — signals API·카드에 volume_regime_flag 배지, known_warnings 문자열 매핑 삭제"
```

---

### Task 8: checklist 이력·전체 검증·PR

- [ ] **Step 1: checklist 이력 1줄** — `docs/superpowers/threshold-change-checklist.md` 끝에: "2026-09-30: #207 회신 21 Q-5c 1·3(PR-2) — thresholds.py 변경 0. 봉 3테이블 `volume_regime`(날짜 함수, 저장 SQL CASE)·판정 5테이블 `volume_regime_flag`(PR-2 규칙 as_of ≥ 09-28 → mixed, PR-3 에서 창 유도로 축소) · market_context 분배일/정체일/FTD 는 전일과 regime 다르면 비교 제외(09-25→09-28 1쌍) · 문자열 표지 제거·이관 SQL. 판정 값·산술 변경 0. 소비 경계: daily_prices.volume_regime → market_context.load → distribution_day/follow_through(regime_comparable) / weekly_prices.volume_regime → (PR-3) C3·T2·T-D 창 유도."
- [ ] **Step 2: 전체 suite** — `pgrep -f "pytest tests/" || uv run pytest tests/ -q` → 실패 0.
- [ ] **Step 3: 커밋·푸시·PR** — 제목 "volume_regime PR-2 — 봉 단위 거래량 정의·판정 행 전용 표지·경계일 비교 무효화(#207 회신 21 Q-5c 1·3)". 본문: 요약·운영 적용 절차(Task 6 Step 5, 승인 후)·검증 수치. 머지는 사용자.

---

## Self-Review

- **Spec coverage**: D1·D2→T1~T3, D3(유도 함수)→PR-3(범위 밖, 계획 §7 명시), D4·D5→T5·T6, D6→T4, D7→T5(flag 기록; 발화 불변), D8 유지, D9→T7. 이관·양쪽 DB→T6.
- **Placeholder scan**: T4 Step 4 의 테스트 파일명, T5 positions NOT NULL 컬럼, T7 API 경로는 실행 시 확인 지시 포함 — 값은 코드 블록에 있음.
- **Type consistency**: `regime_flag_for_as_of` 반환 `str|None`('mixed'|None) 을 T5·T6·T7 이 동일 사용; `volume_regime` 문자열 3종 T1~T3·T6 동일; `regime_comparable(today, yesterday)` T4 두 모듈 공유.
