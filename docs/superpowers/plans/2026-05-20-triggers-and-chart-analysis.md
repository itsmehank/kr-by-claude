# Triggers 페이지 + ChartPage 분석 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** trigger_evaluation_log 데이터를 API/UI 로 노출하는 `/triggers` 페이지를 추가하고, ChartPage 에 종목별 분석 결과 (분류 / 결정론 지표 / 매수 시그널 / 성과 / 트리거 이력) 와 차트 위 overlay (pivot/stop 선 + 트리거 마커) 를 통합한다.

**Architecture:** 새 `GET /api/triggers` 라우터 (날짜/종목/decision/trigger_type 필터, stocks 조인, daily_indicators 의 avg_volume_50d 비율 계산). 기존 라우터 (classifications, signals, performance/signals) 에 `ticker` 옵션 쿼리 추가. 프론트는 `/triggers` 페이지 + ChartPage 아래 분석 카드 5개 (각 자체 fetch) + PriceChart overlay 확장.

**Tech Stack:** FastAPI, psycopg, pytest, TestClient, React 19, TanStack Query, react-router-dom, recharts/d3 기반 PriceChart, Tailwind CSS, lucide-react.

**Spec:** `docs/superpowers/specs/2026-05-20-triggers-and-chart-analysis-design.md` (commit 6ed681e)

---

## File Structure

### 신규
- `api/routers/triggers.py` — `GET /api/triggers` 라우터
- `api/schemas/trigger.py` — `TriggerOut` Pydantic 스키마
- `tests/test_api_triggers.py` — triggers 라우터 테스트
- `web/src/pages/TriggersPage.tsx` — `/triggers` 페이지
- `web/src/components/panels/ClassificationCard.tsx`
- `web/src/components/panels/IndicatorsCard.tsx`
- `web/src/components/panels/EntrySignalCard.tsx`
- `web/src/components/panels/PerformanceCard.tsx`
- `web/src/components/panels/TriggerHistoryTable.tsx`

### 수정
- `api/routers/classifications.py` — `ticker` 옵션 쿼리 추가
- `api/routers/signals.py` — `ticker` 옵션 쿼리 추가
- `api/routers/performance.py` — `list_perf_signals` 에 `ticker` 옵션 쿼리 추가
- `api/main.py` — `triggers` 라우터 등록
- `tests/test_api_classifications.py` — ticker 필터 테스트 추가
- `tests/test_api_signals_performance.py` — ticker 필터 테스트 추가
- `web/src/App.tsx` — `NAV_ITEMS` 에 `/triggers` 추가, `Route` 추가
- `web/src/lib/types.ts` — `Trigger` 등 타입 추가
- `web/src/components/charts/PriceChart.tsx` — overlay props 추가
- `web/src/pages/ChartPage.tsx` — 카드 그리드 + overlay 데이터 전달 + 토글 체크박스

---

## Task 1: `GET /api/triggers` 라우터 + 스키마 + 테스트

**Files:**
- Create: `api/schemas/trigger.py`
- Create: `api/routers/triggers.py`
- Create: `tests/test_api_triggers.py`
- Modify: `api/main.py:5,31` (import + include_router)

- [ ] **Step 1: 스키마 작성**

Create `api/schemas/trigger.py`:

```python
from datetime import datetime
from pydantic import BaseModel


class TriggerOut(BaseModel):
    symbol: str
    name: str | None = None
    market: str | None = None
    evaluated_at: datetime
    trigger_type: str
    close: float | None = None
    volume: int | None = None
    avg_volume_50d_ratio: float | None = None
    pivot_price: float | None = None
    pivot_delta_pct: float | None = None
    decision: str
    confidence: float | None = None
    reasoning: str | None = None
    abort_reason: str | None = None
```

- [ ] **Step 2: 빈 라우터 파일 + main.py 등록**

Create `api/routers/triggers.py`:

```python
from datetime import date as _date
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection

from api.deps import get_conn
from api.schemas.trigger import TriggerOut


router = APIRouter(prefix="/api/triggers", tags=["triggers"])


@router.get("", response_model=list[TriggerOut])
def list_triggers(
    ticker: str | None = None,
    date: _date | None = None,
    from_: _date | None = Query(default=None, alias="from"),
    to: _date | None = None,
    decision: str | None = None,
    trigger_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
    conn: Connection = Depends(get_conn),
):
    return []
```

Modify `api/main.py:5` — add `triggers` to the import line:

```python
from api.routers import stocks, indicators, heatmap, render, prompts, runs, market_context, signals, performance, runner, pipelines, classifications, triggers
```

Modify `api/main.py:31` (after `app.include_router(classifications.router)`) — add:

```python
app.include_router(triggers.router)
```

