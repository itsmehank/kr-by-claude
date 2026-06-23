# 수익성·강건성 백테스트 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2021-2024 전 국면에 걸쳐 무작위 100종목의 결정론 트리거·청산을 시뮬해, 시장 게이트가 하락·횡보기 진입을 억제하고 손실을 막는지 국면별로 측정한다.

**Architecture:** 기존 `kr_pipeline/backtest/` 결정론 엔진과 LLM 백필 building block을 재사용한다. 클린 환경 보장을 위해 분류는 **전용 테이블 `backtest_classification`**(pre-lockdown 적재분과 격리)에 적재·resume한다. 신규 코드는 전부 `kr_pipeline/backtest/` 아래(읽기전용 분석 패키지)에 두고, 공유 코드는 두 곳만 default-preserving하게 `table` 파라미터화한다.

**Tech Stack:** Python (psycopg, pandas 불요), Postgres, Claude CLI(`call_claude`), pytest(kr_test DB fixture `db`).

## Global Constraints

- **결정론·재현**: 표집 시드 = **20260623** 고정. 표집 방법은 단순 무작위 100종목, 프레임 = 2021-2024 production 주말 필터 통과 종목(1,851).
- **클린 격리**: 분류 적재·resume는 **`backtest_classification`** 테이블만 사용. `classification_backfill`(pre-lockdown 321행)을 읽지도 쓰지도 않는다.
- **웹검색 차단**: 이미 적용됨(`5e02826`, `--tools Read` + 프롬프트). 추가 작업 없음 — 이 plan의 모든 LLM 호출은 그 환경에서 돈다.
- **LLM 비결정성 규율**: 1회 백필 → 저장 → 분석. 재실행 비교 금지(멱등 이어가기만 OK).
- **SQL injection 가드**: `table` 파라미터는 반드시 allowlist `{"classification_backfill", "backtest_classification"}` 검증 후 f-string에 넣는다(사용자 입력 아님, 내부 상수지만 방어).
- **schema.sql 수동 적용**: `schema.sql` 변경은 자동 반영 안 됨 — `kr_pipeline`·`kr_test` 양쪽 DB에 `psql -f` 수동 적용(memory: schema_manual_apply_both_dbs).
- **테스트 baseline**: 회귀 판정은 base↔HEAD 실패 수 비교(사전 실패 ~31개 baseline). 새 실패 0건이 목표.

---

### Task 1: 전용 테이블 `backtest_classification` (스키마)

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (append, `classification_backfill` 블록 직후 ~line 485 근처)

**Interfaces:**
- Produces: 테이블 `backtest_classification` (PK `(symbol, analyzed_for_date)`), 인덱스 `idx_backtest_classification_date`.

- [ ] **Step 1: schema.sql 에 테이블 추가**

`classification_backfill` 의 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS watch_reason` 블록 바로 뒤에 추가:

```sql
-- ====== 수익성·강건성 백테스트 전용 분류 테이블 (2026-06-23) ======
-- classification_backfill 스키마 복제. pre-lockdown 적재분과 격리해 "검색-차단 클린
-- 환경" 을 구조적으로 보장(spec §5.0). 적재·멱등 resume 모두 이 테이블 기준.
CREATE TABLE IF NOT EXISTS backtest_classification (
  symbol               VARCHAR(10) NOT NULL,
  classified_at        TIMESTAMPTZ NOT NULL,
  analyzed_for_date    DATE NOT NULL,
  market               VARCHAR(10) NOT NULL,
  classification       VARCHAR(20) NOT NULL,
  pattern              VARCHAR(50),
  pivot_price          NUMERIC(12, 4),
  pivot_basis          VARCHAR(30),
  base_high            NUMERIC(12, 4),
  base_low             NUMERIC(12, 4),
  base_depth_pct       NUMERIC(5, 2),
  base_start_date      DATE,
  risk_flags           JSONB,
  confidence           NUMERIC(3, 2),
  reasoning            TEXT,
  source               VARCHAR(20) NOT NULL,
  llm_call_duration_s  NUMERIC(8, 2),
  llm_input_tokens     INTEGER,
  llm_output_tokens    INTEGER,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  triggered_rules      JSONB,
  measurements         JSONB,
  watch_reason         VARCHAR(40),
  PRIMARY KEY (symbol, analyzed_for_date)
);
CREATE INDEX IF NOT EXISTS idx_backtest_classification_date
  ON backtest_classification (analyzed_for_date);
```

- [ ] **Step 2: 양쪽 DB 에 수동 적용**

```bash
psql postgresql://localhost/kr_pipeline -f kr_pipeline/db/schema.sql
psql postgresql://localhost/kr_test     -f kr_pipeline/db/schema.sql
```
Expected: 에러 없이 완료(`CREATE TABLE` / `NOTICE: relation already exists, skipping` 혼재 OK).

- [ ] **Step 3: 적용 확인**

```bash
psql postgresql://localhost/kr_pipeline -c "\d backtest_classification" | head -5
psql postgresql://localhost/kr_test     -c "\d backtest_classification" | head -5
```
Expected: 양쪽 모두 테이블 정의 출력(컬럼 24개, PK symbol+analyzed_for_date).

- [ ] **Step 4: Commit**

```bash
git add kr_pipeline/db/schema.sql
git commit -m "feat(backtest): backtest_classification 전용 분류 테이블 추가"
```

---

### Task 2: `insert_backfill_classification` 에 `table` 파라미터

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py` (`insert_backfill_classification`, ~line 159-209)
- Test: `tests/test_backtest_classification_store.py` (create)

**Interfaces:**
- Consumes: 기존 `insert_backfill_classification(conn, *, symbol, classified_at, market, result, source, llm_meta, analyzed_for_date)`
- Produces: 동일 + `table: str = "classification_backfill"` 키워드. allowlist 검증 후 해당 테이블에 INSERT.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_classification_store.py
from datetime import datetime, date, timezone


