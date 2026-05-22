# LLM 분류 결과 페이지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/classifications` 라우트에서 `weekly_classification` 테이블의 LLM 분류 결과 (watch / entry / ignore) 를 그룹별 collapsible 리스트로 표시. 필터 (기간/classification/source/min_confidence/sort) + row expand 로 reasoning 전문 표시 + 차트 페이지 라우팅.

**Architecture:** Backend 신규 endpoint `GET /api/classifications` 가 `DISTINCT ON (symbol)` 으로 종목별 최신 분류 1건만 반환 (kwarg 필터 적용). Frontend 신규 페이지 `ClassificationsPage` 가 TanStack Query 로 호출, 그룹별 collapsible UI 렌더링. RunDialog 패턴 (이미 추출됨) 과 동일하게 컴포넌트 단순화.

**Tech Stack:** Python (FastAPI, psycopg), TypeScript, React 19, React Router, TanStack Query, lucide-react, Tailwind.

**Spec:** `docs/superpowers/specs/2026-05-18-classifications-page-design.md`

---

## ⚙️ Goal State

다음 모두 충족 시 종료:

1. 모든 task 체크박스 완료
2. Backend 회귀 유지 + 신규 ~8 추가
3. Frontend tsc 0 errors
4. `GET /api/classifications` 200 OK + 응답 키 모두 존재
5. 사이드바 새 메뉴 "LLM 분류" 노출 + `/classifications` 라우트 정상 작동
6. 페이지 — 헤더 / 필터 바 / 그룹별 (watch/entry/ignore) 리스트 / row expand 모두 동작
7. row 의 "차트 보기 →" 클릭 시 `/chart/<symbol>` 로 라우팅
8. `git status` clean

---

## 사전 조건

- HEAD: `2fb4ebf` (spec commit) 또는 이후
- 기존 `weekly_classification` 테이블 + 데이터 (LLM 주말 분류 테스트로 3건 들어있음)
- 기존 React Router / TanStack Query / Tailwind 설정 정상

---

## Task 1: Backend — `GET /api/classifications` 엔드포인트

**Files:**
- Create: `api/routers/classifications.py`
- Modify: `api/main.py` (router include)
- Create: `tests/test_api_classifications.py`

신규 endpoint 가 `weekly_classification` ⋈ `stocks` 결과를 `DISTINCT ON (symbol)` 으로 종목별 최신 1건만 반환. 쿼리 파라미터로 필터 + 정렬.

### Step 1: 테스트 작성

`tests/test_api_classifications.py` 신규:

