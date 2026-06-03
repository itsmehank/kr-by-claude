# 차트 분류/미너비니 오버레이 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 차트 배경에 분류(entry/watch/ignore/fail) 색 밴드를 토글 1개로 오버레이한다. 기존 차트 동작(호버 툴팁·드래그·줌)은 그대로.

**Architecture:** 백엔드에 분류 시계열 history 엔드포인트(라이브+백필 UNION)를 추가하고, 프론트는 순수 함수로 날짜별 배타 상태 세그먼트를 만들어 차트 위 투명 오버레이 div(`pointer-events:none`)에 밴드로 그린다. 위치는 `timeScale().timeToCoordinate` + `subscribeVisibleTimeRangeChange`/`ResizeObserver` 로 동기화. 기존 PriceChart 시리즈 코드는 무수정.

**Tech Stack:** FastAPI/psycopg(pytest) + React/TS, lightweight-charts v5.2 (client). **web/ 단위테스트 프레임워크 없음** → 프론트 검증은 `npx tsc -b` + `npm run lint` + 앱 수동.

**Spec:** `docs/superpowers/specs/2026-06-03-chart-classification-minervini-overlay-design.md`

---

## File Structure

- `api/schemas/classification.py` — `ClassificationHistoryRow` 모델 추가.
- `api/routers/classifications.py` — `GET /api/classifications/history/{ticker}` 핸들러 추가.
- `tests/test_api_classifications.py` — history 엔드포인트 테스트 추가.
- `web/src/components/charts/overlayBands.ts` — 신규. 타입/색 + 순수 `buildBandSegments`.
- `web/src/components/charts/ChartOverlayBands.tsx` — 신규. 오버레이 렌더(차트 좌표 동기화).
- `web/src/components/charts/PriceChart.tsx` — 차트 인스턴스 state 노출 + 오버레이 자식 + 새 props(무수정 시리즈).
- `web/src/pages/ChartPage.tsx` — history fetch, minervini_pass 매핑, 세그먼트 계산, 토글.
- `web/src/lib/types.ts` — `PriceChartBar.minervini_pass` 추가 + history 응답 타입.

web 명령은 `cd /Users/hank.es/git/personal/kr-by-claude/web && <cmd>`. pytest 는 repo 루트 `uv run pytest`. baseline isolation fail(~26) 늘리지 않기.

---

### Task 1: 백엔드 — 분류 history 엔드포인트

**Files:**
- Modify: `api/schemas/classification.py`
- Modify: `api/routers/classifications.py`
- Test: `tests/test_api_classifications.py`

- [ ] **Step 1: 테스트 작성 (실패하도록)**

`tests/test_api_classifications.py` 끝에 추가. (이 파일의 기존 테스트가 쓰는 fixture 패턴을 따른다 — `client`/`db` 사용. 아래는 db 직접 insert + TestClient 호출; 기존 테스트의 fixture 이름에 맞춰 조정.)