- [ ] **Step 3: Run the empty endpoint to verify routing**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && python -c "from api.main import app; print([r.path for r in app.routes if '/triggers' in r.path])"`

Expected output: `['/api/triggers']`

- [ ] **Step 4: Write failing test — basic empty result**

Create `tests/test_api_triggers.py`:

```python
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_triggers(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override

    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'TRGTEST%'")
        cur.execute("DELETE FROM daily_indicators WHERE ticker LIKE 'TRGTEST%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'TRGTEST%'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('TRGTEST01','Test1','KOSPI','반도체','2020-01-01'),
                      ('TRGTEST02','Test2','KOSDAQ','보험','2020-01-01')"""
        )
        cur.execute(
            """INSERT INTO daily_indicators
                 (ticker, date, open, high, low, close, adj_close, volume, avg_volume_50d)
               VALUES
                 ('TRGTEST01', '2026-05-20', 80000, 85000, 80000, 84000, 84000, 12000000, 6600000),
                 ('TRGTEST02', '2026-05-19', 30000, 31000, 29800, 30200, 30200,  3000000, 2500000)"""
        )
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, confidence, reasoning, prior_classification_at)
               VALUES
                 ('TRGTEST01', '2026-05-20 09:32:12+09', 'breakout',
                  84000, 12000000, 82300, 'go_now', 0.78, '거래량 증가와 함께 …',
                  '2026-05-17 10:00:00+09'),
                 ('TRGTEST02', '2026-05-19 09:35:00+09', 'invalidation',
                  30200, 3000000, 32100, 'abort', 0.65, '손절 가격 하향 이탈',
                  '2026-05-17 10:00:00+09')"""
        )
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_empty_when_no_filter_matches(client, seed_triggers):
    r = client.get("/api/triggers?ticker=NOSUCH")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_triggers.py::test_empty_when_no_filter_matches -v`

Expected: PASS (empty endpoint returns `[]`, no ticker rows match). This locks in the contract before adding real queries.

- [ ] **Step 6: Write failing test — basic non-empty + stocks join**

Add to `tests/test_api_triggers.py`:

```python
def test_returns_triggers_with_stocks_join(client, seed_triggers):
    r = client.get("/api/triggers?ticker=TRGTEST01")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    row = data[0]
    assert row["symbol"] == "TRGTEST01"
    assert row["name"] == "Test1"
    assert row["market"] == "KOSPI"
    assert row["trigger_type"] == "breakout"
    assert row["decision"] == "go_now"
    assert row["close"] == 84000.0
    assert row["pivot_price"] == 82300.0
    assert row["confidence"] == 0.78


def test_volume_ratio_and_pivot_delta_calculated(client, seed_triggers):
    r = client.get("/api/triggers?ticker=TRGTEST01")
    row = r.json()[0]
    # avg_volume_50d_ratio = 12000000 / 6600000 ≈ 1.818
    assert row["avg_volume_50d_ratio"] == pytest.approx(1.818, rel=0.01)
    # pivot_delta_pct = (84000 - 82300) / 82300 * 100 ≈ 2.066
    assert row["pivot_delta_pct"] == pytest.approx(2.066, rel=0.01)
```

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_triggers.py::test_returns_triggers_with_stocks_join tests/test_api_triggers.py::test_volume_ratio_and_pivot_delta_calculated -v`

Expected: FAIL — empty list.

- [ ] **Step 7: Implement query — full SQL + filter binding**

Replace `api/routers/triggers.py` content:

```python
from datetime import date as _date
from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from api.deps import get_conn
from api.schemas.trigger import TriggerOut


router = APIRouter(prefix="/api/triggers", tags=["triggers"])


@router.get("", response_model=list[TriggerOut])
def list_triggers(
    ticker: str | None = None,
    date: _date | None = None,
    from_: _date | None = Query(default=None, alias="from"),
    to: _date | None = None,
    decision: str | None = None,
    trigger_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
    conn: Connection = Depends(get_conn),
):
    if limit > 1000:
        limit = 1000

    sql = """
        SELECT t.symbol, s.name, s.market,
               t.evaluated_at, t.trigger_type,
               t.close, t.volume, t.pivot_price,
               di.avg_volume_50d,
               t.decision, t.confidence, t.reasoning, t.abort_reason
          FROM trigger_evaluation_log t
          LEFT JOIN stocks s ON s.ticker = t.symbol
          LEFT JOIN daily_indicators di
                 ON di.ticker = t.symbol
                AND di.date = (t.evaluated_at AT TIME ZONE 'Asia/Seoul')::date
         WHERE (%(ticker)s::text   IS NULL OR t.symbol = %(ticker)s)
           AND (%(date)s::date     IS NULL OR (t.evaluated_at AT TIME ZONE 'Asia/Seoul')::date = %(date)s)
           AND (%(from_)s::date    IS NULL OR (t.evaluated_at AT TIME ZONE 'Asia/Seoul')::date >= %(from_)s)
           AND (%(to)s::date       IS NULL OR (t.evaluated_at AT TIME ZONE 'Asia/Seoul')::date <= %(to)s)
           AND (%(decision)s::text IS NULL OR t.decision = %(decision)s)
           AND (%(trigger_type)s::text IS NULL OR t.trigger_type = %(trigger_type)s)
         ORDER BY t.evaluated_at DESC
         LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {
        "ticker": ticker,
        "date": date,
        "from_": from_,
        "to": to,
        "decision": decision,
        "trigger_type": trigger_type,
        "limit": limit,
        "offset": offset,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    result: list[TriggerOut] = []
    for r in rows:
        close = float(r[5]) if r[5] is not None else None
        volume = int(r[6]) if r[6] is not None else None
        pivot = float(r[7]) if r[7] is not None else None
        avg_vol = float(r[8]) if r[8] is not None else None

        vol_ratio = (volume / avg_vol) if (volume is not None and avg_vol and avg_vol > 0) else None
        pivot_delta = ((close - pivot) / pivot * 100.0) if (close is not None and pivot is not None and pivot > 0) else None

        result.append(TriggerOut(
            symbol=r[0],
            name=r[1],
            market=r[2],
            evaluated_at=r[3],
            trigger_type=r[4],
            close=close,
            volume=volume,
            pivot_price=pivot,
            avg_volume_50d_ratio=vol_ratio,
            pivot_delta_pct=pivot_delta,
            decision=r[9],
            confidence=float(r[10]) if r[10] is not None else None,
            reasoning=r[11],
            abort_reason=r[12],
        ))
    return result
```

- [ ] **Step 8: Run the two basic tests to verify they pass**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_triggers.py -v`

Expected: 3/3 PASS (empty + join + ratio/delta).

- [ ] **Step 9: Write failing tests — filters**

Append to `tests/test_api_triggers.py`:

```python
def test_date_filter(client, seed_triggers):
    r = client.get("/api/triggers?date=2026-05-20")
    syms = {row["symbol"] for row in r.json() if row["symbol"].startswith("TRGTEST")}
    assert syms == {"TRGTEST01"}


def test_from_to_range(client, seed_triggers):
    r = client.get("/api/triggers?from=2026-05-19&to=2026-05-19")
    syms = {row["symbol"] for row in r.json() if row["symbol"].startswith("TRGTEST")}
    assert syms == {"TRGTEST02"}


def test_decision_filter(client, seed_triggers):
    r = client.get("/api/triggers?decision=go_now")
    test_rows = [row for row in r.json() if row["symbol"].startswith("TRGTEST")]
    for row in test_rows:
        assert row["decision"] == "go_now"
    assert {row["symbol"] for row in test_rows} == {"TRGTEST01"}


def test_trigger_type_filter(client, seed_triggers):
    r = client.get("/api/triggers?trigger_type=invalidation")
    test_rows = [row for row in r.json() if row["symbol"].startswith("TRGTEST")]
    assert {row["symbol"] for row in test_rows} == {"TRGTEST02"}


def test_combined_filters(client, seed_triggers):
    r = client.get("/api/triggers?from=2026-05-20&to=2026-05-20&decision=go_now")
    syms = {row["symbol"] for row in r.json() if row["symbol"].startswith("TRGTEST")}
    assert syms == {"TRGTEST01"}


def test_order_evaluated_at_desc(client, seed_triggers):
    r = client.get("/api/triggers?from=2026-05-19&to=2026-05-20")
    test_rows = [row for row in r.json() if row["symbol"].startswith("TRGTEST")]
    assert test_rows[0]["symbol"] == "TRGTEST01"
    assert test_rows[1]["symbol"] == "TRGTEST02"


def test_limit_and_offset(client, seed_triggers):
    r1 = client.get("/api/triggers?from=2026-05-19&to=2026-05-20&limit=1&offset=0")
    r2 = client.get("/api/triggers?from=2026-05-19&to=2026-05-20&limit=1&offset=1")
    test_r1 = [row for row in r1.json() if row["symbol"].startswith("TRGTEST")]
    test_r2 = [row for row in r2.json() if row["symbol"].startswith("TRGTEST")]
    assert len(test_r1) == 1 and len(test_r2) == 1
    assert test_r1[0]["symbol"] != test_r2[0]["symbol"]
```

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_triggers.py -v`

Expected: All 10 PASS (3 prior + 7 new). The implementation in Step 7 already handles them; if any fail, fix the SQL and re-run.

- [ ] **Step 10: Commit**

```bash
git add api/schemas/trigger.py api/routers/triggers.py api/main.py tests/test_api_triggers.py
git commit -m "feat: add GET /api/triggers endpoint for trigger_evaluation_log

종목/날짜/decision/trigger_type 필터, stocks 조인, daily_indicators 의
avg_volume_50d 비율 + pivot_price 대비 % 응답 시 계산."
```

---

## Task 2: 기존 endpoint 에 `ticker` 옵션 쿼리 추가

**Files:**
- Modify: `api/routers/classifications.py:18-64`
- Modify: `api/routers/signals.py:12-30`
- Modify: `api/routers/performance.py:38-52`
- Modify: `tests/test_api_classifications.py` (테스트 추가)
- Modify: `tests/test_api_signals_performance.py` (테스트 추가)

- [ ] **Step 1: Write failing test — classifications?ticker=**

Append to `tests/test_api_classifications.py`:

```python
def test_ticker_filter_returns_only_that_symbol(client, seed_classifications):
    r = client.get("/api/classifications?lookback_days=30&ticker=CLSTEST02")
    rows = r.json()
    assert {row["symbol"] for row in rows} == {"CLSTEST02"}
    assert len(rows) == 1
```

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_classifications.py::test_ticker_filter_returns_only_that_symbol -v`

Expected: FAIL — ticker param not yet recognized; all 3 test rows returned.

- [ ] **Step 2: Add `ticker` param + WHERE clause to classifications.py**

In `api/routers/classifications.py`, modify the signature (line 18-26) to add `ticker`:

```python
@router.get("", response_model=list[ClassificationRow])
def get_classifications(
    lookback_days: int = 14,
    ticker: str | None = None,
    classifications: list[str] | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
    min_confidence: float = 0.0,
    sort: str = "classified_at_desc",
    limit: int = 100,
    conn: Connection = Depends(get_conn),
):
```

In the SQL `WHERE` (after the latest CTE inner WHERE at line 40), add to the CTE filter:

```sql
           WHERE classified_at >= NOW() - (%(lookback_days)s || ' days')::interval
             AND (%(ticker)s::text IS NULL OR symbol = %(ticker)s)
```

In `params` dict (line 58-63), add:

```python
        "ticker": ticker,
```

- [ ] **Step 3: Run classifications tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_classifications.py -v`

Expected: All previous PASS + new ticker test PASS.

- [ ] **Step 4: Write failing test — signals?ticker=**

Append to `tests/test_api_signals_performance.py` (확인 후 적절한 위치). 먼저 기존 signals 테스트 fixture 가 있는지 확인 — 없으면 새로 작성:

```python
def test_signals_ticker_filter(client, db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM signal_performance WHERE symbol LIKE 'SIGTKR%'")
            cur.execute("DELETE FROM entry_params WHERE symbol LIKE 'SIGTKR%'")
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'SIGTKR%'")
            cur.execute(
                """INSERT INTO stocks (ticker, name, market, sector, listed_at)
                   VALUES ('SIGTKR01','T1','KOSPI','반도체','2020-01-01'),
                          ('SIGTKR02','T2','KOSPI','보험','2020-01-01')"""
            )
            cur.execute(
                """INSERT INTO entry_params
                     (symbol, signal_at, entry_price, stop_loss,
                      trigger_evaluation_at, prior_classification_at)
                   VALUES
                     ('SIGTKR01', NOW() - INTERVAL '1 day', 100, 90, NOW(), NOW()),
                     ('SIGTKR02', NOW() - INTERVAL '1 day', 200, 180, NOW(), NOW())"""
            )
        db.commit()
        r = client.get("/api/signals?ticker=SIGTKR01&days=7")
        syms = {row["symbol"] for row in r.json()}
        assert syms == {"SIGTKR01"}
    finally:
        app.dependency_overrides.pop(get_conn, None)
```

(이 테스트가 의존하는 `client` fixture / import 가 파일 상단에 없으면 추가:)

```python
import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)
```

- [ ] **Step 5: Run signals ticker test to verify it fails**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_signals_performance.py::test_signals_ticker_filter -v`

Expected: FAIL — ticker param ignored.

- [ ] **Step 6: Add `ticker` param to signals.py**

In `api/routers/signals.py`, replace function (line 12-29):

```python
@router.get("", response_model=list[SignalOut])
def list_signals(
    days: int = 5,
    ticker: str | None = None,
    conn: Connection = Depends(get_conn),
):
    cutoff = date.today() - timedelta(days=days)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ep.symbol, s.name, s.sector, s.market,
                   ep.signal_at, ep.entry_mode, ep.trigger_price, ep.entry_price,
                   ep.stop_loss, ep.stop_loss_pct_from_pivot, ep.stop_loss_pct_from_current_price,
                   ep.expected_target_price, ep.expected_target_pct, ep.risk_reward_ratio,
                   ep.position_size_pct, ep.known_warnings, ep.notes
              FROM entry_params ep
              JOIN stocks s ON s.ticker = ep.symbol
             WHERE ep.signal_at::date >= %s
               AND (%s::text IS NULL OR ep.symbol = %s)
             ORDER BY ep.signal_at DESC
            """,
            (cutoff, ticker, ticker),
        )
        rows = cur.fetchall()
```

- [ ] **Step 7: Run signals tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_signals_performance.py -v`

Expected: All PASS.

- [ ] **Step 8: Write failing test — performance/signals?ticker=**

Append to `tests/test_api_signals_performance.py`:

```python
def test_performance_signals_ticker_filter(client, db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM signal_performance WHERE symbol LIKE 'PERFTKR%'")
            cur.execute("DELETE FROM entry_params WHERE symbol LIKE 'PERFTKR%'")
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'PERFTKR%'")
            cur.execute(
                """INSERT INTO stocks (ticker, name, market, sector, listed_at)
                   VALUES ('PERFTKR01','T1','KOSPI','반도체','2020-01-01'),
                          ('PERFTKR02','T2','KOSPI','보험','2020-01-01')"""
            )
            cur.execute(
                """INSERT INTO entry_params
                     (symbol, signal_at, entry_price, stop_loss,
                      trigger_evaluation_at, prior_classification_at)
                   VALUES
                     ('PERFTKR01', NOW() - INTERVAL '7 day', 100, 90, NOW(), NOW()),
                     ('PERFTKR02', NOW() - INTERVAL '7 day', 200, 180, NOW(), NOW())"""
            )
            cur.execute(
                """INSERT INTO signal_performance
                     (symbol, signal_at, entry_price, return_2w_pct)
                   VALUES
                     ('PERFTKR01', (SELECT signal_at FROM entry_params WHERE symbol='PERFTKR01'), 100, 5.0),
                     ('PERFTKR02', (SELECT signal_at FROM entry_params WHERE symbol='PERFTKR02'), 200, -3.0)"""
            )
        db.commit()
        r = client.get("/api/performance/signals?ticker=PERFTKR01")
        syms = {row["symbol"] for row in r.json()}
        assert syms == {"PERFTKR01"}
    finally:
        app.dependency_overrides.pop(get_conn, None)
```

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_signals_performance.py::test_performance_signals_ticker_filter -v`

Expected: FAIL.

- [ ] **Step 9: Add `ticker` param to performance.py**

In `api/routers/performance.py`, replace function (line 38-52):

```python
@router.get("/signals")
def list_perf_signals(
    limit: int = 50,
    ticker: str | None = None,
    conn: Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sp.symbol, s.name, sp.signal_at, sp.entry_price,
                   sp.return_1w_pct, sp.return_2w_pct, sp.return_4w_pct, sp.return_8w_pct,
                   sp.market_return_1w_pct, sp.market_return_2w_pct,
                   sp.market_return_4w_pct, sp.market_return_8w_pct
              FROM signal_performance sp
              JOIN stocks s ON s.ticker = sp.symbol
             WHERE (%s::text IS NULL OR sp.symbol = %s)
             ORDER BY sp.signal_at DESC LIMIT %s
            """,
            (ticker, ticker, limit),
        )
        rows = cur.fetchall()
