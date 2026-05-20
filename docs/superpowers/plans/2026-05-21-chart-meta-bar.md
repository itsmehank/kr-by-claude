# ChartPage 메타바 + 요일 표시 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChartPage 의 차트 위에 종목/시장 비교/주간 거래량 한 줄 메타바를 추가하고, 차트 hover tooltip 의 날짜 옆에 한국어 요일을 표시한다.

**Architecture:** 새 `GET /api/index/daily/{index_code}` 라우터로 KOSPI(1001)/KOSDAQ(2001) OHLC 노출. `ChartMetaBar` 컴포넌트가 종목 daily + 지수 daily 를 자체 fetch 해 1주/1달/3달 (5/22/63 거래일) 수익률 비교 + 이번주 거래량 합 + SMA50 대비 % 계산해 한 줄 표시. ChartPage 가 차트 카드 위에 메타바 삽입. PriceChart tooltip 은 helper 한 줄로 요일 추가.

**Tech Stack:** FastAPI, psycopg, pytest, TestClient, React 19, TanStack Query, Tailwind, lightweight-charts (PriceChart 기존).

**Spec:** `docs/superpowers/specs/2026-05-21-chart-meta-bar-design.md` (commit a2f28d4)

---

## File Structure

### 신규
- `api/schemas/index.py` — `IndexDailyOut` Pydantic 스키마
- `api/routers/index.py` — `GET /api/index/daily/{index_code}` 라우터
- `tests/test_api_index.py` — index 라우터 테스트
- `web/src/components/ChartMetaBar.tsx` — 메타바 컴포넌트

### 수정
- `api/main.py` — `index` 라우터 import + include_router
- `web/src/lib/types.ts` — `IndexDaily` 타입 추가
- `web/src/pages/ChartPage.tsx` — 메타바 import + 차트 카드 위에 삽입
- `web/src/components/charts/PriceChart.tsx` — tooltip 날짜에 요일 추가

---

## Task 1: `GET /api/index/daily/{index_code}` 라우터 + 스키마 + 테스트

**Files:**
- Create: `api/schemas/index.py`
- Create: `api/routers/index.py`
- Create: `tests/test_api_index.py`
- Modify: `api/main.py` (import + include_router)

- [ ] **Step 1: Pydantic 스키마**

Create `api/schemas/index.py`:

```python
from datetime import date
from pydantic import BaseModel


class IndexDailyOut(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
```

- [ ] **Step 2: 빈 라우터 + main.py 등록**

Create `api/routers/index.py`:

```python
from datetime import date as _date, timedelta
from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn
from api.schemas.index import IndexDailyOut


router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("/daily/{index_code}", response_model=list[IndexDailyOut])
def get_index_daily(
    index_code: str,
    start: _date | None = None,
    end: _date | None = None,
    conn: Connection = Depends(get_conn),
):
    return []
```

Modify `api/main.py`. Locate the existing router import line (currently includes `stocks, indicators, heatmap, render, prompts, runs, market_context, signals, performance, runner, pipelines, classifications, triggers`) and append `, index`. Then add `app.include_router(index.router)` after the `triggers` registration.

The Python module is named `index` (file `api/routers/index.py`); avoid shadowing the built-in `index` by importing it as `from api.routers import ... , index as index_router` if your IDE complains. The simplest working form:

```python
from api.routers import index  # added at end of router import block
# ...
app.include_router(index.router)
```