def _result(cls="watch", pivot=100.0):
    return {
        "classification": cls, "pattern": "flat_base", "pivot_price": pivot,
        "pivot_basis": "range_high", "base_high": pivot, "base_low": pivot * 0.9,
        "base_depth_pct": 8.0, "base_start_date": "2025-08-01", "risk_flags": [],
        "confidence": 0.7, "reasoning": "t",
    }


def test_insert_into_backtest_classification_table(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BT1','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='BT1'")
    db.commit()
    insert_backfill_classification(
        db, symbol="BT1", classified_at=datetime(2026, 6, 23, 1, tzinfo=timezone.utc),
        market="KOSPI", result=_result("watch"), source="backtest",
        llm_meta={"duration_s": 5.0, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2023, 6, 30), table="backtest_classification",
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT classification, source FROM backtest_classification WHERE symbol='BT1'")
            rows = cur.fetchall()
            # 기존 테이블에는 안 들어가야 함(격리)
            cur.execute("SELECT COUNT(*) FROM classification_backfill WHERE symbol='BT1'")
            other = cur.fetchone()[0]
        assert len(rows) == 1 and rows[0] == ("watch", "backtest")
        assert other == 0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM backtest_classification WHERE symbol='BT1'")
        db.commit()


def test_insert_rejects_unknown_table(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    import pytest
    with pytest.raises(ValueError):
        insert_backfill_classification(
            db, symbol="BT1", classified_at=datetime(2026, 6, 23, tzinfo=timezone.utc),
            market="KOSPI", result=_result(), source="backtest",
            llm_meta={"duration_s": 1.0}, analyzed_for_date=date(2023, 6, 30),
            table="weekly_classification; DROP TABLE x",
        )
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_classification_store.py -v`
Expected: FAIL — `insert_backfill_classification() got an unexpected keyword argument 'table'`

- [ ] **Step 3: 최소 구현**

`store.py` 시그니처에 `table` 추가(맨 끝 키워드):

```python
def insert_backfill_classification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    result: dict,
    source: str,
    llm_meta: dict,
    analyzed_for_date: date,
    table: str = "classification_backfill",
) -> None:
```

함수 본문 맨 위(`_validate_classification(result)` 직전)에 allowlist 검증 추가:

```python
    if table not in ("classification_backfill", "backtest_classification"):
        raise ValueError(f"insert_backfill_classification: unknown table {table!r}")
```

INSERT 문의 테이블명을 f-string으로(검증 끝났으므로 안전). line 190-210 의 `cur.execute("""... INSERT INTO classification_backfill ...""", (...))` 를:

```python
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {table}
              (symbol, classified_at, analyzed_for_date, market, classification, pattern,
               pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date,
               risk_flags, confidence, reasoning,
               source,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens,
               triggered_rules,
               measurements,
               watch_reason)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s,
                    %s,
                    %s,
                    %s)
            ON CONFLICT (symbol, analyzed_for_date) DO NOTHING
            """,
            (
```
(VALUES 튜플·나머지 본문은 그대로 둔다.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_classification_store.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 기존 백필 테스트 회귀 확인**

Run: `uv run pytest tests/test_llm_backfill.py -q`
Expected: 기존과 동일(default 'classification_backfill' 보존 — 새 실패 0).

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/llm_runner/store.py tests/test_backtest_classification_store.py
git commit -m "feat(backtest): insert_backfill_classification table 파라미터(allowlist)"
```

---

### Task 3: `trigger_sim.load_watchlist` 에 `table` 파라미터

**Files:**
- Modify: `kr_pipeline/backtest/trigger_sim.py` (`load_watchlist`, line 153-171)
- Test: `tests/test_backtest_load_watchlist_table.py` (create)

**Interfaces:**
- Consumes: 기존 `load_watchlist(conn, ticker, start, end)`
- Produces: 동일 + `table: str = "classification_backfill"`. allowlist 검증 후 해당 테이블에서 watch 행 로드.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_load_watchlist_table.py
from datetime import datetime, date, timezone


def test_load_watchlist_reads_backtest_table(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    from kr_pipeline.backtest.trigger_sim import load_watchlist
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('WL1','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='WL1'")
    db.commit()
    insert_backfill_classification(
        db, symbol="WL1", classified_at=datetime(2026, 6, 23, tzinfo=timezone.utc),
        market="KOSPI",
        result={"classification": "watch", "pattern": "flat_base", "pivot_price": 100.0,
                "pivot_basis": "range_high", "base_high": 100.0, "base_low": 90.0,
                "base_depth_pct": 8.0, "base_start_date": "2023-05-01", "risk_flags": [],
                "confidence": 0.7, "reasoning": "t", "watch_reason": "base_forming"},
        llm_meta={"duration_s": 1.0}, analyzed_for_date=date(2023, 6, 30),
        table="backtest_classification",
    )
    db.commit()
    try:
        rows = load_watchlist(db, "WL1", date(2023, 1, 1), date(2023, 12, 31),
                              table="backtest_classification")
        assert len(rows) == 1
        assert rows[0].pivot_price == 100.0
        # default 테이블에는 없음
        empty = load_watchlist(db, "WL1", date(2023, 1, 1), date(2023, 12, 31))
        assert empty == []
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM backtest_classification WHERE symbol='WL1'")
        db.commit()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_load_watchlist_table.py -v`
Expected: FAIL — unexpected keyword argument 'table'

- [ ] **Step 3: 최소 구현**

`load_watchlist` 를 수정:

```python
def load_watchlist(conn: Connection, ticker: str, start: date, end: date,
                   table: str = "classification_backfill") -> list[WatchRow]:
    if table not in ("classification_backfill", "backtest_classification"):
        raise ValueError(f"load_watchlist: unknown table {table!r}")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT analyzed_for_date, pivot_price, base_low, watch_reason
              FROM {table}
             WHERE symbol = %s AND classification = 'watch'
               AND analyzed_for_date BETWEEN %s AND %s
             ORDER BY analyzed_for_date
            """,
            (ticker, start, end),
        )
        return [
            WatchRow(ticker=ticker, sat=r[0],
                     pivot_price=float(r[1]) if r[1] is not None else None,
                     base_low=float(r[2]) if r[2] is not None else None,
                     watch_reason=r[3])
            for r in cur.fetchall()
        ]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_load_watchlist_table.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/trigger_sim.py tests/test_backtest_load_watchlist_table.py