```

- [ ] **Step 10: Run all performance tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && pytest tests/test_api_signals_performance.py -v`

Expected: All PASS.

- [ ] **Step 11: Commit**

```bash
git add api/routers/classifications.py api/routers/signals.py api/routers/performance.py tests/test_api_classifications.py tests/test_api_signals_performance.py
git commit -m "feat: add ticker query filter to classifications/signals/performance

ChartPage 의 종목별 분석 카드들이 사용할 종목 단위 fetch 지원."
```

---

## Task 3: `/triggers` 페이지

**Files:**
- Modify: `web/src/lib/types.ts` (`Trigger` 타입 추가)
- Modify: `web/src/App.tsx:38-49` (NAV_ITEMS), `:181-195` (Routes)
- Create: `web/src/pages/TriggersPage.tsx`

- [ ] **Step 1: Add Trigger type**

Open `web/src/lib/types.ts` and append:

```ts
export type TriggerDecision = "go_now" | "wait" | "abort";

export interface Trigger {
  symbol: string;
  name: string | null;
  market: string | null;
  evaluated_at: string;          // ISO timestamp
  trigger_type: string;
  close: number | null;
  volume: number | null;
  avg_volume_50d_ratio: number | null;
  pivot_price: number | null;
  pivot_delta_pct: number | null;
  decision: TriggerDecision;
  confidence: number | null;
  reasoning: string | null;
  abort_reason: string | null;
}
```