```python
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_classifications(db):
    """3종목 분류 + stocks 데이터 seed."""
    def override():
        yield db
    app.dependency_overrides[get_conn] = override

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'CLSTEST%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'CLSTEST%'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('CLSTEST01','Test1','KOSPI','금융','2020-01-01'),
                      ('CLSTEST02','Test2','KOSDAQ','반도체','2020-01-01'),
                      ('CLSTEST03','Test3','KOSPI','보험','2020-01-01')"""
        )
        # 최근 분류 3건 (서로 다른 종목)
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, confidence, reasoning, source, created_at)
               VALUES
                 ('CLSTEST01', NOW() - INTERVAL '1 day', 'KOSPI', 'watch', 'flat_base',
                  1000.0, 0.55, '근거1', 'weekend', NOW()),
                 ('CLSTEST02', NOW() - INTERVAL '2 day', 'KOSDAQ', 'ignore', 'none',
                  NULL, 0.78, '근거2', 'weekend', NOW()),
                 ('CLSTEST03', NOW() - INTERVAL '3 day', 'KOSPI', 'entry', 'cup',
                  2000.0, 0.85, '근거3', 'daily-delta', NOW())"""
        )
        # 같은 종목 CLSTEST01 의 더 오래된 분류 (DISTINCT ON 검증용)
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  confidence, source, created_at)
               VALUES ('CLSTEST01', NOW() - INTERVAL '10 day', 'KOSPI', 'ignore', 'none',
                       0.40, 'weekend', NOW())"""
        )
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_get_classifications_basic(client, seed_classifications):
    r = client.get("/api/classifications?lookback_days=30")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    symbols = {row["symbol"] for row in data}
    assert {"CLSTEST01", "CLSTEST02", "CLSTEST03"}.issubset(symbols)


def test_distinct_on_symbol_returns_latest(client, seed_classifications):
    """같은 symbol 의 두 분류 행 → 최신 1건만 응답."""
    r = client.get("/api/classifications?lookback_days=30")
    rows = [row for row in r.json() if row["symbol"] == "CLSTEST01"]
    assert len(rows) == 1
    # 최신 (1일 전, watch) 가 반환 — 10일 전 ignore 가 아님
    assert rows[0]["classification"] == "watch"


def test_response_includes_name_and_sector(client, seed_classifications):
    r = client.get("/api/classifications?lookback_days=30")
    row = next(row for row in r.json() if row["symbol"] == "CLSTEST01")
    assert row["name"] == "Test1"
    assert row["sector"] == "금융"
    assert row["market"] == "KOSPI"


def test_classification_filter(client, seed_classifications):
    """classifications=watch&classifications=entry → ignore 제외."""
    r = client.get("/api/classifications?lookback_days=30&classifications=watch&classifications=entry")
    classes = {row["classification"] for row in r.json()}
    assert "ignore" not in classes
    test_symbols = {row["symbol"] for row in r.json() if row["symbol"].startswith("CLSTEST")}
    assert test_symbols == {"CLSTEST01", "CLSTEST03"}


def test_source_filter(client, seed_classifications):
    """sources=weekend → daily-delta 제외."""
    r = client.get("/api/classifications?lookback_days=30&sources=weekend")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    for row in test_rows:
        assert row["source"] == "weekend"


def test_min_confidence_filter(client, seed_classifications):
    """min_confidence=0.7 → confidence < 0.7 제외."""
    r = client.get("/api/classifications?lookback_days=30&min_confidence=0.7")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    for row in test_rows:
        assert row["confidence"] >= 0.7
    syms = {row["symbol"] for row in test_rows}
    # CLSTEST01 (0.55) 제외, CLSTEST02 (0.78) + CLSTEST03 (0.85) 만
    assert syms == {"CLSTEST02", "CLSTEST03"}


def test_lookback_days_filter(client, seed_classifications):
    """lookback_days=1 → 1일 이내 분류만."""
    r = client.get("/api/classifications?lookback_days=1")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    # 1일 전 CLSTEST01 만 통과 (2, 3일 전 제외)
    syms = {row["symbol"] for row in test_rows}
    assert syms == {"CLSTEST01"}


def test_sort_confidence_desc(client, seed_classifications):
    """sort=confidence_desc → confidence 내림차순."""
    r = client.get("/api/classifications?lookback_days=30&sort=confidence_desc")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    confs = [row["confidence"] for row in test_rows]
    assert confs == sorted(confs, reverse=True)
```

### Step 2: 테스트 실패 확인

```bash
cd ~/kr-by-claude
uv run pytest tests/test_api_classifications.py -v
```

Expected: 8 failures (404 — route 없음).

### Step 3: Router 구현

`api/routers/classifications.py` 신규:

```python
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection
from pydantic import BaseModel

from api.deps import get_conn


router = APIRouter(prefix="/api/classifications", tags=["classifications"])


class ClassificationRow(BaseModel):
    symbol: str
    name: str
    market: str
    sector: str | None
    classification: str
    pattern: str | None
    pivot_price: float | None
    pivot_basis: str | None
    base_high: float | None
    base_low: float | None
    base_depth_pct: float | None
    base_start_date: date | None
    risk_flags: list[str]
    confidence: float | None
    reasoning: str | None
    source: str
    classified_at: datetime
    expires_at: datetime | None
    llm_call_duration_s: float | None
    llm_input_tokens: int | None
    llm_output_tokens: int | None


SORT_CLAUSES = {
    "classified_at_desc": "l.classified_at DESC",
    "confidence_desc": "l.confidence DESC NULLS LAST, l.classified_at DESC",
}


@router.get("", response_model=list[ClassificationRow])
def get_classifications(
    lookback_days: int = 14,
    classifications: list[str] | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
    min_confidence: float = 0.0,
    sort: str = "classified_at_desc",
    limit: int = 100,
    conn: Connection = Depends(get_conn),
):
    """LLM 분류 결과 — 종목별 최신 1건 (DISTINCT ON), 필터 + 정렬 + 제한."""
    sort_clause = SORT_CLAUSES.get(sort, SORT_CLAUSES["classified_at_desc"])

    sql = f"""
        WITH latest AS (
          SELECT DISTINCT ON (symbol)
                 symbol, classified_at, market, classification, pattern,
                 pivot_price, pivot_basis, base_high, base_low, base_depth_pct,
                 base_start_date, risk_flags, confidence, reasoning, source,
                 expires_at, llm_call_duration_s, llm_input_tokens, llm_output_tokens
            FROM weekly_classification
           WHERE classified_at >= NOW() - (%(lookback_days)s || ' days')::interval
           ORDER BY symbol, classified_at DESC
        )
        SELECT l.symbol, s.name, l.market, s.sector,
               l.classification, l.pattern, l.pivot_price, l.pivot_basis,
               l.base_high, l.base_low, l.base_depth_pct, l.base_start_date,
               l.risk_flags, l.confidence, l.reasoning, l.source,
               l.classified_at, l.expires_at,
               l.llm_call_duration_s, l.llm_input_tokens, l.llm_output_tokens
          FROM latest l
          JOIN stocks s ON s.ticker = l.symbol
         WHERE (%(classifications)s::text[] IS NULL OR l.classification = ANY(%(classifications)s::text[]))
           AND (%(sources)s::text[] IS NULL OR l.source = ANY(%(sources)s::text[]))
           AND COALESCE(l.confidence, 0) >= %(min_confidence)s
         ORDER BY {sort_clause}
         LIMIT %(limit)s
    """

    params = {
        "lookback_days": lookback_days,
        "classifications": classifications,
        "sources": sources,
        "min_confidence": min_confidence,
        "limit": limit,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    result = []
    for r in rows:
        # risk_flags 는 JSONB — psycopg 가 list 또는 None 으로 변환. None 이면 빈 리스트로.
        rf = r[12] if r[12] is not None else []
        result.append(ClassificationRow(
            symbol=r[0],
            name=r[1],
            market=r[2],
            sector=r[3],
            classification=r[4],
            pattern=r[5],
            pivot_price=float(r[6]) if r[6] is not None else None,
            pivot_basis=r[7],
            base_high=float(r[8]) if r[8] is not None else None,
            base_low=float(r[9]) if r[9] is not None else None,
            base_depth_pct=float(r[10]) if r[10] is not None else None,
            base_start_date=r[11],
            risk_flags=rf if isinstance(rf, list) else [],
            confidence=float(r[13]) if r[13] is not None else None,
            reasoning=r[14],
            source=r[15],
            classified_at=r[16],
            expires_at=r[17],
            llm_call_duration_s=float(r[18]) if r[18] is not None else None,
            llm_input_tokens=r[19],
            llm_output_tokens=r[20],
        ))
    return result
```

### Step 4: `api/main.py` 에 router include

`api/main.py` 의 router import 섹션에 추가:

```python
from api.routers import classifications  # ← 추가
```

`app.include_router(...)` 들 중에 추가:

```python
app.include_router(classifications.router)
```

### Step 5: 테스트 통과 확인

```bash
cd ~/kr-by-claude
uv run pytest tests/test_api_classifications.py -v
```

Expected: 8 passed.

### Step 6: 기존 회귀 확인

```bash
uv run pytest tests/ -v 2>&1 | tail -10
```

기존 passing 유지 (286 정도) + 신규 8 추가 = ~294. pre-existing failures 동일.

### Step 7: Commit

```bash
cd ~/kr-by-claude
git add api/routers/classifications.py api/main.py tests/test_api_classifications.py
git commit -m "feat(api): GET /api/classifications — DISTINCT ON (symbol) + 필터/정렬"
```

**NEVER add `Co-Authored-By: Claude` trailer.**

---

## Task 2: Frontend — types + 라우팅

**Files:**
- Modify: `web/src/lib/types.ts` — Classification 타입 추가
- Modify: `web/src/App.tsx` — NAV_ITEMS + 라우트 추가