- [ ] **Step 3: Verify routing**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && python -c "from api.main import app; print([r.path for r in app.routes if '/index' in r.path])"`

Expected output: `['/api/index/daily/{index_code}']`

- [ ] **Step 4: Write failing test — empty for unknown code**

Create `tests/test_api_index.py`:

```python
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_index(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override

    with db.cursor() as cur:
        cur.execute("DELETE FROM index_daily WHERE index_code IN ('IDXTEST1','IDXTEST2')")
        cur.execute(
            """INSERT INTO index_daily
                 (index_code, date, open, high, low, close, volume)
               VALUES
                 ('IDXTEST1','2026-05-18',2540.10,2562.00,2535.70,2558.30,412345678),
                 ('IDXTEST1','2026-05-19',2558.30,2570.00,2550.00,2565.50,400000000),
                 ('IDXTEST1','2026-05-20',2565.50,2580.10,2560.00,2575.00,420000000),
                 ('IDXTEST2','2026-05-20', 850.00, 860.50, 845.00, 855.10,180000000)"""
        )
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_unknown_index_returns_empty(client, seed_index):
    r = client.get("/api/index/daily/9999")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 5: Run the empty-handler test**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_api_index.py::test_unknown_index_returns_empty -v`

Expected: PASS (empty handler returns `[]`).

- [ ] **Step 6: Write failing test — real rows + asc order**

Append to `tests/test_api_index.py`:

```python
def test_returns_rows_ordered_asc(client, seed_index):
    r = client.get("/api/index/daily/IDXTEST1?start=2026-05-18&end=2026-05-20")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    assert [row["date"] for row in rows] == ["2026-05-18", "2026-05-19", "2026-05-20"]
    assert rows[0]["close"] == 2558.30
    assert rows[2]["close"] == 2575.00
    assert rows[0]["volume"] == 412345678


def test_start_end_filter(client, seed_index):
    r = client.get("/api/index/daily/IDXTEST1?start=2026-05-19&end=2026-05-20")
    dates = [row["date"] for row in r.json()]
    assert dates == ["2026-05-19", "2026-05-20"]


def test_default_window_returns_recent(client, seed_index):
    # start/end 안 주면 최근 365일 → seed 데이터 포함되어야 함
    r = client.get("/api/index/daily/IDXTEST1")
    dates = {row["date"] for row in r.json()}
    assert {"2026-05-18", "2026-05-19", "2026-05-20"}.issubset(dates)
```

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_api_index.py -v`

Expected: 1 pass + 3 fail (empty handler doesn't return real rows yet).

- [ ] **Step 7: Implement query**

Replace `api/routers/index.py` content:

```python
from datetime import date as _date, timedelta
from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn
from api.schemas.index import IndexDailyOut


router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("/daily/{index_code}", response_model=list[IndexDailyOut])
def get_index_daily(
    index_code: str,
    start: _date | None = None,
    end: _date | None = None,
    conn: Connection = Depends(get_conn),
):
    if end is None:
        end = _date.today()
    if start is None:
        start = end - timedelta(days=365)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, open, high, low, close, volume
              FROM index_daily
             WHERE index_code = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (index_code, start, end),
        )
        rows = cur.fetchall()

    return [
        IndexDailyOut(
            date=r[0],
            open=float(r[1]),
            high=float(r[2]),
            low=float(r[3]),
            close=float(r[4]),
            volume=int(r[5]) if r[5] is not None else None,
        )
        for r in rows
    ]
```

- [ ] **Step 8: Run all index tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_api_index.py -v`

Expected: 4/4 PASS.

- [ ] **Step 9: Commit**

```bash
git add api/schemas/index.py api/routers/index.py api/main.py tests/test_api_index.py
git commit -m "feat: add GET /api/index/daily/{index_code} endpoint

index_daily 테이블 노출. start/end 필터 + date ASC. KOSPI(1001)/KOSDAQ(2001)
가격으로 ChartMetaBar 의 시장 대비 수익률 계산에 사용."
```

---

## Task 2: `ChartMetaBar.tsx` 컴포넌트

**Files:**
- Modify: `web/src/lib/types.ts` (`IndexDaily` 타입 추가)
- Create: `web/src/components/ChartMetaBar.tsx`

- [ ] **Step 1: Add IndexDaily type**

Open `web/src/lib/types.ts` and append:

```ts
export interface IndexDaily {
  date: string;     // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}
```

- [ ] **Step 2: Create ChartMetaBar component**

Create `web/src/components/ChartMetaBar.tsx`:

```tsx
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { DailyIndicator, IndexDaily } from "../lib/types";

interface Props {
  ticker: string;
  stockName: string | null;
  market: string | null;
  sector: string | null;
}

const MARKET_INDEX_CODE: Record<string, string> = {
  KOSPI: "1001",
  KOSDAQ: "2001",
};

function nDaysAgoISO(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

// KST 기준 오늘이 속한 주의 월요일을 YYYY-MM-DD 로 반환.
// getDay(): 0=일 1=월 ... 6=토. 일요일(0)이면 6일 전 월요일.
function thisWeekMondayISO(): string {
  const now = new Date();
  const day = now.getDay();
  const back = day === 0 ? 6 : day - 1;
  const mon = new Date(now);
  mon.setDate(now.getDate() - back);
  return mon.toISOString().slice(0, 10);
}

function pctChange(curr: number, base: number): number | null {
  if (!base || base === 0) return null;
  return ((curr - base) / base) * 100;
}

function formatPct(p: number | null): string {
  if (p == null) return "—";
  const sign = p >= 0 ? "+" : "";
  return `${sign}${p.toFixed(2)}%`;
}

function pctClass(p: number | null): string {
  if (p == null) return "text-muted";
  return p > 0 ? "text-success" : p < 0 ? "text-danger" : "text-muted";
}

function formatVolume(v: number): string {
  return v.toLocaleString();
}

interface ReturnsRow {
  label: string;
  daysAgo: number; // 1주=5, 1달=22, 3달=63 거래일
}

const RETURN_PERIODS: ReturnsRow[] = [
  { label: "1주", daysAgo: 5 },
  { label: "1달", daysAgo: 22 },
  { label: "3달", daysAgo: 63 },
];

export function ChartMetaBar({ ticker, stockName, market, sector }: Props) {
  const indexCode = market ? MARKET_INDEX_CODE[market] ?? null : null;

  const stockQ = useQuery<DailyIndicator[]>({
    queryKey: ["meta-bar-stock", ticker],
    queryFn: () =>
      api<DailyIndicator[]>(
        `/indicators/daily/${ticker}?start=${nDaysAgoISO(180)}&end=${todayISO()}`,
      ),
    enabled: !!ticker,
  });

  const indexQ = useQuery<IndexDaily[]>({
    queryKey: ["meta-bar-index", indexCode],
    queryFn: () =>
      api<IndexDaily[]>(
        `/index/daily/${indexCode}?start=${nDaysAgoISO(180)}&end=${todayISO()}`,
      ),
    enabled: !!indexCode,
  });

  const returns = useMemo(() => {
    const sb = stockQ.data ?? [];
    const ib = indexQ.data ?? [];
    return RETURN_PERIODS.map(({ label, daysAgo }) => {
      const stockNow = sb[sb.length - 1]?.adj_close ?? null;
      const stockBase = sb[sb.length - 1 - daysAgo]?.adj_close ?? null;
      const stock = stockNow != null && stockBase != null
        ? pctChange(stockNow, stockBase)
        : null;

      const idxNow = ib[ib.length - 1]?.close ?? null;
      const idxBase = ib[ib.length - 1 - daysAgo]?.close ?? null;
      const idx = idxNow != null && idxBase != null
        ? pctChange(idxNow, idxBase)
        : null;

      return { label, stock, idx };
    });
  }, [stockQ.data, indexQ.data]);

  const weekVolume = useMemo(() => {
    const sb = stockQ.data ?? [];
    if (sb.length === 0) return { sum: null as number | null, days: 0, sma50: null as number | null };
    const monday = thisWeekMondayISO();
    const week = sb.filter((d) => d.date >= monday && d.volume != null);
    const sum = week.reduce((acc, d) => acc + (d.volume ?? 0), 0);
    const sma50 = sb[sb.length - 1].avg_volume_50d ?? null;
    return { sum: week.length > 0 ? sum : null, days: week.length, sma50 };
  }, [stockQ.data]);

  // 주간 일평균 vs SMA50 비교 (%)
  const weekVsSma = useMemo(() => {
    if (!weekVolume.sum || !weekVolume.days || !weekVolume.sma50) return null;
    const dailyAvg = weekVolume.sum / weekVolume.days;
    return pctChange(dailyAvg, weekVolume.sma50);
  }, [weekVolume]);

  const loading = stockQ.isLoading || (!!indexCode && indexQ.isLoading);
  const error = stockQ.isError;

  return (
    <div className="bento p-4 mb-3">
      <div className="text-data flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="num font-bold text-ink">{ticker}</span>
        {stockName && <span className="font-semibold text-ink">{stockName}</span>}
        {market && (
          <>
            <span className="text-faint">·</span>
            <span className="text-muted">{market}</span>
          </>
        )}
        {sector && (
          <>
            <span className="text-faint">·</span>
            <span className="text-muted">{sector}</span>
          </>
        )}
      </div>

      {loading ? (
        <div className="mt-2 text-muted">불러오는 중…</div>
      ) : error ? (
        <div className="mt-2 text-muted">정보를 불러오지 못했습니다</div>
      ) : (
        <>
          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-data">
            {returns.map(({ label, stock, idx }) => (
              <span key={label} className="inline-flex items-baseline gap-1.5">
                <span className="caps text-faint">{label}</span>
                <span className={`num font-semibold ${pctClass(stock)}`}>
                  {formatPct(stock)}
                </span>
                {indexCode && (
                  <span className={`num text-data-xs ${pctClass(idx)}`}>
                    (시장 {formatPct(idx)})
                  </span>
                )}
              </span>
            ))}
          </div>

          <div className="mt-1 text-data text-muted">
            <span className="caps text-faint">이번주 거래량</span>{" "}
            <span className="num text-ink">
              {weekVolume.sum != null ? formatVolume(weekVolume.sum) : "—"}
            </span>{" "}
            {weekVolume.days > 0 && (
              <span className="text-faint">({weekVolume.days}일)</span>
            )}
            {" / "}
            <span className="caps text-faint">SMA50</span>{" "}
            <span className="num text-ink">
              {weekVolume.sma50 != null ? formatVolume(weekVolume.sma50) : "—"}
            </span>
            {weekVsSma != null && (
              <span className={`num ml-1.5 ${pctClass(weekVsSma)}`}>
                ({formatPct(weekVsSma)})
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Type-check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/types.ts web/src/components/ChartMetaBar.tsx
git commit -m "feat: ChartMetaBar 컴포넌트 (수익률 비교 + 주간 거래량)

종목 daily + 지수 daily 자체 fetch. 1주/1달/3달 거래일 수익률 비교
(KOSPI/KOSDAQ 자동 매핑), 이번주 거래량 합 + SMA50 대비 비율.
fetch 실패 시 한 줄 회색 메시지로 graceful fallback."
```

---

## Task 3: ChartPage 에 메타바 삽입

**Files:**
- Modify: `web/src/pages/ChartPage.tsx`

- [ ] **Step 1: Add import**

In `web/src/pages/ChartPage.tsx` import block (line 1-26 영역), append:

```tsx
import { ChartMetaBar } from "../components/ChartMetaBar";
```

- [ ] **Step 2: Insert meta bar above the chart card**

Locate the chart container (around line 388):

```tsx
      ) : bars.length > 0 ? (
        <div className="bento p-2 mb-5 overflow-hidden">
          <PriceChart
```

Insert the meta bar immediately BEFORE this `<div className="bento p-2 mb-5 overflow-hidden">` (only when `ticker` is set):

```tsx
      ) : bars.length > 0 ? (
        <>
          {ticker && (
            <ChartMetaBar
              ticker={ticker}
              stockName={stockMeta?.name ?? null}
              market={stockMeta?.market ?? null}
              sector={stockMeta?.sector ?? null}
            />
          )}
          <div className="bento p-2 mb-5 overflow-hidden">
            <PriceChart
```

And close the fragment after the chart card's closing `</div>`:

```tsx
            />
          </div>
        </>
      ) : (
```

Exact transformation (find this block — note it spans many lines, keep the rest of PriceChart props untouched):

Before:
```tsx
      ) : bars.length > 0 ? (
        <div className="bento p-2 mb-5 overflow-hidden">
          <PriceChart
            data={bars}
            ...all existing props...
            triggerEvents={triggerEvents}
          />
        </div>
      ) : (
```

After:
```tsx
      ) : bars.length > 0 ? (
        <>
          {ticker && (
            <ChartMetaBar
              ticker={ticker}
              stockName={stockMeta?.name ?? null}
              market={stockMeta?.market ?? null}
              sector={stockMeta?.sector ?? null}
            />
          )}
          <div className="bento p-2 mb-5 overflow-hidden">
            <PriceChart
              data={bars}
              ...all existing props (unchanged)...
              triggerEvents={triggerEvents}
            />
          </div>
        </>
      ) : (
```

The inner `<PriceChart .../>` props block is unchanged — only the surrounding fragment and ChartMetaBar are added.

- [ ] **Step 3: Type-check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 4: Manual smoke test**

If dev server is not already running, start it: `cd /Users/hank.es/git/personal/kr-by-claude/web && npm run dev`

Open `http://localhost:5173/chart/005930` and verify:
- 종목 메타 카드 (기존, 종가/RS 등) 아래, 차트 카드 위에 새 메타바 카드가 보인다
- 1주/1달/3달 % 가 종목/시장 둘 다 표시된다 (KOSPI 종목)
- 이번주 거래량 합과 SMA50 비교 % 가 표시된다
- 종목 변경 시 (다른 ticker 로 이동) 데이터 갱신된다
- KOSDAQ 종목 (예: `/chart/247540` 에코프로비엠) 로 가면 KOSDAQ 지수 대비로 자동 전환된다

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/ChartPage.tsx
git commit -m "feat(chart): ChartPage 에 ChartMetaBar 삽입

종목 메타 카드 아래, 차트 카드 위. 종목 미선택 시 hidden.
stockMeta 데이터를 prop 으로 넘김 — 추가 fetch 없음."
```

---

## Task 4: PriceChart tooltip 에 요일 표시

**Files:**
- Modify: `web/src/components/charts/PriceChart.tsx`

- [ ] **Step 1: Add `withWeekday` helper**

In `web/src/components/charts/PriceChart.tsx`, locate the top of the file (after imports, before `interface PriceChartBar`) and add a helper:

```tsx
// 날짜에 한국어 요일 추가: "2026-05-20" → "2026-05-20 (수)"
function withWeekday(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  const wd = ["일", "월", "화", "수", "목", "금", "토"][d.getDay()];
  return `${iso} (${wd})`;
}
```

- [ ] **Step 2: Use helper in tooltip**

Locate the tooltip's date line (around line 363):

```tsx
            <div className="num text-data-xs text-muted">{tooltip.date}</div>
```

Change to:

```tsx
            <div className="num text-data-xs text-muted">{withWeekday(tooltip.date)}</div>
```

- [ ] **Step 3: Type-check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 4: Manual smoke test**

Open `http://localhost:5173/chart/005930` and hover the chart — tooltip 의 날짜 옆에 한국어 요일 (월/화/수/목/금/토/일 중 하나) 이 표시되어야 합니다.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/charts/PriceChart.tsx
git commit -m "feat(chart): tooltip 날짜에 한국어 요일 표시

withWeekday helper 추가. 2026-05-20 → 2026-05-20 (수)"
```

---

## Self-Review Notes

**Spec coverage check (against `docs/superpowers/specs/2026-05-21-chart-meta-bar-design.md`):**

| 스펙 항목 | 구현 task |
|---|---|
| `GET /api/index/daily/{index_code}` 라우터 + start/end | Task 1 |
| 빈 `index_code` → 빈 배열 응답 | Task 1 Step 7 (`%s AND date BETWEEN` 자동 처리) |
| `ChartMetaBar` 자체 fetch (종목 + 지수) | Task 2 |
| KOSPI/KOSDAQ 자동 매핑 | Task 2 (`MARKET_INDEX_CODE`) |
| 1주/1달/3달 거래일 수익률 계산 | Task 2 (`RETURN_PERIODS`, 5/22/63 행 전 close 대비) |
| 이번주 거래량 합 (KST 월요일~최신) | Task 2 (`thisWeekMondayISO`, filter + reduce) |
| 주간 일평균 vs SMA50 대비 % | Task 2 (`weekVsSma`) |
| 로딩 / 에러 graceful fallback | Task 2 (회색 한 줄, throw 안 함) |
| ChartPage 에 메타바 삽입 (차트 카드 위) | Task 3 |
| 메타바 prop 으로 stockMeta 데이터 재사용 (추가 fetch 없음) | Task 3 Step 2 |
| tooltip 에 한국어 요일 (월/화/수/목/금/토/일) | Task 4 |

빠진 항목 없음.

**Type / 네이밍 일관성:**

- `IndexDaily` (Task 2 Step 1) 의 필드명이 `IndexDailyOut` (Task 1 Step 1) 의 필드명과 일치
- `MARKET_INDEX_CODE` 의 key (`KOSPI`/`KOSDAQ`) 가 `stocks.market` 의 값과 일치
- `nDaysAgoISO(180)` 가 종목/지수 양쪽에서 동일 — 정합성 OK
- `RETURN_PERIODS.daysAgo` 가 5/22/63 — 스펙의 정의와 일치

**Risks:**

- `nDaysAgoISO(180)` 가 달력일 180 — 실제 거래일은 약 130 (3달 + 마진). 데이터 부족 종목 (신생 / 거래정지 등) 은 `null` → "—" 표시되어 안전.
- `thisWeekMondayISO()` 는 사용자 브라우저 timezone 사용. KST 가 아니면 월요일이 다를 수 있음. 사용자가 한국 외 지역에서 접속하지 않는 전제 (localhost 단일 사용자, 한국 운영자) 이므로 허용.
- 새 `index` 라우터 모듈명이 Python 내장 `index` 와 동일하지만, FastAPI 라우터 import 컨텍스트에서는 충돌 없음.