- [ ] **Step 2: Add NAV item + Route**

In `web/src/App.tsx`, line 1-7 region — append `Activity` to the lucide-react import:

```tsx
import {
  // ... existing imports ...
  Activity,
} from "lucide-react";
```

(만약 file 의 lucide-react import 가 named 가 아니라면 그 파일 본래 패턴 따라.)

In `NAV_ITEMS` (line 38-49), add between `Classifications` and `LLM Pipeline Guide`:

```tsx
{ to: "/classifications", label: "Classifications", kr: "LLM 분류", Icon: ListChecks },
{ to: "/triggers", label: "Triggers", kr: "트리거 이력", Icon: Activity },
{ to: "/docs/llm-pipeline", label: "LLM Pipeline Guide", kr: "LLM 분석 안내", Icon: BookOpen },
```

In Routes (line 181-195), add after `/classifications`:

```tsx
<Route path="/classifications" element={<ClassificationsPage />} />
<Route path="/triggers" element={<TriggersPage />} />
```

Add the import near other page imports at the top of `App.tsx`:

```tsx
import TriggersPage from "./pages/TriggersPage";
```

- [ ] **Step 3: Create skeleton TriggersPage**

Create `web/src/pages/TriggersPage.tsx`:

```tsx
import { useMemo, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Trigger, TriggerDecision } from "../lib/types";

const DECISIONS: { value: ""; label: string }[] | { value: TriggerDecision | ""; label: string }[] = [
  { value: "", label: "전체" },
  { value: "go_now", label: "go_now" },
  { value: "wait", label: "wait" },
  { value: "abort", label: "abort" },
];

const TRIGGER_TYPES: { value: ""; label: string }[] | { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "breakout", label: "breakout" },
  { value: "promotion", label: "promotion" },
  { value: "invalidation", label: "invalidation" },
];

function defaultFrom(): string {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function TriggersPage() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();

  const ticker = sp.get("ticker") ?? "";
  const decision = sp.get("decision") ?? "";
  const triggerType = sp.get("trigger_type") ?? "";
  const from = sp.get("from") ?? defaultFrom();
  const to = sp.get("to") ?? todayStr();

  function updateParam(key: string, value: string) {
    const next = new URLSearchParams(sp);
    if (value) next.set(key, value);
    else next.delete(key);
    setSp(next);
  }

  const q = useQuery<Trigger[]>({
    queryKey: ["triggers", { ticker, decision, triggerType, from, to }],
    queryFn: () => {
      const params = new URLSearchParams();
      if (ticker) params.set("ticker", ticker);
      if (decision) params.set("decision", decision);
      if (triggerType) params.set("trigger_type", triggerType);
      if (from) params.set("from", from);
      if (to) params.set("to", to);
      params.set("limit", "500");
      return api<Trigger[]>(`/triggers?${params.toString()}`);
    },
  });

  const groupedByDate = useMemo(() => {
    const map = new Map<string, Trigger[]>();
    for (const t of q.data ?? []) {
      const d = t.evaluated_at.slice(0, 10);
      const arr = map.get(d) ?? [];
      arr.push(t);
      map.set(d, arr);
    }
    return Array.from(map.entries()).sort(([a], [b]) => b.localeCompare(a));
  }, [q.data]);

  return (
    <div className="px-8 py-6">
      <h1 className="font-display text-display-md font-bold mb-6">트리거 이력</h1>

      <div className="flex flex-wrap gap-3 mb-6 items-end">
        <div>
          <label className="caps block mb-1">종목</label>
          <input
            type="text"
            value={ticker}
            placeholder="예: 005930"
            onChange={(e) => updateParam("ticker", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          />
        </div>
        <div>
          <label className="caps block mb-1">decision</label>
          <select
            value={decision}
            onChange={(e) => updateParam("decision", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          >
            {DECISIONS.map((d) => (
              <option key={d.value} value={d.value}>{d.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="caps block mb-1">trigger_type</label>
          <select
            value={triggerType}
            onChange={(e) => updateParam("trigger_type", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          >
            {TRIGGER_TYPES.map((d) => (
              <option key={d.value} value={d.value}>{d.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="caps block mb-1">from</label>
          <input
            type="date"
            value={from}
            onChange={(e) => updateParam("from", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          />
        </div>
        <div>
          <label className="caps block mb-1">to</label>
          <input
            type="date"
            value={to}
            onChange={(e) => updateParam("to", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          />
        </div>
      </div>

      {q.isLoading && <div className="text-muted">불러오는 중…</div>}
      {q.isError && <div className="text-red-600">불러오기 실패</div>}
      {q.data && q.data.length === 0 && (
        <div className="text-muted">필터에 해당하는 트리거 평가 이력이 없습니다.</div>
      )}

      {groupedByDate.map(([date, rows]) => {
        const go = rows.filter((r) => r.decision === "go_now").length;
        const wait = rows.filter((r) => r.decision === "wait").length;
        const abort = rows.filter((r) => r.decision === "abort").length;
        return (
          <section key={date} className="mb-6 border border-hairline rounded-xl overflow-hidden">
            <header className="px-4 py-2 bg-paper flex justify-between text-data">
              <span className="font-semibold">{date}</span>
              <span className="text-muted">
                {rows.length} 건 · go {go} / wait {wait} / abort {abort}
              </span>
            </header>
            <table className="w-full text-data">
              <thead className="bg-paper/60 text-faint">
                <tr>
                  <th className="text-left px-3 py-1.5">종목</th>
                  <th className="text-left px-3 py-1.5">트리거</th>
                  <th className="text-left px-3 py-1.5">decision</th>
                  <th className="text-right px-3 py-1.5">거래량비</th>
                  <th className="text-right px-3 py-1.5">pivot대비</th>
                  <th className="text-left px-3 py-1.5">reasoning</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr
                    key={`${t.symbol}-${t.evaluated_at}`}
                    onClick={() => navigate(`/chart/${t.symbol}`)}
                    className="border-t border-hairline cursor-pointer hover:bg-paper/40"
                  >
                    <td className="px-3 py-1.5 font-semibold">
                      {t.symbol} <span className="text-muted">{t.name}</span>
                    </td>
                    <td className="px-3 py-1.5">{t.trigger_type}</td>
                    <td className="px-3 py-1.5">
                      <DecisionPill decision={t.decision} />
                    </td>
                    <td className="px-3 py-1.5 text-right num">
                      {t.avg_volume_50d_ratio != null ? `${t.avg_volume_50d_ratio.toFixed(2)}×` : "—"}
                    </td>
                    <td className="px-3 py-1.5 text-right num">
                      {t.pivot_delta_pct != null
                        ? `${t.pivot_delta_pct >= 0 ? "+" : ""}${t.pivot_delta_pct.toFixed(2)}%`
                        : "—"}
                    </td>
                    <td className="px-3 py-1.5 text-muted truncate max-w-md" title={t.reasoning ?? ""}>
                      {t.reasoning ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        );
      })}
    </div>
  );
}

function DecisionPill({ decision }: { decision: TriggerDecision }) {
  const cfg = {
    go_now: { bg: "bg-green-100", text: "text-green-800", dot: "bg-green-500" },
    wait:   { bg: "bg-yellow-100", text: "text-yellow-800", dot: "bg-yellow-500" },
    abort:  { bg: "bg-gray-200", text: "text-gray-700", dot: "bg-gray-500" },
  }[decision];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded ${cfg.bg} ${cfg.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
      {decision}
    </span>
  );
}
```