```python
def test_classification_history_unions_live_and_backfill(client, db):
    """history 엔드포인트: weekly_classification + classification_backfill 합쳐 날짜순 반환, 같은 날짜 라이브 우선."""
    from datetime import date, datetime, timezone
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('HST1','H','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM weekly_classification WHERE symbol='HST1'")
        cur.execute("DELETE FROM classification_backfill WHERE symbol='HST1'")
        # 라이브: 2025-02-01 watch
        cur.execute("""INSERT INTO weekly_classification (symbol, classified_at, analyzed_for_date, market, classification, source)
                       VALUES ('HST1', %s, %s, 'KOSPI', 'watch', 'weekend')""",
                    (datetime(2025, 2, 2, tzinfo=timezone.utc), date(2025, 2, 1)))
        # 백필: 2025-01-04 ignore, 2025-02-01 entry(중복 날짜 → 라이브 우선이라 무시돼야)
        cur.execute("""INSERT INTO classification_backfill (symbol, classified_at, analyzed_for_date, market, classification, source)
                       VALUES ('HST1', %s, %s, 'KOSPI', 'ignore', 'backfill')""",
                    (datetime(2025, 1, 5, tzinfo=timezone.utc), date(2025, 1, 4)))
        cur.execute("""INSERT INTO classification_backfill (symbol, classified_at, analyzed_for_date, market, classification, source)
                       VALUES ('HST1', %s, %s, 'KOSPI', 'entry', 'backfill')""",
                    (datetime(2025, 2, 1, tzinfo=timezone.utc), date(2025, 2, 1)))
    db.commit()
    try:
        r = client.get("/api/classifications/history/HST1?start=2025-01-01&end=2025-03-01")
        assert r.status_code == 200
        rows = r.json()
        # 날짜 오름차순, 같은 2025-02-01 은 라이브(watch) 1건만
        assert [(x["date"], x["classification"]) for x in rows] == [
            ("2025-01-04", "ignore"),
            ("2025-02-01", "watch"),
        ]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='HST1'")
            cur.execute("DELETE FROM classification_backfill WHERE symbol='HST1'")
        db.commit()


def test_classification_history_empty_for_unknown_ticker(client):
    r = client.get("/api/classifications/history/NOPE1?start=2025-01-01&end=2025-03-01")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `uv run pytest tests/test_api_classifications.py::test_classification_history_unions_live_and_backfill tests/test_api_classifications.py::test_classification_history_empty_for_unknown_ticker -v`
Expected: FAIL — 404 (라우트 없음).

- [ ] **Step 3: 스키마 추가**

`api/schemas/classification.py` 에 모델 추가(파일 끝):

```python
class ClassificationHistoryRow(BaseModel):
    symbol: str
    date: date
    classification: str
    source: str
```

(파일 상단에 `from datetime import date` 와 `from pydantic import BaseModel` 가 이미 있는지 확인하고 없으면 추가.)

- [ ] **Step 4: 핸들러 추가**

`api/routers/classifications.py` 에 import 보강 + 핸들러 추가:

상단 import 에 `ClassificationHistoryRow` 추가:
```python
from api.schemas.classification import ClassificationRow, ClassificationHistoryRow
from datetime import date as _date, timedelta
```

파일 끝에 핸들러 추가:
```python
@router.get("/history/{ticker}", response_model=list[ClassificationHistoryRow])
def get_classification_history(
    ticker: str,
    start: _date | None = None,
    end: _date | None = None,
    conn: Connection = Depends(get_conn),
):
    """종목의 분류 시계열 — weekly_classification(라이브) + classification_backfill 합산.

    같은 날짜 중복 시 라이브 우선(source_rank 0 < 1), 그다음 classified_at 최신.
    날짜 = COALESCE(analyzed_for_date, classified_at::date).
    """
    if start is None:
        start = _date.today() - timedelta(days=365)
    if end is None:
        end = _date.today()

    sql = """
        WITH combined AS (
          SELECT COALESCE(analyzed_for_date, classified_at::date) AS d,
                 classification, classified_at, 0 AS source_rank, 'live' AS src
            FROM weekly_classification
           WHERE symbol = %(ticker)s
             AND COALESCE(analyzed_for_date, classified_at::date) BETWEEN %(start)s AND %(end)s
          UNION ALL
          SELECT analyzed_for_date AS d,
                 classification, classified_at, 1 AS source_rank, 'backfill' AS src
            FROM classification_backfill
           WHERE symbol = %(ticker)s
             AND analyzed_for_date BETWEEN %(start)s AND %(end)s
        )
        SELECT DISTINCT ON (d) d, classification, src
          FROM combined
         ORDER BY d ASC, source_rank ASC, classified_at DESC
    """
    params = {"ticker": ticker, "start": start, "end": end}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [ClassificationHistoryRow(symbol=ticker, date=r[0], classification=r[1], source=r[2]) for r in rows]
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_api_classifications.py -v`
Expected: 전체 PASS (신규 2개 포함).

- [ ] **Step 6: Commit**

```bash
git add api/schemas/classification.py api/routers/classifications.py tests/test_api_classifications.py
git commit -m "feat(chart): 분류 history 엔드포인트 (라이브+백필 UNION, 라이브 우선)"
```

---

### Task 2: 프론트 — 세그먼트 빌더 + 오버레이 컴포넌트 + 타입

**Files:**
- Create: `web/src/components/charts/overlayBands.ts`
- Create: `web/src/components/charts/ChartOverlayBands.tsx`
- Modify: `web/src/lib/types.ts`

(모두 신규 파일 + 기존 타입에 optional 필드 추가라 단독으로 tsc 통과. 아직 어디서도 import 안 해도 됨.)

- [ ] **Step 1: 세그먼트 빌더 + 타입/색 작성**

`web/src/components/charts/overlayBands.ts` 신규:

```ts
export type BandState = "entry" | "watch" | "ignore" | "fail";