라우트 + 사이드바 메뉴 항목 추가. ClassificationsPage 컴포넌트는 Task 3 에서. 일단 placeholder 또는 빈 컴포넌트라도 라우트 동작 확인.

### Step 1: types.ts 에 타입 추가

`web/src/lib/types.ts` 끝에 append:

```typescript
export interface Classification {
  symbol: string;
  name: string;
  market: string;
  sector: string | null;
  classification: string;
  pattern: string | null;
  pivot_price: number | null;
  pivot_basis: string | null;
  base_high: number | null;
  base_low: number | null;
  base_depth_pct: number | null;
  base_start_date: string | null;
  risk_flags: string[];
  confidence: number | null;
  reasoning: string | null;
  source: string;
  classified_at: string;
  expires_at: string | null;
  llm_call_duration_s: number | null;
  llm_input_tokens: number | null;
  llm_output_tokens: number | null;
}
```

### Step 2: App.tsx 에 라우트 + NAV_ITEMS 추가

`web/src/App.tsx`:

1. Import 추가:
   ```tsx
   import ClassificationsPage from "./pages/ClassificationsPage";
   import { ListChecks } from "lucide-react";  // 기존 lucide-react import 줄 안에 ListChecks 추가
   ```

2. `NAV_ITEMS` 배열에 항목 추가 (Performance 와 Runner 사이):
   ```tsx
   const NAV_ITEMS: NavItem[] = [
     { to: "/", label: "Overview", kr: "총괄", Icon: LayoutDashboard },
     { to: "/heatmap", label: "Sectors", kr: "섹터 히트맵", Icon: LayoutGrid },
     { to: "/chart", label: "Chart", kr: "차트", Icon: LineChart },
     { to: "/minervini", label: "Minervini", kr: "미너비니", Icon: Sparkles },
     { to: "/signals", label: "Signals", kr: "시그널", Icon: Zap },
     { to: "/performance", label: "Performance", kr: "시그널 성과", Icon: TrendingUp },
     { to: "/classifications", label: "Classifications", kr: "LLM 분류", Icon: ListChecks },  // ← 추가
     { to: "/runner", label: "Runner", kr: "분석 운영", Icon: Wrench },
     { to: "/prompt", label: "LLM Prompt", kr: "LLM 프롬프트", Icon: FileArchive },
   ];
   ```

3. `<Routes>` 블록에 라우트 추가 (기존 라우트들 사이 적절한 위치):
   ```tsx
   <Route path="/classifications" element={<ClassificationsPage />} />
   ```

### Step 3: ClassificationsPage 가 아직 없으므로 placeholder 생성

`web/src/pages/ClassificationsPage.tsx` 임시 placeholder (Task 3 에서 본문 작성):

```tsx
export default function ClassificationsPage() {
  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <h2>LLM 분류 — 작업 중</h2>
    </div>
  );
}
```

### Step 4: tsc

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

### Step 5: Commit

```bash
cd ~/kr-by-claude
git add web/src/lib/types.ts web/src/App.tsx web/src/pages/ClassificationsPage.tsx
git commit -m "feat(web): /classifications 라우트 + 사이드바 'LLM 분류' 메뉴 + placeholder"
```

---

## Task 3: Frontend — `ClassificationsPage` 컴포넌트

**Files:**
- Modify (overwrite placeholder): `web/src/pages/ClassificationsPage.tsx`

페이지 본문 — 헤더 + 필터 바 + 그룹별 collapsible 리스트 + row expand + 차트 라우팅.

### Step 1: 컴포넌트 작성

`web/src/pages/ClassificationsPage.tsx` 를 다음으로 교체:

```tsx
import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  ChevronDown,
  LineChart,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";
import { api } from "../lib/api";
import type { Classification } from "../lib/types";
import { relativeTime, formatKst } from "../lib/utils";
import { Tooltip } from "../components/ui/Tooltip";


type SortOption = "classified_at_desc" | "confidence_desc";


interface Filters {
  lookback_days: number;
  classifications: string[];  // ["watch", "entry", "ignore"]
  sources: string[];           // ["weekend", "daily-delta"]
  min_confidence: number;
  sort: SortOption;
}


const DEFAULT_FILTERS: Filters = {
  lookback_days: 14,
  classifications: ["watch", "entry"],  // ignore 기본 미선택
  sources: ["weekend", "daily-delta"],
  min_confidence: 0.0,
  sort: "classified_at_desc",
};

const CLASSIFICATION_ORDER = ["watch", "entry", "ignore"] as const;

const CLASSIFICATION_LABELS: Record<string, string> = {
  watch: "Watch",
  entry: "Entry",
  ignore: "Ignore",
};

const CLASSIFICATION_TONES: Record<string, string> = {
  watch: "bg-tint-blue text-blue",
  entry: "bg-success-soft text-success",
  ignore: "bg-tint-stone text-muted",
};


function buildQueryString(filters: Filters): string {
  const params = new URLSearchParams();
  params.set("lookback_days", String(filters.lookback_days));
  for (const c of filters.classifications) params.append("classifications", c);
  for (const s of filters.sources) params.append("sources", s);
  params.set("min_confidence", String(filters.min_confidence));
  params.set("sort", filters.sort);
  return params.toString();
}


function ClassificationChip({ classification }: { classification: string }) {
  const tone = CLASSIFICATION_TONES[classification] ?? "bg-tint-stone text-muted";
  const label = CLASSIFICATION_LABELS[classification] ?? classification;
  return <span className={`chip ${tone}`}>{label}</span>;
}


function RowHeader({
  row,
  expanded,
  onToggle,
}: {
  row: Classification;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      onClick={onToggle}
      className="flex items-center gap-3 px-4 py-3 hover:bg-cream cursor-pointer"
    >
      <span className="text-faint shrink-0">
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </span>
      <span className="num text-data text-ink shrink-0">{row.symbol}</span>
      <span className="text-data text-ink truncate flex-1 min-w-0">{row.name}</span>
      <ClassificationChip classification={row.classification} />
      {row.pattern && (
        <span className="text-data-xs text-muted">{row.pattern}</span>
      )}
      {row.confidence != null && (
        <span className="num text-data-xs text-faint shrink-0">
          conf {row.confidence.toFixed(2)}
        </span>
      )}
      <Tooltip
        content={
          <>
            <div className="num">분류: {formatKst(row.classified_at)}</div>
            {row.expires_at && (
              <div className="num">만료: {formatKst(row.expires_at)}</div>
            )}
            <div className="text-faint mt-1">(KST)</div>
          </>
        }
      >
        <span className="text-data-xs text-faint shrink-0 cursor-help underline decoration-dotted decoration-faint underline-offset-2">
          {relativeTime(row.classified_at)}
        </span>
      </Tooltip>
    </div>
  );
}


function RowDetails({ row }: { row: Classification }) {
  return (
    <div className="px-10 pb-4 space-y-3 bg-cream/50">
      {/* Base / Pivot 정보 */}
      <div className="grid grid-cols-2 gap-4 text-data-xs">
        {row.pivot_price != null && (
          <div>
            <div className="caps text-faint">Pivot</div>
            <div className="num text-data text-ink">
              {row.pivot_price.toLocaleString()}{" "}
              {row.pivot_basis && (
                <span className="text-data-xs text-faint">({row.pivot_basis})</span>
              )}
            </div>
          </div>
        )}
        {row.base_high != null && row.base_low != null && (
          <div>
            <div className="caps text-faint">Base</div>
            <div className="num text-data text-ink">
              {row.base_low.toLocaleString()} ~ {row.base_high.toLocaleString()}
              {row.base_depth_pct != null && (
                <span className="text-data-xs text-faint"> ({row.base_depth_pct.toFixed(1)}%)</span>
              )}
              {row.base_start_date && (
                <div className="text-data-xs text-faint">{row.base_start_date} 부터</div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Risk flags */}
      {row.risk_flags && row.risk_flags.length > 0 && (
        <div>
          <div className="caps text-faint mb-1">Risk Flags</div>
          <div className="flex flex-wrap gap-1">
            {row.risk_flags.map((flag) => (
              <span key={flag} className="chip bg-amber-soft text-amber">
                <AlertTriangle size={11} /> {flag}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Reasoning */}
      {row.reasoning && (
        <div>
          <div className="caps text-faint mb-1">Reasoning</div>
          <div className="text-data text-ink whitespace-pre-wrap bg-paper border border-hairline rounded-lg p-3 max-h-64 overflow-auto leading-relaxed">
            {row.reasoning}
          </div>
        </div>
      )}

      {/* 메타 */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-data-xs text-faint num">
        <span>source: {row.source}</span>
        {row.llm_call_duration_s != null && (
          <span>duration: {row.llm_call_duration_s.toFixed(1)}s</span>
        )}
        {row.llm_input_tokens != null && (
          <span>in: {row.llm_input_tokens.toLocaleString()} tok</span>
        )}
        {row.llm_output_tokens != null && (
          <span>out: {row.llm_output_tokens.toLocaleString()} tok</span>
        )}
      </div>

      {/* 차트 보기 */}
      <Link
        to={`/chart/${row.symbol}`}
        onClick={(e) => e.stopPropagation()}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white rounded-lg text-data-xs font-semibold hover:bg-accent-light"
      >
        <LineChart size={11} /> 차트 보기
      </Link>
    </div>
  );
}


function ClassificationGroup({
  classification,
  rows,
  expandedRows,
  onToggleRow,
}: {
  classification: string;
  rows: Classification[];
  expandedRows: Set<string>;
  onToggleRow: (symbol: string) => void;
}) {
  const [groupOpen, setGroupOpen] = useState(classification !== "ignore");

  if (rows.length === 0) return null;

  return (
    <section className="bento mb-4 overflow-hidden">
      <div
        onClick={() => setGroupOpen(!groupOpen)}
        className="flex items-center gap-2 px-4 py-3 cursor-pointer hover:bg-cream"
      >
        <span className="text-faint">
          {groupOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <ClassificationChip classification={classification} />
        <span className="text-data text-muted">{rows.length} 건</span>
      </div>
      {groupOpen && (
        <div className="border-t border-hairline">
          {rows.map((row, idx) => (
            <div
              key={row.symbol}
              className={idx < rows.length - 1 ? "border-b border-hairline" : ""}
            >
              <RowHeader
                row={row}
                expanded={expandedRows.has(row.symbol)}
                onToggle={() => onToggleRow(row.symbol)}
              />
              {expandedRows.has(row.symbol) && <RowDetails row={row} />}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}


export default function ClassificationsPage() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const qs = buildQueryString(filters);
  const q = useQuery<Classification[]>({
    queryKey: ["classifications", qs],
    queryFn: () => api<Classification[]>(`/classifications?${qs}`),
  });

  const rowsByClassification = useMemo(() => {
    const grouped: Record<string, Classification[]> = {
      watch: [],
      entry: [],
      ignore: [],
    };
    for (const row of q.data ?? []) {
      const c = grouped[row.classification] ?? (grouped[row.classification] = []);
      c.push(row);
    }
    return grouped;
  }, [q.data]);

  const counts = {
    watch: rowsByClassification.watch?.length ?? 0,
    entry: rowsByClassification.entry?.length ?? 0,
    ignore: rowsByClassification.ignore?.length ?? 0,
  };

  const toggleRow = (symbol: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  };

  const toggleClassification = (c: string) => {
    setFilters((prev) => ({
      ...prev,
      classifications: prev.classifications.includes(c)
        ? prev.classifications.filter((x) => x !== c)
        : [...prev.classifications, c],
    }));
  };

  const toggleSource = (s: string) => {
    setFilters((prev) => ({
      ...prev,
      sources: prev.sources.includes(s)
        ? prev.sources.filter((x) => x !== s)
        : [...prev.sources, s],
    }));
  };

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Classifications</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            LLM 분류
          </h2>
          <div className="flex gap-2 mt-3">
            <span className="chip bg-tint-blue text-blue">Watch {counts.watch}</span>
            <span className="chip bg-success-soft text-success">Entry {counts.entry}</span>
            <span className="chip bg-tint-stone text-muted">Ignore {counts.ignore}</span>
          </div>
        </div>
        <button
          onClick={() => q.refetch()}
          className="flex items-center gap-1.5 text-data text-muted hover:text-ink"
        >
          <RefreshCw size={14} />
          새로고침
        </button>
      </header>

      {/* 필터 바 */}
      <section className="bento p-4 mb-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2">
            <span className="caps text-faint">최근</span>
            <select
              value={filters.lookback_days}
              onChange={(e) => setFilters({ ...filters, lookback_days: parseInt(e.target.value, 10) })}
              className="num text-data px-2 py-1 border border-hairline rounded-lg bg-paper"
            >
              <option value={7}>7일</option>
              <option value={14}>14일</option>
              <option value={30}>30일</option>
              <option value={90}>90일</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">분류</span>
            {(["watch", "entry", "ignore"] as const).map((c) => (
              <label key={c} className="flex items-center gap-1 cursor-pointer text-data-xs">
                <input
                  type="checkbox"
                  checked={filters.classifications.includes(c)}
                  onChange={() => toggleClassification(c)}
                  className="accent-accent"
                />
                {CLASSIFICATION_LABELS[c]}
              </label>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">소스</span>
            {(["weekend", "daily-delta"] as const).map((s) => (
              <label key={s} className="flex items-center gap-1 cursor-pointer text-data-xs">
                <input
                  type="checkbox"
                  checked={filters.sources.includes(s)}
                  onChange={() => toggleSource(s)}
                  className="accent-accent"
                />
                {s}
              </label>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">최소 conf</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={filters.min_confidence}
              onChange={(e) => setFilters({ ...filters, min_confidence: parseFloat(e.target.value) || 0 })}
              className="num text-data w-20 px-2 py-1 border border-hairline rounded-lg"
            />
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">정렬</span>
            <select
              value={filters.sort}
              onChange={(e) => setFilters({ ...filters, sort: e.target.value as SortOption })}
              className="text-data px-2 py-1 border border-hairline rounded-lg bg-paper"
            >
              <option value="classified_at_desc">시각 최신</option>
              <option value="confidence_desc">Confidence</option>
            </select>
          </div>
        </div>
      </section>

      {/* 리스트 */}
      {q.isLoading && <div className="text-muted">로딩 중…</div>}
      {q.isError && <div className="text-danger">에러: {String(q.error)}</div>}
      {q.data && q.data.length === 0 && (
        <div className="bento p-8 text-center text-muted">
          최근 {filters.lookback_days}일간 분류 결과 없음.
          <div className="text-data-xs text-faint mt-2">
            /runner 에서 'LLM 주말 분류' 또는 'LLM 평일 전체 분석' 실행.
          </div>
        </div>
      )}
      {q.data && q.data.length > 0 && (
        <>
          {CLASSIFICATION_ORDER.map((c) => (
            <ClassificationGroup
              key={c}
              classification={c}
              rows={rowsByClassification[c] ?? []}
              expandedRows={expandedRows}
              onToggleRow={toggleRow}
            />
          ))}
        </>
      )}
    </div>
  );
}
```