- [ ] **Step 4: Type-check the frontend**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npm run build`

Expected: build succeeds (or `tsc --noEmit` if configured). No type errors.

- [ ] **Step 5: Manual smoke test**

Start dev server: `cd /Users/hank.es/git/personal/kr-by-claude/web && npm run dev`

In a browser open `http://localhost:5173/triggers` and verify:
- 사이드바에 "트리거 이력" 항목이 보인다
- 페이지가 로딩 → 데이터 없으면 빈 상태 메시지
- DB 에 trigger_evaluation_log 행이 있으면 날짜 그룹 헤더 + 테이블이 보인다
- 필터 변경 시 URL 쿼리 파라미터가 갱신되고 결과가 다시 그려진다
- 행 클릭 시 `/chart/{ticker}` 로 이동한다

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/types.ts web/src/App.tsx web/src/pages/TriggersPage.tsx
git commit -m "feat: add /triggers page for trigger_evaluation_log

날짜 그룹 + 필터 (종목/decision/trigger_type/기간). 행 클릭 시 ChartPage 로
이동. URL 쿼리 파라미터로 필터 상태 유지."
```

---

## Task 4: 분석 카드 5개 컴포넌트

각 카드는 자체 `useQuery` 로 fetch. `ticker: string` 만 prop.

**Files:**
- Modify: `web/src/lib/types.ts` (필요 타입 확인 + 누락 시 추가)
- Create: `web/src/components/panels/ClassificationCard.tsx`
- Create: `web/src/components/panels/IndicatorsCard.tsx`
- Create: `web/src/components/panels/EntrySignalCard.tsx`
- Create: `web/src/components/panels/PerformanceCard.tsx`
- Create: `web/src/components/panels/TriggerHistoryTable.tsx`

- [ ] **Step 1: Audit existing types and add missing ones**

Open `web/src/lib/types.ts`. Verify these types exist (from prior work on ClassificationsPage / SignalsPage). If any is missing or incomplete, add:

```ts
export interface Classification {
  symbol: string;
  name: string | null;
  market: string | null;
  sector: string | null;
  classification: string;
  pattern: string | null;
  pivot_price: number | null;
  pivot_basis: string | null;
  base_high: number | null;
  base_low: number | null;
  base_depth_pct: number | null;
  base_start_date: string | null;     // YYYY-MM-DD
  risk_flags: string[];
  confidence: number | null;
  reasoning: string | null;
  source: string;
  classified_at: string;
  analyzed_for_date: string | null;
}

export interface Signal {
  symbol: string;
  name: string | null;
  sector: string | null;
  market: string | null;
  signal_at: string;
  entry_mode: string | null;
  trigger_price: number | null;
  entry_price: number;
  stop_loss: number;
  stop_loss_pct_from_pivot: number | null;
  stop_loss_pct_from_current_price: number | null;
  expected_target_price: number | null;
  expected_target_pct: number | null;
  risk_reward_ratio: number | null;
  position_size_pct: number | null;
  known_warnings: string[];
  notes: string | null;
}

export interface PerformanceSignal {
  symbol: string;
  name: string | null;
  signal_at: string;
  entry_price: number;
  return_1w_pct: number | null;
  return_2w_pct: number | null;
  return_4w_pct: number | null;
  return_8w_pct: number | null;
  market_return_1w_pct: number | null;
  market_return_2w_pct: number | null;
  market_return_4w_pct: number | null;
  market_return_8w_pct: number | null;
}
```

- [ ] **Step 2: Create ClassificationCard**

Create `web/src/components/panels/ClassificationCard.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import { api } from "../../lib/api";
import type { Classification } from "../../lib/types";

interface Props { ticker: string }

const CLASSIFICATION_COLOR: Record<string, string> = {
  entry: "bg-green-100 text-green-800",
  watch: "bg-blue-100 text-blue-800",
  ignore: "bg-gray-200 text-gray-700",
};

export function ClassificationCard({ ticker }: Props) {
  const q = useQuery<Classification[]>({
    queryKey: ["classification-card", ticker],
    queryFn: () => api<Classification[]>(`/classifications?ticker=${ticker}&lookback_days=60&limit=1`),
    enabled: !!ticker,
  });

  if (q.isLoading) return <Card title="분류">불러오는 중…</Card>;
  if (q.isError || !q.data || q.data.length === 0) {
    return <Card title="분류">최근 60일 분류 이력 없음</Card>;
  }

  const c = q.data[0];
  const baseEnd = c.analyzed_for_date ?? c.classified_at.slice(0, 10);
  const baseStart = c.base_start_date;
  const baseWeeks = baseStart && baseEnd
    ? Math.round((new Date(baseEnd).getTime() - new Date(baseStart).getTime()) / (7 * 24 * 60 * 60 * 1000))
    : null;

  return (
    <Card title="분류">
      <div className="space-y-2 text-data">
        <div className="flex items-center gap-2">
          <span className={`px-2 py-0.5 rounded ${CLASSIFICATION_COLOR[c.classification] ?? "bg-gray-100"}`}>
            {c.classification}
          </span>
          {c.pattern && <span className="text-muted">{c.pattern}</span>}
        </div>
        <div>
          <span className="caps text-faint">Base 기간</span>{" "}
          {baseStart ? `${baseStart} ~ ${baseEnd}${baseWeeks ? ` (${baseWeeks}주)` : ""}` : "—"}
        </div>
        <div>
          <span className="caps text-faint">Base 가격대</span>{" "}
          {c.base_low != null && c.base_high != null
            ? `${c.base_low.toLocaleString()} ~ ${c.base_high.toLocaleString()}원`
            : "—"}
        </div>
        <div>
          <span className="caps text-faint">Base 깊이</span>{" "}
          {c.base_depth_pct != null ? `${c.base_depth_pct.toFixed(2)}%` : "—"}
        </div>
        <div>
          <span className="caps text-faint">Pivot</span>{" "}
          {c.pivot_price != null ? `${c.pivot_price.toLocaleString()}원` : "—"}
          {c.pivot_basis && <span className="text-faint"> ({c.pivot_basis})</span>}
        </div>
        {c.risk_flags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {c.risk_flags.map((f) => (
              <span key={f} className="px-2 py-0.5 rounded bg-red-50 text-red-700 text-data-xs">
                {f}
              </span>
            ))}
          </div>
        )}
        {c.reasoning && (
          <div className="prose prose-sm max-w-none text-muted">
            <ReactMarkdown>{c.reasoning}</ReactMarkdown>
          </div>
        )}
      </div>
    </Card>
  );
}

export function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-paper border border-hairline rounded-xl p-4 shadow-bento">
      <h3 className="caps text-faint mb-3">{title}</h3>
      {children}
    </div>
  );
}
```

- [ ] **Step 3: Create IndicatorsCard**

Create `web/src/components/panels/IndicatorsCard.tsx`. minervini-detail endpoint 가 8조건 + drawdown + RS 를 모두 반환한다고 가정 (별도 spec 검증 없이 응답 키 추정; 실제 응답이 다르면 build 실패 → 조정).

```tsx
import { useQuery } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { api } from "../../lib/api";
import { Card } from "./ClassificationCard";

interface MinerviniDetail {
  ticker: string;
  date: string;
  rs_rating: number | null;
  drawdown_filter: boolean | null;
  conditions: {
    c1_above_sma150: boolean | null;
    c2_above_sma200: boolean | null;
    c3_sma150_above_sma200: boolean | null;
    c4_sma200_uptrend: boolean | null;
    c5_sma50_above_sma150: boolean | null;
    c6_price_above_sma50: boolean | null;
    c7_price_30pct_above_52w_low: boolean | null;
    c8_price_within_25pct_of_52w_high: boolean | null;
  };
}

interface Props { ticker: string }