export interface BandSegment {
  startDate: string; // YYYY-MM-DD inclusive
  endDate: string;   // YYYY-MM-DD inclusive
  state: BandState;
}

export const BAND_COLORS: Record<BandState, string> = {
  entry: "rgba(22,163,74,0.18)",
  watch: "rgba(37,99,235,0.18)",
  ignore: "rgba(156,163,175,0.18)",
  fail: "rgba(220,38,38,0.18)",
};

export const BAND_LABELS: Record<BandState, string> = {
  entry: "entry",
  watch: "watch",
  ignore: "ignore",
  fail: "미통과/탈락",
};

export interface BandBar {
  date: string;
  minervini_pass: boolean | null;
}

export interface ClassificationPoint {
  date: string;
  classification: string;
}

const COLORED = new Set<string>(["entry", "watch", "ignore"]);

/**
 * 날짜별 배타 상태로 분류 밴드 세그먼트를 만든다.
 * 규칙: minervini_pass === false → "fail"(우선). 아니면 그 날짜 이하 가장 최근 분류(entry/watch/ignore)
 * 를 이월(carry-forward). disqualified/분류없음 → 밴드 없음(none). 연속 동일 상태는 하나로 병합.
 * bars 와 points 는 날짜 오름차순 가정(points 는 방어적 정렬).
 */
export function buildBandSegments(
  bars: BandBar[],
  points: ClassificationPoint[],
): BandSegment[] {
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const segments: BandSegment[] = [];
  let pi = 0;
  let carried: BandState | null = null;
  let cur: BandSegment | null = null;

  for (const bar of bars) {
    while (pi < sorted.length && sorted[pi].date <= bar.date) {
      const c = sorted[pi].classification;
      carried = COLORED.has(c) ? (c as BandState) : null;
      pi++;
    }
    const state: BandState | null = bar.minervini_pass === false ? "fail" : carried;

    if (state === null) {
      if (cur) { segments.push(cur); cur = null; }
      continue;
    }
    if (cur && cur.state === state) {
      cur.endDate = bar.date;
    } else {
      if (cur) segments.push(cur);
      cur = { startDate: bar.date, endDate: bar.date, state };
    }
  }
  if (cur) segments.push(cur);
  return segments;
}
```

- [ ] **Step 2: 오버레이 컴포넌트 작성**

`web/src/components/charts/ChartOverlayBands.tsx` 신규:

```tsx
import { useEffect, useState, type RefObject } from "react";
import type { IChartApi, Time } from "lightweight-charts";
import type { BandSegment } from "./overlayBands";
import { BAND_COLORS } from "./overlayBands";

interface Rect {
  left: number;
  width: number;
  color: string;
}

interface ChartOverlayBandsProps {
  chart: IChartApi | null;
  containerRef: RefObject<HTMLDivElement | null>;
  segments: BandSegment[];
  visible: boolean;
}