git commit -m "feat(backtest): load_watchlist table 파라미터(allowlist)"
```

---

### Task 4: 결정론 표집 (`sample.py`)

**Files:**
- Create: `kr_pipeline/backtest/sample.py`
- Test: `tests/test_backtest_sample.py`

**Interfaces:**
- Produces:
  - `build_frame(conn, start: date, end: date) -> list[str]` — 기간 내 production 주말 필터 통과 종목(정렬된 distinct ticker).
  - `draw_sample(frame: list[str], n: int = 100, seed: int = 20260623) -> list[str]` — 결정론 무작위 추출(정렬 후 `random.Random(seed).sample`), 결과 정렬 반환.
  - `sample_composition(conn, tickers: list[str]) -> dict` — `{"n":..,"by_market":{...},"by_sector":{...}}`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_sample.py
from datetime import date


def test_draw_sample_is_deterministic():
    from kr_pipeline.backtest.sample import draw_sample
    frame = [f"{i:06d}" for i in range(1000)]
    a = draw_sample(frame, n=100, seed=20260623)
    b = draw_sample(frame, n=100, seed=20260623)
    assert a == b                 # 같은 시드 → 동일
    assert len(a) == 100
    assert len(set(a)) == 100     # 중복 없음
    assert a == sorted(a)         # 정렬 반환
    c = draw_sample(frame, n=100, seed=1)
    assert c != a                 # 다른 시드 → 다름


def test_draw_sample_order_independent():
    from kr_pipeline.backtest.sample import draw_sample
    frame1 = [f"{i:06d}" for i in range(1000)]
    frame2 = list(reversed(frame1))
    # 입력 순서가 달라도(내부 정렬) 동일 표본
    assert draw_sample(frame1, seed=20260623) == draw_sample(frame2, seed=20260623)


def test_draw_sample_n_exceeds_frame():
    from kr_pipeline.backtest.sample import draw_sample
    assert sorted(draw_sample(["a", "b", "c"], n=100, seed=1)) == ["a", "b", "c"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_sample.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 구현**

```python
# kr_pipeline/backtest/sample.py
"""수익성·강건성 백테스트 표집 — 결정론 무작위(시드 고정). 읽기전용."""
from __future__ import annotations

import random
from datetime import date

from psycopg import Connection

DEFAULT_SEED = 20260623


def build_frame(conn: Connection, start: date, end: date) -> list[str]:
    """기간 내 production 주말 필터(get_qualifying_tickers 와 동일 조건)를 한 번이라도
    통과한 종목 집합. 금요일 기준(주간 cadence)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT i.ticker
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date BETWEEN %s AND %s
               AND EXTRACT(DOW FROM i.date) = 5
               AND i.minervini_pass = TRUE
               AND i.rs_line_not_declining_7m = TRUE
               AND s.delisted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM daily_prices p
                    WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL
               )
             ORDER BY i.ticker
            """,
            (start, end),
        )
        return [r[0] for r in cur.fetchall()]


def draw_sample(frame: list[str], n: int = 100, seed: int = DEFAULT_SEED) -> list[str]:
    """결정론 단순무작위 추출. 입력 순서 무관(내부 정렬), 결과 정렬 반환."""
    pool = sorted(set(frame))
    if len(pool) <= n:
        return pool
    return sorted(random.Random(seed).sample(pool, n))


def sample_composition(conn: Connection, tickers: list[str]) -> dict:
    if not tickers:
        return {"n": 0, "by_market": {}, "by_sector": {}}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT market, COALESCE(sector,'(none)') FROM stocks WHERE ticker = ANY(%s)",
            (tickers,),
        )
        rows = cur.fetchall()
    by_market: dict[str, int] = {}
    by_sector: dict[str, int] = {}
    for market, sector in rows:
        by_market[market] = by_market.get(market, 0) + 1
        by_sector[sector] = by_sector.get(sector, 0) + 1
    return {"n": len(tickers), "by_market": by_market, "by_sector": by_sector}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_sample.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/sample.py tests/test_backtest_sample.py
git commit -m "feat(backtest): 결정론 표집(build_frame/draw_sample/composition)"
```

---

### Task 5: 백테스트 백필 드라이버 (`backfill.py`)

**Files:**
- Create: `kr_pipeline/backtest/backfill.py`
- Test: `tests/test_backtest_backfill.py`

**Interfaces:**
- Consumes: `kr_pipeline.llm_runner.backfill._enumerate_saturdays`, `kr_pipeline.llm_runner.load.get_qualifying_tickers`, `kr_pipeline.llm_runner.parallel.run_parallel_batch`, `api.services.inline_builder.build_analysis_inline`, `kr_pipeline.llm_runner.llm.claude_cli.call_claude`, `kr_pipeline.llm_runner.store.insert_backfill_classification` (Task 2의 `table` 파라미터).
- Produces:
  - `BT_TABLE = "backtest_classification"`, `BT_SOURCE = "backtest"`
  - `already_done(conn, as_of: date) -> set[str]` — `backtest_classification` 기준 skip 집합.
  - `run_backtest_backfill(conn, *, start: date, end: date, tickers: list[str], dry_run: bool=False, concurrency: int|None=None) -> dict` — 토요일 × tickers 멱등 백필.

- [ ] **Step 1: 실패하는 테스트 작성 (dry_run + mock, DB 미적재 경로 + 멱등 skip)**

```python
# tests/test_backtest_backfill.py
from datetime import datetime, date, timezone