### Step 2: tsc

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors. 만약 Tailwind 클래스 (`bg-tint-blue`, `text-blue`, `bg-amber-soft`, `text-amber`) 가 정의되지 않았다면 비슷한 클래스로 대체 (예: `bg-blue-100 text-blue-700`). 프로젝트의 tailwind config 확인.

### Step 3: Commit

```bash
cd ~/kr-by-claude
git add web/src/pages/ClassificationsPage.tsx
git commit -m "feat(web): ClassificationsPage — 헤더/필터/그룹별 리스트/row expand/차트 라우팅"
```

---

## Task 4: Goal State 검증

- [ ] **Step 1: Backend 회귀**

```bash
cd ~/kr-by-claude
uv run pytest 2>&1 | tail -3
```

Expected: 기존 + 신규 8 = ~294 passed / 20 pre-existing failed.

- [ ] **Step 2: Frontend tsc**

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: 라이브 API 검증**

```bash
pkill -f "uvicorn api.main" 2>/dev/null; sleep 1
cd ~/kr-by-claude
uv run uvicorn api.main:app --port 8000 --log-level warning > /tmp/uvicorn.log 2>&1 &
sleep 3

echo "=== GET /api/classifications ==="
curl -s -w "\nHTTP %{http_code}\n" "http://localhost:8000/api/classifications?lookback_days=30" | python3 -c "
import sys, json
text = sys.stdin.read()
body, status = text.rsplit('\nHTTP ', 1)
print(f'status: {status.strip()}')
d = json.loads(body)
print(f'rows: {len(d)}')
for r in d[:5]:
    print(f'  {r[\"symbol\"]:10s} {r[\"classification\"]:8s} conf={r[\"confidence\"]} source={r[\"source\"]}')
"

echo ""
echo "=== 필터: classifications=watch ==="
curl -s "http://localhost:8000/api/classifications?classifications=watch" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'watch only: {len(d)} rows')
"
```