export function ChartOverlayBands({ chart, containerRef, segments, visible }: ChartOverlayBandsProps) {
  const [rects, setRects] = useState<Rect[]>([]);

  useEffect(() => {
    if (!chart || !visible || segments.length === 0) {
      setRects([]);
      return;
    }
    const ts = chart.timeScale();
    const recompute = () => {
      const vr = ts.getVisibleRange();
      if (!vr) {
        setRects([]);
        return;
      }
      const from = String(vr.from);
      const to = String(vr.to);
      const out: Rect[] = [];
      for (const seg of segments) {
        if (seg.endDate < from || seg.startDate > to) continue; // 화면 밖
        const cs = seg.startDate < from ? from : seg.startDate;
        const ce = seg.endDate > to ? to : seg.endDate;
        const x1 = ts.timeToCoordinate(cs as Time);
        const x2 = ts.timeToCoordinate(ce as Time);
        if (x1 === null || x2 === null) continue;
        const left = Math.min(x1, x2);
        const right = Math.max(x1, x2);
        out.push({ left, width: Math.max(1, right - left), color: BAND_COLORS[seg.state] });
      }
      setRects(out);
    };
    recompute();
    ts.subscribeVisibleTimeRangeChange(recompute);
    const container = containerRef.current;
    const ro = container ? new ResizeObserver(recompute) : null;
    if (ro && container) ro.observe(container);
    return () => {
      ts.unsubscribeVisibleTimeRangeChange(recompute);
      ro?.disconnect();
    };
  }, [chart, containerRef, segments, visible]);

  if (!visible) return null;
  return (
    <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
      {rects.map((r, i) => (
        <div
          key={i}
          style={{ position: "absolute", left: r.left, width: r.width, top: 0, bottom: 0, background: r.color }}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: PriceChartBar 에 minervini_pass 추가**

`web/src/lib/types.ts` 의 `PriceChartBar` 인터페이스에 필드 추가(기존 필드 뒤, optional 로 — 기존 호출 영향 없음):

```ts
  minervini_pass?: boolean | null;
```

(`PriceChartBar` 인터페이스 안 마지막 필드 다음 줄에 삽입.)

- [ ] **Step 4: 타입체크 + Lint**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc -b && npm run lint`
Expected: 통과. 신규 파일/타입 관련 새 에러 없음(미사용 export 는 에러 아님). 기존 ~20 lint baseline 무관.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/charts/overlayBands.ts web/src/components/charts/ChartOverlayBands.tsx web/src/lib/types.ts
git commit -m "feat(chart): 밴드 세그먼트 빌더 + 오버레이 컴포넌트 + PriceChartBar.minervini_pass"
```

---

### Task 3: 프론트 — PriceChart/ChartPage 통합 + 토글

**Files:**
- Modify: `web/src/components/charts/PriceChart.tsx`
- Modify: `web/src/pages/ChartPage.tsx`

(PriceChart 와 ChartPage 를 함께 바꿔 한 커밋 — 중간 빌드 깨짐 방지.)

- [ ] **Step 1: PriceChart — 차트 인스턴스 state + 새 props**

`web/src/components/charts/PriceChart.tsx`:

(a) 상단 import 에 추가:
```tsx
import { ChartOverlayBands } from "./ChartOverlayBands";
import type { BandSegment } from "./overlayBands";
```
lightweight-charts import 에 `type IChartApi` 가 없으면 추가:
```tsx
import { createChart, /* 기존들 */ } from "lightweight-charts";
import type { IChartApi } from "lightweight-charts";
```

(b) `PriceChartProps` 인터페이스에 추가:
```tsx
  showClassificationBands?: boolean;
  bandSegments?: BandSegment[];
```

(c) 컴포넌트 본문 상단(다른 useState 들 근처)에 차트 인스턴스 state 추가:
```tsx
  const [chartApi, setChartApi] = useState<IChartApi | null>(null);
```

(d) 메인 useEffect 안에서 `const chart = createChart(...)` 직후에:
```tsx
    setChartApi(chart);
```
그리고 cleanup(`return () => { ... chart.remove(); }`) 안 `chart.remove();` 앞에:
```tsx
      setChartApi(null);
```

(e) return JSX 의 wrapper(`<div ref={wrapperRef} className="relative">`) 안, `<div ref={containerRef} .../>` **바로 다음 줄**에 오버레이 추가:
```tsx
      <ChartOverlayBands
        chart={chartApi}
        containerRef={containerRef}
        segments={bandSegments ?? []}
        visible={showClassificationBands ?? false}
      />
```

(f) 함수 시그니처 구조분해에 새 props 추가: `showClassificationBands`, `bandSegments`.

기존 시리즈/마커/툴팁/볼륨 코드는 변경하지 않는다.

- [ ] **Step 2: ChartPage — history fetch + minervini_pass 매핑 + 세그먼트 + 토글**

`web/src/pages/ChartPage.tsx`:

(a) import 추가:
```tsx
import { buildBandSegments, type BandSegment, type ClassificationPoint } from "../components/charts/overlayBands";
```
(기존 types import 에 `ClassificationHistoryRow` 가 필요하면 추가 — 아래 (b) 참조.)

(b) `web/src/lib/types.ts` 에 history 응답 타입 추가(없으면):
```ts
export interface ClassificationHistoryRow {
  symbol: string;
  date: string;
  classification: string;
  source: string;
}
```

(c) `dailyToBar` 에 `minervini_pass: d.minervini_pass` 추가, `weeklyToBar` 에 `minervini_pass: null` 추가:
```tsx
// dailyToBar 의 return 객체 마지막에
    minervini_pass: d.minervini_pass,
// weeklyToBar 의 return 객체 마지막에 (주봉은 일봉 minervini 기준과 달라 v1 에선 미표시)
    minervini_pass: null,
```

(d) 토글 state 추가(다른 show* state 들 근처):
```tsx
  const [showClassificationBands, setShowClassificationBands] = useState(false);
```

(e) history useQuery 추가(classificationQ 근처):
```tsx
  const classHistoryQ = useQuery<ClassificationHistoryRow[]>({
    queryKey: ["chart-classification-history", ticker, period],
    queryFn: () =>
      api<ClassificationHistoryRow[]>(
        `/classifications/history/${ticker}?start=${startForPeriod(period)}&end=${todayStr()}`,
      ),
    enabled: !!ticker,
  });
```
(`startForPeriod`/`todayStr` 는 기존 daily/weekly fetch 에서 쓰는 동일 헬퍼.)

(f) 세그먼트 계산(useMemo, bars 정의 뒤):
```tsx
  const bandSegments = useMemo<BandSegment[]>(() => {
    const points: ClassificationPoint[] = (classHistoryQ.data ?? []).map((h) => ({
      date: h.date,
      classification: h.classification,
    }));
    return buildBandSegments(
      bars.map((b) => ({ date: b.date, minervini_pass: b.minervini_pass ?? null })),
      points,
    );
  }, [bars, classHistoryQ.data]);
```

(g) `<PriceChart ... />` 호출에 props 추가:
```tsx
        showClassificationBands={showClassificationBands}
        bandSegments={bandSegments}
```

(h) 토글 UI: 기존 `<Toggle .../>` 들이 모인 "차트 옵션" 영역에 추가(기존 Toggle 컴포넌트 시그니처 `checked/onChange/color/label` 사용):
```tsx
            <Toggle
              checked={showClassificationBands}
              onChange={setShowClassificationBands}
              color="#16a34a"
              label="분류 밴드"
            />
```

- [ ] **Step 3: 타입체크 + 빌드 + Lint**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc -b && npm run build && npm run lint`
Expected: tsc 통과, vite build 성공. 기존 ~20 lint baseline 외 새 에러 없음. (`react-hooks/set-state-in-effect` 류 기존 경고는 PriceChart 에 이미 있음 — 새로 추가한 `setChartApi`도 같은 류일 수 있으나 동작 정상; 새 *에러* 없으면 OK.)

- [ ] **Step 4: 앱 수동 검증**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npm run dev` (백엔드 API 기동 상태). 차트 페이지에서:
1. 토글 "분류 밴드" OFF → 현재와 동일(밴드 없음).
2. ON → 분류 이력 있는 종목에 entry(초록)/watch(파랑)/ignore(회색)/fail(빨강) 배경 밴드. 한 날짜 한 색(겹침 없음).
3. 마우스 호버 → OHLC 툴팁 정상.
4. 드래그로 기간 이동 → 밴드가 캔들과 정렬 유지하며 함께 이동.
5. 줌/창 리사이즈 → 밴드 재배치.
6. 분류 이력 없는 종목 → 밴드 없음, 에러 없음.
7. backfill 로 분류한 과거 종목 → 그 구간에도 밴드 표시(라이브+백필 합산 확인).

Expected: 7가지 정상. (web 단위테스트 없음 — 이 수동 확인이 기능 검증.)

- [ ] **Step 5: Commit**

```bash
git add web/src/components/charts/PriceChart.tsx web/src/pages/ChartPage.tsx web/src/lib/types.ts
git commit -m "feat(chart): 분류 밴드 오버레이 PriceChart/ChartPage 통합 + 토글"
```

---

## Self-Review (작성자 점검)

**1. Spec coverage**
- 배경 색 밴드 오버레이(B안), pointer-events:none → Task 2 ChartOverlayBands(`pointer-events`), Task 3 wrapper 자식 ✓
- timeToCoordinate + subscribeVisibleTimeRangeChange + ResizeObserver 동기화 → Task 2 recompute ✓
- 배타 4상태(entry/watch/ignore/fail), disqualified+minervini=fail 통합 → Task 2 buildBandSegments(fail 우선, disqualified→none, minervini false→fail) ✓
- 상태 규칙(minervini false 우선, 아니면 carry-forward) → Task 2 ✓
- 라이브+백필 UNION, 라이브 우선 → Task 1 엔드포인트(source_rank) ✓
- minervini_pass 기존 데이터 재사용 → Task 2 타입 + Task 3 dailyToBar 매핑 ✓
- 토글 1개 기본 OFF → Task 3 showClassificationBands=false ✓
- 기존 차트 무수정(시리즈/툴팁/드래그) → Task 3 는 state 노출 + 자식 추가만 ✓
- weekly 는 분류 밴드만(fail 미표시) → Task 3 weeklyToBar minervini_pass=null ✓
- 테스트(엔드포인트 pytest; 프론트 tsc+lint+수동) → Task 1 / Task 2-3 ✓

**2. Placeholder scan:** 없음 — 모든 코드 스텝에 완전한 코드.

**3. Type consistency:** `BandSegment`(startDate/endDate/state), `BandState`, `buildBandSegments(BandBar[], ClassificationPoint[])`, `BAND_COLORS` 가 Task 2 정의와 Task 3 사용에서 일치. `ChartOverlayBands` props(chart/containerRef/segments/visible)가 Task 2 정의와 Task 3 PriceChart 사용에서 일치. `ClassificationHistoryRow`(symbol/date/classification/source) 가 Task 1 백엔드 모델과 Task 3 프론트 타입에서 일치. `PriceChartBar.minervini_pass` optional 추가로 기존 어댑터 무영향.

**참고:** Task 2 는 신규 파일 + optional 타입 추가라 단독 green. Task 3 가 PriceChart+ChartPage 를 함께 바꿔 green. Task 간 빌드 깨짐 없음.