const COND_LABELS: { key: keyof MinerviniDetail["conditions"]; label: string }[] = [
  { key: "c1_above_sma150", label: "주가 > SMA150" },
  { key: "c2_above_sma200", label: "주가 > SMA200" },
  { key: "c3_sma150_above_sma200", label: "SMA150 > SMA200" },
  { key: "c4_sma200_uptrend", label: "SMA200 상승" },
  { key: "c5_sma50_above_sma150", label: "SMA50 > SMA150" },
  { key: "c6_price_above_sma50", label: "주가 > SMA50" },
  { key: "c7_price_30pct_above_52w_low", label: "52w저점 +30% 이상" },
  { key: "c8_price_within_25pct_of_52w_high", label: "52w고점 -25% 이내" },
];

export function IndicatorsCard({ ticker }: Props) {
  const q = useQuery<MinerviniDetail>({
    queryKey: ["minervini-detail", ticker],
    queryFn: () => api<MinerviniDetail>(`/indicators/minervini-detail/${ticker}`),
    enabled: !!ticker,
    retry: false,
  });

  if (q.isLoading) return <Card title="결정론 지표">불러오는 중…</Card>;
  if (q.isError || !q.data) return <Card title="결정론 지표">데이터 없음</Card>;

  const d = q.data;

  return (
    <Card title="결정론 지표">
      <div className="space-y-3 text-data">
        <div className="flex items-baseline gap-2">
          <span className="caps text-faint">RS Rating</span>
          <span className="text-display-sm font-bold num">{d.rs_rating ?? "—"}</span>
        </div>
        <div>
          <span className="caps text-faint">Drawdown filter</span>{" "}
          {d.drawdown_filter == null
            ? "—"
            : d.drawdown_filter ? (
              <span className="text-green-700">통과</span>
            ) : (
              <span className="text-red-700">실패</span>
            )}
        </div>
        <div>
          <div className="caps text-faint mb-1">Minervini 8조건</div>
          <ul className="space-y-1">
            {COND_LABELS.map(({ key, label }) => {
              const v = d.conditions?.[key];
              return (
                <li key={key} className="flex items-center gap-2">
                  {v ? (
                    <Check size={14} className="text-green-600" />
                  ) : (
                    <X size={14} className="text-red-500" />
                  )}
                  <span className={v ? "" : "text-muted"}>{label}</span>
                </li>
              );
            })}
          </ul>
        </div>
        <div className="text-faint text-data-xs">기준일: {d.date}</div>
      </div>
    </Card>
  );
}
```

- [ ] **Step 4: Create EntrySignalCard**

Create `web/src/components/panels/EntrySignalCard.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { Signal } from "../../lib/types";
import { Card } from "./ClassificationCard";

interface Props { ticker: string }

export function EntrySignalCard({ ticker }: Props) {
  const q = useQuery<Signal[]>({
    queryKey: ["entry-signal-card", ticker],
    queryFn: () => api<Signal[]>(`/signals?ticker=${ticker}&days=60`),
    enabled: !!ticker,
  });

  if (q.isLoading) return <Card title="매수 시그널">불러오는 중…</Card>;
  if (q.isError || !q.data || q.data.length === 0) {
    return (
      <Card title="매수 시그널">
        <div className="text-muted">아직 매수 시그널이 발생하지 않았습니다.</div>
        <div className="text-faint text-data-xs mt-2">트리거 이력 표에서 평가 과정을 확인하세요.</div>
      </Card>
    );
  }
  const s = q.data[0];

  return (
    <Card title="매수 시그널">
      <div className="space-y-2 text-data">
        <div className="text-faint text-data-xs">{s.signal_at.slice(0, 19).replace("T", " ")}</div>
        {s.entry_mode && <div><span className="caps text-faint">진입 모드</span> {s.entry_mode}</div>}
        <div>
          <span className="caps text-faint">진입가</span>{" "}
          <span className="num font-semibold">{s.entry_price.toLocaleString()}원</span>
        </div>
        <div>
          <span className="caps text-faint">손절가</span>{" "}
          <span className="num">{s.stop_loss.toLocaleString()}원</span>
          {s.stop_loss_pct_from_current_price != null && (
            <span className="text-faint"> ({s.stop_loss_pct_from_current_price.toFixed(2)}%)</span>
          )}
        </div>
        {s.expected_target_price != null && (
          <div>
            <span className="caps text-faint">목표가</span>{" "}
            <span className="num">{s.expected_target_price.toLocaleString()}원</span>
            {s.expected_target_pct != null && (
              <span className="text-faint"> (+{s.expected_target_pct.toFixed(2)}%)</span>
            )}
          </div>
        )}
        {s.risk_reward_ratio != null && (
          <div>
            <span className="caps text-faint">R/R</span>{" "}
            <span className="num">{s.risk_reward_ratio.toFixed(2)}</span>
          </div>
        )}
        {s.known_warnings.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {s.known_warnings.map((w) => (
              <span key={w} className="px-2 py-0.5 rounded bg-yellow-50 text-yellow-800 text-data-xs">
                {w}
              </span>
            ))}
          </div>
        )}
        {s.notes && <div className="text-muted text-data-xs">{s.notes}</div>}
      </div>
    </Card>
  );
}
```

- [ ] **Step 5: Create PerformanceCard**

Create `web/src/components/panels/PerformanceCard.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import type { PerformanceSignal } from "../../lib/types";
import { Card } from "./ClassificationCard";

interface Props { ticker: string }

const PERIODS = [
  { key: "1w", label: "1주" },
  { key: "2w", label: "2주" },
  { key: "4w", label: "4주" },
  { key: "8w", label: "8주" },
] as const;