Expected:
- 첫 호출 HTTP 200, 사용자가 방금 돌린 weekend 분류 3건 (CLSTEST 가 아닌 실제 종목 코드) 포함
- watch 필터 시 watch 만 (사용자 시험 데이터 기준 1건: 001450)

- [ ] **Step 4: 수동 브라우저 검증 (사용자가 직접)**

`http://localhost:5173/classifications` 에서:
1. 헤더 카운트 칩 (Watch / Entry / Ignore) 표시
2. 필터 바 — 14일 / watch+entry 체크 / source 둘 다 / 정렬 시각 최신 (default)
3. 그룹별 리스트 (watch / entry / ignore) — ignore 기본 접힘
4. row 클릭 → expand → reasoning 전문 + risk_flags + 메타 + [차트 보기]
5. [차트 보기] 클릭 → `/chart/<symbol>` 라우팅
6. 다른 row 클릭 → 동시 expand 가능
7. 필터 조작 → 결과 즉시 새로고침
8. 사이드바 "LLM 분류" 메뉴 표시

- [ ] **Step 5: git status**

```bash
git status
```

Expected: clean working tree.

---

## Self-Review

✅ **Spec coverage**:
- 1. 라우팅 & 네비게이션 → Task 2 (App.tsx + ClassificationsPage placeholder)
- 2-1. GET /api/classifications endpoint → Task 1 (Pydantic 모델 + 쿼리 파라미터 + SQL DISTINCT ON + sort_clause allowlist)
- 2-2. 파일 위치 (api/routers/classifications.py) → Task 1 Step 3
- 3-1. Frontend 타입 → Task 2 Step 1
- 3-2. ClassificationsPage 컴포넌트 (헤더/필터/리스트/row expand/차트 라우팅) → Task 3
- 3-3. App.tsx 변경 → Task 2 Step 2
- 4. Testing → Task 1 Step 1 (8 tests) + Task 4 수동 검증
- Out of scope (종목별 이력 / expires_at 자동 숨김 등) → 명시적으로 제외