def test_already_done_reads_backtest_table(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    from kr_pipeline.backtest.backfill import already_done
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BD1','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='BD1'")
    db.commit()
    assert already_done(db, date(2023, 6, 30)) == set() or "BD1" not in already_done(db, date(2023, 6, 30))
    insert_backfill_classification(
        db, symbol="BD1", classified_at=datetime(2026, 6, 23, tzinfo=timezone.utc),
        market="KOSPI",
        result={"classification": "watch", "pattern": "flat_base", "pivot_price": 100.0,
                "pivot_basis": "range_high", "base_high": 100.0, "base_low": 90.0,
                "base_depth_pct": 8.0, "base_start_date": "2023-05-01", "risk_flags": [],
                "confidence": 0.7, "reasoning": "t", "watch_reason": "base_forming"},
        llm_meta={"duration_s": 1.0}, analyzed_for_date=date(2023, 6, 30),
        table="backtest_classification",
    )
    db.commit()
    try:
        assert "BD1" in already_done(db, date(2023, 6, 30))
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM backtest_classification WHERE symbol='BD1'")
        db.commit()


def test_run_backtest_backfill_dry_run_no_insert(db, monkeypatch):
    # call_claude 를 mock(웹/실호출 없이) — dry_run 경로는 insert 안 함
    from kr_pipeline.backtest import backfill as bt
    # 토요일 1개 범위, 후보를 강제 주입(실제 qualifying 조회 우회)
    monkeypatch.setattr(bt, "get_qualifying_tickers",
                        lambda conn, as_of, tickers=None: [{"symbol": "BD2", "market": "KOSPI"}])
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BD2','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM backtest_classification WHERE symbol='BD2'")
    db.commit()
    r = bt.run_backtest_backfill(db, start=date(2023, 6, 26), end=date(2023, 7, 1),
                                 tickers=["BD2"], dry_run=True, concurrency=1)
    assert r["weeks"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM backtest_classification WHERE symbol='BD2'")
        assert cur.fetchone()[0] == 0   # dry_run 은 적재 안 함
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_backfill.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 구현**

```python
# kr_pipeline/backtest/backfill.py
"""수익성·강건성 백테스트 백필 — 전용 테이블 backtest_classification 에 멱등 적재.

production backfill(kr_pipeline/llm_runner/backfill.py)과 격리된 드라이버.
공유 building block(토요일 열거·qualifying 조회·병렬·인라인 빌드·call_claude·insert)을
재사용하되, 적재·resume 는 backtest_classification 만 본다(spec §5). 읽기전용 분석.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.inline_builder import build_analysis_inline
from kr_pipeline.llm_runner.backfill import _enumerate_saturdays
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError
from kr_pipeline.llm_runner.load import get_qualifying_tickers
from kr_pipeline.llm_runner.parallel import run_parallel_batch
from kr_pipeline.llm_runner.store import insert_backfill_classification

log = logging.getLogger(__name__)

BT_TABLE = "backtest_classification"
BT_SOURCE = "backtest"


def already_done(conn: Connection, as_of: date) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT symbol FROM {BT_TABLE} WHERE analyzed_for_date = %s", (as_of,)
        )
        return {r[0] for r in cur.fetchall()}


def _process_one(conn: Connection, symbol: str, market: str, *, dry_run: bool, as_of: date) -> None:
    started = datetime.now(timezone.utc)
    inline_text, png_paths, _ = build_analysis_inline(conn, symbol, on_date=as_of)
    png_dir = str(Path(png_paths[0]).parent)
    try:
        result = call_claude(
            prompt_file="analyze_chart_v3.md",
            attachments=png_paths, payload_inline=inline_text, dry_run=dry_run,
        )
    finally:
        shutil.rmtree(png_dir, ignore_errors=True)
    finished = datetime.now(timezone.utc)
    if dry_run:
        log.info("dry-run: skip insert %s (%s)", symbol, result.get("classification"))
        return
    insert_backfill_classification(
        conn, symbol=symbol, classified_at=finished, market=market, result=result,
        source=BT_SOURCE,
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": None, "output_tokens": None},
        analyzed_for_date=as_of, table=BT_TABLE,
    )


def run_backtest_backfill(conn: Connection, *, start: date, end: date, tickers: list[str],
                          dry_run: bool = False, concurrency: int | None = None) -> dict:
    """기간 × 매주 토요일, 지정 tickers 중 그 주 qualifying 종목을 분류해 BT_TABLE 에 적재.
    멱등: 이미 적재된 (symbol, 토요일)은 skip. 사용량 한도 시 abort(다음 실행이 이어감)."""
    saturdays = _enumerate_saturdays(start, end)
    concurrency = concurrency or int(os.environ.get("BACKFILL_CONCURRENCY", "4"))
    agg = {"weeks": 0, "processed": 0, "skipped_existing": 0, "failures": 0,
           "failed": [], "integrity_skipped": [], "start": str(start), "end": str(end)}
    dsn = conn.info.dsn
    abort = threading.Event()

    for as_of in saturdays:
        if abort.is_set():
            break
        candidates = get_qualifying_tickers(conn, as_of=as_of, tickers=tickers)
        done = already_done(conn, as_of)
        skipped = [c for c in candidates if c["symbol"] in done]
        candidates = [c for c in candidates if c["symbol"] not in done]
        log.info("bt-backfill week=%s: %d candidate(s) (done %d)", as_of, len(candidates), len(done))
        r = run_parallel_batch(
            dsn=dsn, candidates=candidates, process_fn=_process_one,
            concurrency=concurrency, dry_run=dry_run, as_of=as_of, run_id=None, abort=abort,
        )
        agg["processed"] += r["processed"]
        for ft in r["failed_tickers"]:
            agg["failed"].append([ft["symbol"], str(as_of), ft.get("error", "")])
        agg["failures"] += len(r["failed_tickers"])
        agg["integrity_skipped"].extend(r["integrity_skipped"])
        agg["skipped_existing"] += len(skipped)
        agg["weeks"] += 1
        conn.commit()
        if r["usage_limited"]:
            log.warning("bt-backfill usage limit at %s (processed=%d)", as_of, agg["processed"])
            raise UsageLimitError(
                f"usage limit — bt-backfill aborted: processed={agg['processed']}, reason={r['usage_error']}"
            )
    return agg
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_backfill.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/backfill.py tests/test_backtest_backfill.py
git commit -m "feat(backtest): 전용 테이블 멱등 백필 드라이버(run_backtest_backfill)"
```

---

### Task 6: 국면 라벨 (`phases.py`)

**Files:**
- Create: `kr_pipeline/backtest/phases.py`
- Test: `tests/test_backtest_phases.py`

**Interfaces:**
- Produces:
  - `INDEX_OF = {"KOSPI": "1001", "KOSDAQ": "2001"}`
  - `load_phase_map(conn, index_code: str) -> list[tuple[date, str]]` — (date, current_status) 오름차순 전체.
  - `phase_at(phase_map: list[tuple[date,str]], on: date) -> str | None` — on 이하 가장 최근 status(없으면 None).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_phases.py
from datetime import date


def test_phase_at_nearest_on_or_before():
    from kr_pipeline.backtest.phases import phase_at
    pm = [(date(2023, 1, 2), "downtrend"), (date(2023, 1, 5), "rally_attempt"),
          (date(2023, 1, 9), "confirmed_uptrend")]
    assert phase_at(pm, date(2023, 1, 1)) is None       # 이전 데이터 없음
    assert phase_at(pm, date(2023, 1, 2)) == "downtrend"
    assert phase_at(pm, date(2023, 1, 7)) == "rally_attempt"   # 1/5 의 값
    assert phase_at(pm, date(2023, 1, 30)) == "confirmed_uptrend"


def test_load_phase_map_orders_and_filters(db):
    from kr_pipeline.backtest.phases import load_phase_map
    with db.cursor() as cur:
        cur.execute("DELETE FROM market_context_daily WHERE index_code='9999'")
        cur.execute("INSERT INTO market_context_daily (date,index_code,current_status) "
                    "VALUES ('2023-02-01','9999','correction'),('2023-01-01','9999','downtrend')")
    db.commit()
    try:
        pm = load_phase_map(db, "9999")
        assert [d for d, _ in pm] == sorted(d for d, _ in pm)   # 오름차순
        assert pm[0][1] == "downtrend"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM market_context_daily WHERE index_code='9999'")
        db.commit()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_phases.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 구현**

```python
# kr_pipeline/backtest/phases.py
"""국면 라벨 — market_context_daily.current_status 를 (date 이하 최근) 으로 조회. 읽기전용."""
from __future__ import annotations

import bisect
from datetime import date

from psycopg import Connection

INDEX_OF = {"KOSPI": "1001", "KOSDAQ": "2001"}


def load_phase_map(conn: Connection, index_code: str) -> list[tuple[date, str]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, current_status FROM market_context_daily "
            "WHERE index_code = %s ORDER BY date",
            (index_code,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


def phase_at(phase_map: list[tuple[date, str]], on: date) -> str | None:
    """on 이하 가장 최근 current_status. phase_map 은 date 오름차순."""
    dates = [d for d, _ in phase_map]
    i = bisect.bisect_right(dates, on) - 1
    return phase_map[i][1] if i >= 0 else None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_phases.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/phases.py tests/test_backtest_phases.py
git commit -m "feat(backtest): 국면 라벨 조회(load_phase_map/phase_at)"
```

---

### Task 7: 분석 드라이버 — 국면별 집계 + §7 기준 (`profitability_run.py`)

**Files:**
- Create: `kr_pipeline/backtest/profitability_run.py`
- Test: `tests/test_backtest_profitability_aggregate.py`

**Interfaces:**
- Consumes: Task 3 `load_watchlist(table=BT_TABLE)`, `trigger_sim`(`load_daily_series`/`load_index_series`/`classify_rows`/`simulate`/`market_relative`), Task 6 `phases`.
- Produces:
  - `DOWN_PHASES = {"downtrend", "correction"}`
  - `entry_rate_by_phase(conn, tickers: list[str]) -> dict[str, dict]` — 국면별 `{entry, total, rate}` (분류점 기준, BT_TABLE).
  - `aggregate_trades(trades: list[dict]) -> dict[str, dict]` — 국면별 `{n, mean_excess, win_rate, ...}` (트레이드 기준).
  - `evaluate_criteria(entry_rates: dict, trade_aggs: dict) -> dict` — §7.1/§7.2/§7.5 판정.
  - `run_analysis(conn, tickers: list[str], px_start, px_end) -> dict` — 위를 묶어 전체 산출.

- [ ] **Step 1: 실패하는 테스트(순수 집계 로직, DB 무관) 작성**

```python
# tests/test_backtest_profitability_aggregate.py
def test_entry_rate_ratio_and_criteria():
    from kr_pipeline.backtest.profitability_run import evaluate_criteria
    entry_rates = {
        "confirmed_uptrend": {"entry": 20, "total": 100, "rate": 0.20},
        "downtrend": {"entry": 2, "total": 100, "rate": 0.02},
        "correction": {"entry": 3, "total": 100, "rate": 0.03},
    }
    # R_down = (2+3)/(100+100)=0.025, R_up=0.20 → ratio 0.125 ≤ 0.5 → PASS
    trade_aggs = {
        "downtrend": {"n": 12, "mean_excess": 1.5},
        "correction": {"n": 8, "mean_excess": -0.5},
        "confirmed_uptrend": {"n": 15, "mean_excess": 4.0},
    }
    out = evaluate_criteria(entry_rates, trade_aggs)
    assert out["gate_defense_71"]["r_down"] == 0.025
    assert out["gate_defense_71"]["r_up"] == 0.20
    assert out["gate_defense_71"]["ratio"] == 0.125
    assert out["gate_defense_71"]["pass"] is True
    # §7.5 검정력: correction n=8 < 10 → underpowered 표기
    assert out["power_guard"]["correction"] == "underpowered"
    assert out["power_guard"]["downtrend"] == "ok"


def test_aggregate_trades_basic():
    from kr_pipeline.backtest.profitability_run import aggregate_trades
    trades = [
        {"phase": "downtrend", "excess_pct": 2.0, "pnl_pct": 1.0},
        {"phase": "downtrend", "excess_pct": -1.0, "pnl_pct": -3.0},
        {"phase": "confirmed_uptrend", "excess_pct": 5.0, "pnl_pct": 6.0},
        {"phase": None, "excess_pct": 1.0, "pnl_pct": 1.0},   # 라벨 없으면 제외
    ]
    agg = aggregate_trades(trades)
    assert agg["downtrend"]["n"] == 2
    assert agg["downtrend"]["mean_excess"] == 0.5
    assert agg["downtrend"]["win_rate"] == 0.5
    assert "confirmed_uptrend" in agg
    assert None not in agg
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_profitability_aggregate.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 구현**

```python
# kr_pipeline/backtest/profitability_run.py
"""수익성·강건성 백테스트 분석 드라이버 — 국면별 집계 + §7 사전등록 기준 판정. 읽기전용.

입력 분류 = backtest_classification(전용 테이블). 트리거·청산 = 기존 결정론 엔진.
산출 = 트레이드별 (P&L·시장대비 초과수익·진입일 국면) + 국면별 집계 + §7 판정.
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection

from kr_pipeline.backtest import phases as ph
from kr_pipeline.backtest.backfill import BT_TABLE
from kr_pipeline.backtest.trigger_sim import (
    load_watchlist, load_daily_series, load_index_series, classify_rows,
    simulate, market_relative,
)

DOWN_PHASES = ("downtrend", "correction")
POWER_MIN = 10   # §7.5: 국면별 트레이드 < 10 → underpowered


def _market_of(conn: Connection, ticker: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT market FROM stocks WHERE ticker = %s", (ticker,))
        return cur.fetchone()[0]


def entry_rate_by_phase(conn: Connection, tickers: list[str]) -> dict[str, dict]:
    """분류점(BT_TABLE 행) 기준 국면별 entry-rate. 국면 = analyzed_for_date 의 시장상태."""
    pmaps: dict[str, list] = {}
    counts: dict[str, dict] = {}
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT b.symbol, b.analyzed_for_date, b.classification, s.market "
            f"FROM {BT_TABLE} b JOIN stocks s ON s.ticker = b.symbol "
            f"WHERE b.symbol = ANY(%s)",
            (tickers,),
        )
        rows = cur.fetchall()
    for symbol, afd, cls, market in rows:
        code = ph.INDEX_OF.get(market, "1001")
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
        phase = ph.phase_at(pmaps[code], afd)
        if phase is None:
            continue
        c = counts.setdefault(phase, {"entry": 0, "total": 0})
        c["total"] += 1
        if cls == "entry":
            c["entry"] += 1
    for phase, c in counts.items():
        c["rate"] = (c["entry"] / c["total"]) if c["total"] else 0.0
    return counts


def aggregate_trades(trades: list[dict]) -> dict[str, dict]:
    """국면별 트레이드 집계. phase=None(라벨 없음) 제외. excess_pct None 도 제외."""
    buckets: dict[str, list] = {}
    for t in trades:
        if t.get("phase") is None or t.get("excess_pct") is None:
            continue
        buckets.setdefault(t["phase"], []).append(t)
    out: dict[str, dict] = {}
    for phase, ts in buckets.items():
        ex = [t["excess_pct"] for t in ts]
        wins = sum(1 for t in ts if t["excess_pct"] > 0)
        out[phase] = {
            "n": len(ts),
            "mean_excess": round(sum(ex) / len(ex), 3),
            "win_rate": round(wins / len(ts), 3),
            "mean_pnl": round(sum(t["pnl_pct"] for t in ts) / len(ts), 3),
        }
    return out


def evaluate_criteria(entry_rates: dict[str, dict], trade_aggs: dict[str, dict]) -> dict:
    """§7.1(분류층 게이트 방어, 1차) + §7.2(초과수익, 보조) + §7.5(검정력 가드)."""
    down_entry = sum(entry_rates.get(p, {}).get("entry", 0) for p in DOWN_PHASES)
    down_total = sum(entry_rates.get(p, {}).get("total", 0) for p in DOWN_PHASES)
    r_down = (down_entry / down_total) if down_total else 0.0
    r_up = entry_rates.get("confirmed_uptrend", {}).get("rate", 0.0)
    ratio = (r_down / r_up) if r_up else None
    gate_71 = {
        "r_down": round(r_down, 3), "r_up": round(r_up, 3),
        "ratio": round(ratio, 3) if ratio is not None else None,
        "pass": (ratio is not None and ratio <= 0.5),
        "note": "R_up=0 이면 ratio 미정의 — 수동 해석" if ratio is None else "",
    }
    down_excess = [trade_aggs.get(p, {}).get("mean_excess") for p in DOWN_PHASES
                   if p in trade_aggs]
    excess_72 = {
        "down_mean_excess": down_excess,
        "supportive": all(x is not None and x >= 0 for x in down_excess) if down_excess else None,
        "note": "보조 지표 — §4 트리거 누수 영향. 음수≠게이트 실패(§7.1로 판정).",
    }
    power = {p: ("ok" if trade_aggs.get(p, {}).get("n", 0) >= POWER_MIN else "underpowered")
             for p in set(list(trade_aggs) + list(DOWN_PHASES) + ["confirmed_uptrend", "rally_attempt"])}
    return {"gate_defense_71": gate_71, "excess_72": excess_72, "power_guard": power}


def run_analysis(conn: Connection, tickers: list[str], px_start: date, px_end: date,
                 watch_start: date, watch_end: date) -> dict:
    """전체 산출: 트레이드(production)별 진입일 국면 라벨 + 국면별 집계 + §7 판정."""
    pmaps: dict[str, list] = {}
    all_trades: list[dict] = []
    for ticker in tickers:
        market = _market_of(conn, ticker)
        code = ph.INDEX_OF.get(market, "1001")
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
        wr = load_watchlist(conn, ticker, watch_start, watch_end, table=BT_TABLE)
        bars = load_daily_series(conn, ticker, px_start, px_end)
        idx = load_index_series(conn, market, px_start, px_end)
        cls = classify_rows(wr)
        prod_trades, _ = simulate(ticker, cls["production"], bars, mode="production")
        for t in prod_trades:
            excess = market_relative(t, idx)
            all_trades.append({
                "ticker": t.ticker, "entry_date": str(t.entry_date),
                "exit_date": str(t.exit_date) if t.exit_date else None,
                "pnl_pct": round(t.pnl_pct, 2) if t.pnl_pct is not None else None,
                "excess_pct": round(excess, 2) if excess is not None else None,
                "binding_exit": t.binding_exit,
                "phase": ph.phase_at(pmaps[code], t.entry_date),
            })
    entry_rates = entry_rate_by_phase(conn, tickers)
    trade_aggs = aggregate_trades(all_trades)
    criteria = evaluate_criteria(entry_rates, trade_aggs)
    return {"n_tickers": len(tickers), "n_trades": len(all_trades),
            "entry_rates": entry_rates, "trade_aggs": trade_aggs,
            "criteria": criteria, "trades": all_trades}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_profitability_aggregate.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 전체 백테스트 테스트 회귀 확인**

Run: `uv run pytest tests/ -k "backtest" -q`
Expected: 새 테스트 전부 PASS, 기존 backtest 테스트(있으면) 불변.

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/backtest/profitability_run.py tests/test_backtest_profitability_aggregate.py
git commit -m "feat(backtest): 국면별 집계 + §7 사전등록 기준 판정(profitability_run)"
```

---

### Task 8: 표본 동결(pre-registration) + CLI 엔트리

**Files:**
- Create: `kr_pipeline/backtest/profitability_cli.py` (CLI: sample-freeze / backfill / analyze 서브커맨드)
- Create: `docs/superpowers/backtest-profitability-sample.md` (동결된 100종목 리스트 + 구성 — 실행 산출물)

**Interfaces:**
- Consumes: Task 4 `sample`, Task 5 `run_backtest_backfill`, Task 7 `run_analysis`.
- Produces: `python -m kr_pipeline.backtest.profitability_cli {sample|backfill|analyze}` CLI.

**근거:** 사전등록 규율 — 표본 100종목은 **백필 시작 전** 동결·기록돼야 한다(post-hoc 종목 추가 금지). 시드 고정이라 결정론적이지만, 동결 리스트를 git에 박아 감사 가능하게 한다.

- [ ] **Step 1: CLI 구현 (테스트 없이 — thin orchestration, building block은 Task 2~7에서 검증됨)**

```python
# kr_pipeline/backtest/profitability_cli.py
"""수익성·강건성 백테스트 CLI. 읽기전용 분석 + 전용 테이블 적재.

  python -m kr_pipeline.backtest.profitability_cli sample    # 100종목 동결 출력
  python -m kr_pipeline.backtest.profitability_cli backfill   # 멱등 백필(resume 가능)
  python -m kr_pipeline.backtest.profitability_cli analyze    # 국면별 집계 + §7 판정
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.db.connection import connect
from kr_pipeline.backtest.sample import build_frame, draw_sample, sample_composition, DEFAULT_SEED
from kr_pipeline.backtest.backfill import run_backtest_backfill
from kr_pipeline.backtest.profitability_run import run_analysis

START, END = date(2021, 1, 1), date(2024, 12, 31)          # 분류 윈도(주간)
PX_START, PX_END = date(2020, 7, 1), date(2025, 6, 30)      # 가격(선행 SMA + forward 청산)


def _sample(conn) -> list[str]:
    frame = build_frame(conn, START, END)
    return draw_sample(frame, n=100, seed=DEFAULT_SEED)


def cmd_sample(conn) -> int:
    frame = build_frame(conn, START, END)
    sample = draw_sample(frame, n=100, seed=DEFAULT_SEED)
    comp = sample_composition(conn, sample)
    print(json.dumps({"seed": DEFAULT_SEED, "frame_size": len(frame),
                      "sample": sample, "composition": comp}, ensure_ascii=False, indent=2))
    return 0


def cmd_backfill(conn, dry_run: bool) -> int:
    sample = _sample(conn)
    r = run_backtest_backfill(conn, start=START, end=END, tickers=sample, dry_run=dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


def cmd_analyze(conn) -> int:
    sample = _sample(conn)
    out = run_analysis(conn, sample, PX_START, PX_END, watch_start=START, watch_end=END)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sample"
    dry_run = "--dry-run" in sys.argv
    with connect() as conn:
        if cmd == "sample":
            return cmd_sample(conn)
        if cmd == "backfill":
            return cmd_backfill(conn, dry_run)
        if cmd == "analyze":
            return cmd_analyze(conn)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 표본 동결 — 실제 추출·기록**

```bash
uv run python -m kr_pipeline.backtest.profitability_cli sample > /tmp/bt_sample.json
cat /tmp/bt_sample.json
```
Expected: `frame_size` ≈ 1851, `sample` 100개, `composition.by_market` 에 KOSPI/KOSDAQ 분포.
**확인**: 한 시장이 ≥ 85%면 spec §2 에 따라 시장 층화 재고를 사용자에게 보고(그 전엔 무작위 유지).

- [ ] **Step 3: 동결 문서 작성·commit**

`/tmp/bt_sample.json` 내용을 `docs/superpowers/backtest-profitability-sample.md` 로 옮겨 적되, 다음 형식:

```markdown
# 수익성·강건성 백테스트 — 동결 표본 (2026-06-23, 사전등록)

- 시드: 20260623 / 프레임: <frame_size>종목 / 표본: 100종목
- 구성: KOSPI <n> / KOSDAQ <n> (쏠림 판정: <무작위 유지 | 층화 재고 보고>)
- 섹터 분포: <by_sector>

## 100종목 (정렬)
<sample 리스트를 그대로>
```

```bash
git add docs/superpowers/backtest-profitability-sample.md kr_pipeline/backtest/profitability_cli.py
git commit -m "feat(backtest): 표본 동결(100종목 사전등록) + 백테스트 CLI"
```

---

### Task 9: 실험 실행 (백필 → 분석) — 장기·멱등 resume

**Files:** 없음(실행 단계). 산출물은 `backtest_classification` 적재분 + 분석 JSON.

**근거:** ~1,838 LLM 호출은 사용량 한도(5h)로 끊긴다. 멱등이라 끊겼다 이어가면 됨(Task 5).

- [ ] **Step 1: dry-run 으로 파이프라인 점검(LLM 비용 0)**

```bash
uv run python -m kr_pipeline.backtest.profitability_cli backfill --dry-run 2>&1 | tail -5
```
Expected: `weeks` > 0, 에러 없음, `backtest_classification` 적재 0(dry-run).

- [ ] **Step 2: 실백필 시작(백그라운드, resume 가능)**

```bash
uv run python -m kr_pipeline.backtest.profitability_cli backfill 2>&1 | tee -a /tmp/bt_backfill.log
```
- 사용량 한도로 `UsageLimitError` 종료되면, 한도 리필 후 **같은 명령 재실행** → 이미 적재된 (종목,토요일) skip하고 이어감.
- 진행 확인: `psql postgresql://localhost/kr_pipeline -c "SELECT COUNT(*), COUNT(DISTINCT symbol) FROM backtest_classification WHERE source='backtest'"`

- [ ] **Step 3: 적재 완료 판정**

```bash
# 기대 적재 ≈ 1,838. 미적재 (종목,토요일)이 없을 때까지 Step 2 반복.
uv run python -m kr_pipeline.backtest.profitability_cli backfill 2>&1 | tail -3
```
Expected: 마지막 실행에서 `processed` ≈ 0, `skipped_existing` 이 대부분(= 더 채울 게 없음).

- [ ] **Step 4: 분석 실행·산출 저장**

```bash
uv run python -m kr_pipeline.backtest.profitability_cli analyze > docs/superpowers/backtest-profitability-results.json
```
Expected: `criteria.gate_defense_71`(R_down/R_up·pass), `trade_aggs`(국면별), `power_guard`.

- [ ] **Step 5: 결과 해석 문서 작성**

`docs/superpowers/backtest-profitability-results.md` 작성 — spec §7 기준으로 판정:
- §7.1 게이트 방어(1차, 깨끗): `ratio ≤ 0.5` PASS/FAIL.
- §7.2 초과수익(보조): 부호 보고하되 음수≠실패 명시.
- §7.5 검정력: 국면별 n < 10 은 underpowered 표기.
- spec §8 한계(생존편향·트리거 누수·진입일 라벨·단일시장) 재기재.

```bash
git add docs/superpowers/backtest-profitability-results.json docs/superpowers/backtest-profitability-results.md
git commit -m "docs(backtest): 수익성·강건성 결과 + 국면별 §7 판정"
```

---

## Self-Review (작성자 체크)

**Spec coverage:**
- §1 선결검증 → 이미 완료(plan 전제, Task 무관). §2 표집 → Task 4·8. §3 국면 → Task 6·7.
  §4 트리거·청산 → Task 3(테이블 파라미터) + 기존 엔진 재사용(Task 7). §5 전용테이블·멱등 →
  Task 1·2·5. §6 채점 → Task 7(`market_relative` 재사용 + 국면집계). §7 기준 → Task 7
  `evaluate_criteria`. §8 한계 → Task 9 Step 5 문서. 누락 없음.
- **§4 breakout_from_watch 시장 비게이팅**: 결정론 엔진 동작 그대로(수정 안 함) — 보수적
  하한이 의도. Task 7은 production 트레이드만 집계(기존 __main__ 패턴과 동일).
- **§7.1 분모 단위**(분류점 ≠ 트레이드): `entry_rate_by_phase`는 BT_TABLE 행 기준,
  `aggregate_trades`는 트레이드 기준 — 단위 분리 준수.

**Placeholder scan:** 모든 step에 실제 코드/명령. `<frame_size>` 등은 Task 8 Step 3 문서
템플릿의 런타임 치환값(동결 시 기록)이라 의도적.

**Type consistency:** `BT_TABLE`(Task5)→Task7 import 일치. `load_watchlist(table=)`(Task3)→
Task7 호출 일치. `insert_backfill_classification(table=)`(Task2)→Task5 호출 일치.
`phase_at`/`load_phase_map`(Task6)→Task7 일치. `entry_rates`/`trade_aggs` 구조→
`evaluate_criteria` 소비 일치.