export function PerformanceCard({ ticker }: Props) {
  const q = useQuery<PerformanceSignal[]>({
    queryKey: ["performance-card", ticker],
    queryFn: () => api<PerformanceSignal[]>(`/performance/signals?ticker=${ticker}&limit=1`),
    enabled: !!ticker,
  });

  if (q.isLoading) return <Card title="성과">불러오는 중…</Card>;
  if (q.isError || !q.data || q.data.length === 0) {
    return <Card title="성과">성과 기록 없음</Card>;
  }
  const p = q.data[0];

  return (
    <Card title="성과">
      <div className="space-y-2 text-data">
        <div className="text-faint text-data-xs">
          진입 {p.signal_at.slice(0, 10)} @ {p.entry_price.toLocaleString()}원
        </div>
        <table className="w-full text-data-xs">
          <thead className="text-faint">
            <tr>
              <th className="text-left">기간</th>
              <th className="text-right">종목</th>
              <th className="text-right">시장</th>
              <th className="text-right">α</th>
            </tr>
          </thead>
          <tbody>
            {PERIODS.map(({ key, label }) => {
              const r = (p as any)[`return_${key}_pct`] as number | null;
              const m = (p as any)[`market_return_${key}_pct`] as number | null;
              const alpha = r != null && m != null ? r - m : null;
              return (
                <tr key={key} className="border-t border-hairline">
                  <td className="py-1">{label}</td>
                  <td className={`py-1 text-right num ${r != null && r >= 0 ? "text-green-700" : r != null ? "text-red-700" : ""}`}>
                    {r != null ? `${r >= 0 ? "+" : ""}${r.toFixed(2)}%` : "—"}
                  </td>
                  <td className="py-1 text-right num text-muted">
                    {m != null ? `${m >= 0 ? "+" : ""}${m.toFixed(2)}%` : "—"}
                  </td>
                  <td className={`py-1 text-right num ${alpha != null && alpha >= 0 ? "text-green-700" : alpha != null ? "text-red-700" : ""}`}>
                    {alpha != null ? `${alpha >= 0 ? "+" : ""}${alpha.toFixed(2)}` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
```

- [ ] **Step 6: Create TriggerHistoryTable**

Create `web/src/components/panels/TriggerHistoryTable.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import type { Trigger, TriggerDecision } from "../../lib/types";
import { Card } from "./ClassificationCard";

interface Props { ticker: string; limit?: number }

const DECISION_COLOR: Record<TriggerDecision, { bg: string; text: string; dot: string }> = {
  go_now: { bg: "bg-green-100", text: "text-green-800", dot: "bg-green-500" },
  wait:   { bg: "bg-yellow-100", text: "text-yellow-800", dot: "bg-yellow-500" },
  abort:  { bg: "bg-gray-200", text: "text-gray-700", dot: "bg-gray-500" },
};

export function TriggerHistoryTable({ ticker, limit = 20 }: Props) {
  const q = useQuery<Trigger[]>({
    queryKey: ["trigger-history", ticker, limit],
    queryFn: () => api<Trigger[]>(`/triggers?ticker=${ticker}&limit=${limit}`),
    enabled: !!ticker,
  });

  if (q.isLoading) return <Card title="트리거 평가 이력">불러오는 중…</Card>;
  if (q.isError || !q.data || q.data.length === 0) {
    return <Card title="트리거 평가 이력">트리거 평가 이력이 없습니다.</Card>;
  }

  return (
    <Card title={`트리거 평가 이력 (최근 ${q.data.length}건)`}>
      <table className="w-full text-data">
        <thead className="text-faint">
          <tr>
            <th className="text-left py-1.5">시각</th>
            <th className="text-left py-1.5">트리거</th>
            <th className="text-left py-1.5">decision</th>
            <th className="text-right py-1.5">거래량비</th>
            <th className="text-right py-1.5">pivot대비</th>
            <th className="text-left py-1.5">reasoning</th>
          </tr>
        </thead>
        <tbody>
          {q.data.map((t) => {
            const cfg = DECISION_COLOR[t.decision];
            return (
              <tr key={`${t.symbol}-${t.evaluated_at}`} className="border-t border-hairline">
                <td className="py-1.5 num text-data-xs">
                  {t.evaluated_at.slice(0, 16).replace("T", " ")}
                </td>
                <td className="py-1.5">{t.trigger_type}</td>
                <td className="py-1.5">
                  <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded ${cfg.bg} ${cfg.text}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
                    {t.decision}
                  </span>
                </td>
                <td className="py-1.5 text-right num">
                  {t.avg_volume_50d_ratio != null ? `${t.avg_volume_50d_ratio.toFixed(2)}×` : "—"}
                </td>
                <td className="py-1.5 text-right num">
                  {t.pivot_delta_pct != null
                    ? `${t.pivot_delta_pct >= 0 ? "+" : ""}${t.pivot_delta_pct.toFixed(2)}%`
                    : "—"}
                </td>
                <td className="py-1.5 text-muted truncate max-w-md" title={t.reasoning ?? ""}>
                  {t.reasoning ?? ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mt-3 text-right">
        <Link
          to={`/triggers?ticker=${ticker}`}
          className="text-data text-accent hover:underline"
        >
          전체 이력 보기 →
        </Link>
      </div>
    </Card>
  );
}
```

- [ ] **Step 7: Type-check the frontend**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npm run build`

Expected: success. If `MinerviniDetail` 응답이 위 예상 키와 다르면 실제 응답 JSON 으로 타입을 조정 (예: `/api/indicators/minervini-detail/005930` 호출해서 확인 후 키 매핑).

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/types.ts web/src/components/panels/
git commit -m "feat: add 5 analysis panel components for ChartPage

ClassificationCard / IndicatorsCard / EntrySignalCard / PerformanceCard /
TriggerHistoryTable. 각자 ticker 만 받아 자체 fetch + 빈 상태 처리."
```

---

## Task 5: PriceChart overlay 확장 + 토글

**Files:**
- Modify: `web/src/components/charts/PriceChart.tsx` (props + 렌더링)
- Modify: `web/src/pages/ChartPage.tsx` (토글 state, 추후 Task 6 에서도 사용)

이 task 는 PriceChart 컴포넌트의 외부 API 확장만. ChartPage 의 데이터 전달은 Task 6 에서.

- [ ] **Step 1: Read PriceChart current structure**

Open `web/src/components/charts/PriceChart.tsx` and read lines 1-100 to find the props interface and main chart drawing logic.

- [ ] **Step 2: Extend props**

In `PriceChart.tsx`, locate the props interface (search `interface PriceChartProps` or `type PriceChartProps`). Add these optional fields:

```ts
  pivotPrice?: number | null;
  stopLoss?: number | null;
  showPivotStop?: boolean;
  showTriggerMarkers?: boolean;
  triggerEvents?: Array<{
    date: string;
    decision: "go_now" | "wait" | "abort";
    triggerType: string;
    close: number | null;
    reasoning: string | null;
  }>;
```

Default values inline in the destructure:

```ts
  pivotPrice = null,
  stopLoss = null,
  showPivotStop = true,
  showTriggerMarkers = true,
  triggerEvents = [],
```

- [ ] **Step 3: Render pivot/stop horizontal lines**

The PriceChart uses lightweight-charts (확인) — find the section that adds line series for SMA (search `addLineSeries` or `createLineSeries`). After SMA lines, add (gated by `showPivotStop`):

```ts
  if (showPivotStop && pivotPrice != null && bars.length > 0) {
    const pivotSeries = chart.addLineSeries({
      color: "#2563eb",
      lineWidth: 1,
      lineStyle: 2, // dashed
      lastValueVisible: true,
      priceLineVisible: false,
      title: "pivot",
    });
    pivotSeries.setData(bars.map((b) => ({ time: b.date, value: pivotPrice })));
  }

  if (showPivotStop && stopLoss != null && bars.length > 0) {
    const stopSeries = chart.addLineSeries({
      color: "#dc2626",
      lineWidth: 1,
      lineStyle: 2,
      lastValueVisible: true,
      priceLineVisible: false,
      title: "stop",
    });
    stopSeries.setData(bars.map((b) => ({ time: b.date, value: stopLoss })));
  }
```

> 만약 PriceChart 가 recharts 기반이면 `<ReferenceLine y={pivotPrice} stroke="#2563eb" strokeDasharray="4 4" label="pivot" />` 형태로 추가. PriceChart 의 실제 라이브러리 확인 후 그에 맞춰 수정.

- [ ] **Step 4: Render trigger markers**

After the line setup, add markers (lightweight-charts pattern):

```ts
  if (showTriggerMarkers && triggerEvents.length > 0 && bars.length > 0) {
    const colorByDecision = {
      go_now: "#16a34a",
      wait:   "#ca8a04",
      abort:  "#6b7280",
    } as const;
    const markers = triggerEvents.map((e) => ({
      time: e.date,
      position: "aboveBar" as const,
      color: colorByDecision[e.decision],
      shape: "circle" as const,
      text: e.decision,
    }));
    // 가격 메인 series 에 마커 부여
    priceSeries.setMarkers(markers);
  }
```

> recharts 기반이면 `<Scatter data={triggerEvents.map(...)} fill={...}/>` 패턴. 실제 라이브러리에 맞춰 수정.

`priceSeries` 는 기존 메인 캔들 series 변수명. 파일에서 실제 이름 확인 후 매칭.

- [ ] **Step 5: Add deps to useEffect**

PriceChart 의 차트 그리기 useEffect 의 deps 배열에 신규 props 추가:

```ts
  ], [
    bars,
    showSMAShort, showSMAMid, showSMALong, showSMAExtra,
    showVolume, showVolumeSMA,
    // 신규
    pivotPrice, stopLoss, showPivotStop,
    showTriggerMarkers, triggerEvents,
  ]);
```

- [ ] **Step 6: Build to verify**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npm run build`

Expected: success.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/charts/PriceChart.tsx
git commit -m "feat: PriceChart overlay — pivot/stop lines + trigger markers

pivotPrice / stopLoss / showPivotStop / showTriggerMarkers / triggerEvents
prop 추가. 기존 SMA 와 동일하게 토글 가능."
```

---

## Task 6: ChartPage 통합

**Files:**
- Modify: `web/src/pages/ChartPage.tsx`

이미 ChartPage 에는 종목 선택 / 차트 + 기존 SMA 토글이 있다. 여기에 (a) 새 useQuery 들로 분석 데이터 fetch, (b) PriceChart 에 overlay 데이터 전달, (c) 토글 체크박스 2 개 추가, (d) 차트 아래 카드 그리드.

- [ ] **Step 1: Add useState for new toggles**

In `ChartPage.tsx`, near line 124-133 (기존 useState 들 다음에) 추가:

```tsx
  const [showPivotStop, setShowPivotStop] = useState(true);
  const [showTriggerMarkers, setShowTriggerMarkers] = useState(true);
```

- [ ] **Step 2: Add queries for analysis data needed by overlay**

ChartPage 안에 (`dailyQ` / `weeklyQ` 정의 다음, line 170 근방) 추가:

```tsx
  const classificationQ = useQuery<Classification[]>({
    queryKey: ["chart-classification", ticker],
    queryFn: () => api<Classification[]>(`/classifications?ticker=${ticker}&lookback_days=60&limit=1`),
    enabled: !!ticker,
  });
  const signalQ = useQuery<Signal[]>({
    queryKey: ["chart-signal", ticker],
    queryFn: () => api<Signal[]>(`/signals?ticker=${ticker}&days=60`),
    enabled: !!ticker,
  });
  const triggerQ = useQuery<Trigger[]>({
    queryKey: ["chart-triggers", ticker],
    queryFn: () => api<Trigger[]>(`/triggers?ticker=${ticker}&limit=50`),
    enabled: !!ticker,
  });
```

또한 상단 import 에 추가:

```tsx
import type { Classification, Signal, Trigger } from "../lib/types";
import { ClassificationCard } from "../components/panels/ClassificationCard";
import { IndicatorsCard } from "../components/panels/IndicatorsCard";
import { EntrySignalCard } from "../components/panels/EntrySignalCard";
import { PerformanceCard } from "../components/panels/PerformanceCard";
import { TriggerHistoryTable } from "../components/panels/TriggerHistoryTable";
```

- [ ] **Step 3: Derive overlay data**

`bars` 계산 뒤 (line ~182 근방) 추가:

```tsx
  const pivotPrice = classificationQ.data?.[0]?.pivot_price ?? null;
  const stopLoss = signalQ.data?.[0]?.stop_loss ?? null;
  const triggerEvents = useMemo(() => {
    return (triggerQ.data ?? []).map((t) => ({
      date: t.evaluated_at.slice(0, 10),
      decision: t.decision,
      triggerType: t.trigger_type,
      close: t.close,
      reasoning: t.reasoning,
    }));
  }, [triggerQ.data]);
```

- [ ] **Step 4: Pass overlay props to PriceChart**

찾기: `<PriceChart` (line ~389 근방). 기존 props 옆에 추가:

```tsx
            pivotPrice={pivotPrice}
            stopLoss={stopLoss}
            showPivotStop={showPivotStop}
            showTriggerMarkers={showTriggerMarkers}
            triggerEvents={triggerEvents}
```

- [ ] **Step 5: Add toggle checkboxes**

기존 토글 체크박스 묶음 (line ~420-475) 다음에 새 그룹 추가:

```tsx
          <div className="flex flex-wrap gap-2 mt-3">
            <Toggle
              checked={showPivotStop}
              onChange={setShowPivotStop}
              color="#2563eb"
              label="Pivot/Stop 선"
            />
            <Toggle
              checked={showTriggerMarkers}
              onChange={setShowTriggerMarkers}
              color="#16a34a"
              label="트리거 마커"
            />
          </div>
```

- [ ] **Step 6: Add panel grid below chart**

ChartPage 의 차트 JSX 가 닫히는 직후 (return 의 차트 컨테이너 다음) 추가:

```tsx
        {ticker && (
          <section className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-4">
            <ClassificationCard ticker={ticker} />
            <IndicatorsCard ticker={ticker} />
            <EntrySignalCard ticker={ticker} />
            <PerformanceCard ticker={ticker} />
            <div className="lg:col-span-2">
              <TriggerHistoryTable ticker={ticker} />
            </div>
          </section>
        )}
```

- [ ] **Step 7: Build**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npm run build`

Expected: build succeeds.

- [ ] **Step 8: Manual smoke test**

Start dev server. Visit `http://localhost:5173/chart/005930` (또는 분석 데이터가 있는 다른 종목). Verify:
- 차트 위에 pivot/stop 가로 점선이 보인다 (분류/시그널 데이터 있을 때)
- 트리거 평가일에 마커가 보인다 (decision 색상)
- 토글 체크박스 두 개 (Pivot/Stop 선, 트리거 마커) 가 보이고 끄면 즉시 사라진다
- 차트 아래에 분류/결정론지표/매수시그널/성과/트리거이력 5개 카드가 보인다
- 데이터 없는 카드는 빈 상태 메시지 (페이지 깨지지 않음)
- 트리거 이력 카드의 "전체 이력 보기" 링크가 `/triggers?ticker=005930` 으로 이동한다

- [ ] **Step 9: Commit**

```bash
git add web/src/pages/ChartPage.tsx
git commit -m "feat: integrate analysis panels + overlay into ChartPage

5 카드 (분류/지표/시그널/성과/트리거이력) + pivot/stop 선 + 트리거 마커
+ 토글 체크박스 2개. 모든 카드 종목 미선택 시 hidden."
```

---

## Self-Review Notes

**Spec coverage check (against `docs/superpowers/specs/2026-05-20-triggers-and-chart-analysis-design.md`):**

| 스펙 항목 | 구현 task |
|---|---|
| `GET /api/triggers` 라우터 + 필터 + 응답 | Task 1 |
| `avg_volume_50d_ratio`, `pivot_delta_pct` 응답 시 계산 | Task 1 Step 7 |
| 기존 endpoint `ticker` 필터 (signals/performance/classifications) | Task 2 |
| 사이드바 NAV + Route `/triggers` | Task 3 Step 2 |
| `/triggers` 페이지 (날짜 그룹 + 필터 + 행 클릭) | Task 3 |
| URL 쿼리 파라미터 동기화 | Task 3 Step 3 |
| 5 분석 카드 컴포넌트 | Task 4 |
| 빈 상태 카드 자체 처리 | Task 4 Step 2-6 |
| PriceChart overlay (pivot/stop 선 + 트리거 마커) | Task 5 |
| 토글 체크박스 (Pivot/Stop, 트리거 마커) | Task 6 Step 5 |
| 차트 아래 2 컬럼 그리드 + 트리거 표 전폭 | Task 6 Step 6 |
| 종목 미선택 시 패널 hidden | Task 6 Step 6 (조건 `{ticker && …}`) |
| 트리거 이력 → /triggers?ticker= 더보기 링크 | Task 4 Step 6 |

빠진 항목 없음.

**Type consistency:** `Trigger` (Task 3 Step 1) 의 필드명 / `Classification` (Task 4 Step 1) 의 `base_start_date` / `MinerviniDetail.conditions.cN_…` / `Signal.stop_loss` — 모두 Task 1 의 응답 스키마 (`TriggerOut`) 와 일치, ChartPage (Task 6) 에서 사용하는 필드명도 일치.

**Risks:**
- `MinerviniDetail` 응답 구조가 추정 (Task 4 Step 3 코멘트 참고). 실제 응답이 다르면 build 시 발견 후 키 매핑 조정 — Task 4 Step 7 에서 조정 가능.
- PriceChart 라이브러리 (lightweight-charts vs recharts vs custom) 가 확인 안 됨. Task 5 Step 1 에서 실제 라이브러리 식별 후 Step 3-4 의 코드를 라이브러리에 맞춰 조정 (가이드 두 가지 모두 제시).