✅ **Placeholder scan**: TBD/TODO 없음. 모든 step 에 실제 코드 + 명령 + 기대 출력.

✅ **Type consistency**:
- `ClassificationRow` (Pydantic, Task 1) ↔ `Classification` (TS, Task 2) — 필드명/타입 1:1 매칭. 단 Pydantic 의 `date`/`datetime` 이 JSON 직렬화 시 ISO string 으로 변환되어 TS 의 `string` 과 호환 ✓
- `SORT_CLAUSES` allowlist (`classified_at_desc` / `confidence_desc`) 가 Task 1 backend ↔ Task 3 frontend `SortOption` 동일 ✓
- `Filters.classifications: string[]` 의 값 (`"watch"|"entry"|"ignore"`) 가 SQL classification 컬럼 값과 일치 ✓

⚠️ **알려진 한계**:
- `weekly_classification.risk_flags` 가 JSONB 인데 (Task 1 Step 3 코드) `psycopg` 가 list 또는 None 또는 dict 반환할 수 있음 — 코드에서 `isinstance(rf, list)` 가드 추가했음. 실제로 어떤 형태인지 라이브 데이터로 검증 필요.
- Tailwind 클래스 `bg-tint-blue` / `text-blue` / `bg-amber-soft` / `text-amber` 가 프로젝트 config 에 정의되어 있다고 가정. 없으면 표준 Tailwind 색 (예: `bg-blue-100 text-blue-700`) 으로 대체.
