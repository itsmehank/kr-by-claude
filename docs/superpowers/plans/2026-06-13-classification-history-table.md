# 분류 히스토리 테이블 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 차트 페이지에 종목의 분류 변화 이력(변화점 + 사유 아코디언)을 전폭 테이블로 노출한다.

**Architecture:** 기존 `/api/classifications/history/{ticker}` 응답에 pattern/confidence/reasoning 3필드를 추가(additive — 소비자 3곳 전수조사로 하위호환 검증 완료)하고, 프론트 순수 함수 `groupHistorySegments` 가 주간 행을 변화점 구간으로 묶어 `ClassificationHistoryTable` 아코디언 컴포넌트가 렌더링한다. ChartPage 의 기존 밴드용 쿼리를 재사용해 추가 fetch 없음.

**Tech Stack:** FastAPI + psycopg(백엔드), React + TypeScript + vitest(프론트). 스펙: `docs/superpowers/specs/2026-06-12-classification-history-design.md`

**파일 구조:**
- Modify: `api/schemas/classification.py` (Row 3필드), `api/routers/classifications.py:110-150` (SELECT 확장)
- Modify: `web/src/lib/types.ts` (Row 확장 + `Classification` 4종 타입 신설), `web/src/data/llm-pipeline/glossary.ts` (disqualified 항목)
- Create: `web/src/lib/historySegments.ts` + `historySegments.test.ts` (그룹핑 순수 함수)
- Create: `web/src/components/panels/ClassificationHistoryTable.tsx`
- Modify: `web/src/pages/ChartPage.tsx` (~line 605 카드 그리드에 전폭 섹션 추가)
- Test: `tests/test_api_classifications.py` (백엔드)

---

### Task 1: 백엔드 — history API 에 pattern/confidence/reasoning 추가

**Files:**
- Modify: `api/schemas/classification.py:29-33`
- Modify: `api/routers/classifications.py:110-150`
- Test: `tests/test_api_classifications.py` (파일 끝에 추가)

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_api_classifications.py` 끝에 추가:

```python
def test_classification_history_includes_detail_fields(client, db):
    """history 응답에 pattern/confidence/reasoning 포함 — 분류 히스토리 테이블용.
    disqualified 행(시스템 강등)은 셋 다 NULL 전달."""
    from datetime import datetime, timezone, date
    from api.deps import get_conn

    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('HSTD1','H','KOSPI') ON CONFLICT DO NOTHING")
            cur.execute("DELETE FROM weekly_classification WHERE symbol='HSTD1'")
            cur.execute("DELETE FROM classification_backfill WHERE symbol='HSTD1'")
            cur.execute(
                """INSERT INTO weekly_classification
                     (symbol, classified_at, analyzed_for_date, market, classification,
                      pattern, confidence, reasoning, source)
                   VALUES ('HSTD1', %s, %s, 'KOSPI', 'watch',
                           'cup_with_handle', 0.72, '핸들 형성 중 — 관찰 유지', 'weekend')""",
                (datetime(2025, 2, 2, tzinfo=timezone.utc), date(2025, 2, 1)),
            )
            cur.execute(
                """INSERT INTO weekly_classification
                     (symbol, classified_at, analyzed_for_date, market, classification, source)
                   VALUES ('HSTD1', %s, %s, 'KOSPI', 'disqualified', 'disqualified')""",
                (datetime(2025, 2, 9, tzinfo=timezone.utc), date(2025, 2, 8)),
            )
        db.commit()

        r = client.get("/api/classifications/history/HSTD1?start=2025-01-01&end=2025-03-01")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 2
        watch = rows[0]
        assert watch["pattern"] == "cup_with_handle"
        assert watch["confidence"] == 0.72
        assert watch["reasoning"] == "핸들 형성 중 — 관찰 유지"
        disq = rows[1]
        assert disq["classification"] == "disqualified"
        assert disq["pattern"] is None
        assert disq["confidence"] is None
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='HSTD1'")
            cur.execute("DELETE FROM stocks WHERE ticker='HSTD1'")
        db.commit()
        app.dependency_overrides.pop(get_conn, None)
```

(참고: disqualified 행의 reasoning 은 `insert_disqualification` 경유 시 고정 문구가 들어가지만, 이 테스트는 raw INSERT 라 NULL — 둘 다 유효한 데이터 상태다.)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_classifications.py::test_classification_history_includes_detail_fields -q`
Expected: FAIL — `KeyError: 'pattern'` (응답에 필드 없음)

- [ ] **Step 3: 스키마 확장** — `api/schemas/classification.py` 의 `ClassificationHistoryRow` 를:

```python
class ClassificationHistoryRow(BaseModel):
    symbol: str
    date: date
    classification: str
    source: str
    pattern: str | None = None       # disqualified/구형 행은 NULL
    confidence: float | None = None
    reasoning: str | None = None
```

- [ ] **Step 4: 쿼리 확장** — `api/routers/classifications.py` 의 `get_classification_history` SQL 을 (UNION 양쪽 분기에 동일 컬럼, DISTINCT ON/정렬 불변):

```python
    sql = """
        WITH combined AS (
          SELECT COALESCE(analyzed_for_date, classified_at::date) AS d,
                 classification, pattern, confidence, reasoning,
                 classified_at, 0 AS source_rank, 'live' AS src
            FROM weekly_classification
           WHERE symbol = %(ticker)s
             AND COALESCE(analyzed_for_date, classified_at::date) BETWEEN %(start)s AND %(end)s
          UNION ALL
          SELECT analyzed_for_date AS d,
                 classification, pattern, confidence, reasoning,
                 classified_at, 1 AS source_rank, 'backfill' AS src
            FROM classification_backfill
           WHERE symbol = %(ticker)s
             AND analyzed_for_date BETWEEN %(start)s AND %(end)s
        )
        SELECT DISTINCT ON (d) d, classification, src, pattern, confidence, reasoning
          FROM combined
         ORDER BY d ASC, source_rank ASC, classified_at DESC
    """
```

반환부도:

```python
    return [
        ClassificationHistoryRow(
            symbol=ticker, date=r[0], classification=r[1], source=r[2],
            pattern=r[3],
            confidence=float(r[4]) if r[4] is not None else None,
            reasoning=r[5],
        )
        for r in rows
    ]
```

- [ ] **Step 5: 통과 확인 + 기존 테스트 회귀 확인**

Run: `uv run pytest tests/test_api_classifications.py -q`
Expected: 전부 PASS (기존 history 테스트 2건 포함 — 부분 추출 비교라 영향 없음)

- [ ] **Step 6: 커밋**

```bash
git add api/schemas/classification.py api/routers/classifications.py tests/test_api_classifications.py
git commit -m "feat(api): 분류 history 에 pattern/confidence/reasoning 추가 (additive)"
```

---

### Task 2: 웹 타입 + 용어집 — Classification 4종 SSOT

**Files:**
- Modify: `web/src/lib/types.ts:336-341`
- Modify: `web/src/data/llm-pipeline/glossary.ts` ("entry / watch / ignore" 항목 근처)

- [ ] **Step 1: types.ts 확장** — 기존 `ClassificationHistoryRow` 를 다음으로 교체하고, 바로 위에 `Classification` 타입 신설:

```ts
/** 분류 테이블에 실제로 들어가는 값 전체 집합 — LLM 출력 3종 + 시스템 강등 1종.
 *  (disqualified 는 LLM 이 아니라 평일 disqualify 스윕이 기록 — prompt 에 없는 게 정상) */
export type Classification = "entry" | "watch" | "ignore" | "disqualified";

export interface ClassificationHistoryRow {
  symbol: string;
  date: string;
  classification: string;
  source: string;
  pattern: string | null;
  confidence: number | null;
  reasoning: string | null;
}
```

- [ ] **Step 2: glossary 에 disqualified 항목 추가** — `web/src/data/llm-pipeline/glossary.ts` 의 `{ term: "entry / watch / ignore", ... }` 줄 바로 아래에:

```ts
  { term: "disqualified", meaning: "시스템 강등 — LLM 분류가 아님. 분류(entry/watch/ignore)된 종목이 미너비니 결정론 필터를 탈락하면 평일 disqualify 스윕이 자동 기록하는 4번째 분류 값. 패턴·확신도 없음." },
```

- [ ] **Step 3: 타입 검증**

Run: `cd web && npx tsc -b`
Expected: 에러 0 (옵셔널 아님 주의 — Task 1 이 항상 3필드를 반환하므로 non-optional `| null` 로 선언)

- [ ] **Step 4: 커밋**

```bash
git add web/src/lib/types.ts web/src/data/llm-pipeline/glossary.ts
git commit -m "feat(web): Classification 4종 타입 신설 + history Row 확장 + disqualified 용어집"
```

---

### Task 3: groupHistorySegments 순수 함수 (vitest TDD)

**Files:**
- Create: `web/src/lib/historySegments.test.ts`
- Create: `web/src/lib/historySegments.ts`

- [ ] **Step 1: 실패하는 테스트 작성** — `web/src/lib/historySegments.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { groupHistorySegments } from "./historySegments";
import type { ClassificationHistoryRow } from "./types";

function row(date: string, classification: string, over: Partial<ClassificationHistoryRow> = {}): ClassificationHistoryRow {
  return {
    symbol: "T", date, classification, source: "backfill",
    pattern: "flat_base", confidence: 0.7, reasoning: `사유 ${date}`,
    ...over,
  };
}

describe("groupHistorySegments — 변화점 구간 그룹핑 (스펙 §4)", () => {
  it("빈 입력 → 빈 배열", () => {
    expect(groupHistorySegments([])).toEqual([]);
  });

  it("단일 구간: 연속 동일 분류는 한 구간, N주=행 수", () => {
    const segs = groupHistorySegments([row("2025-06-14", "watch"), row("2025-06-21", "watch")]);
    expect(segs).toHaveLength(1);
    expect(segs[0].classification).toBe("watch");
    expect(segs[0].startDate).toBe("2025-06-14");
    expect(segs[0].endDate).toBe("2025-06-21");
    expect(segs[0].weeks).toHaveLength(2);
  });

  it("분류 교차 시 분할 + 출력은 최신 구간 먼저", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch"), row("2025-06-21", "entry"), row("2025-06-28", "watch"),
    ]);
    expect(segs.map((s) => s.classification)).toEqual(["watch", "entry", "watch"]);
    expect(segs[0].startDate).toBe("2025-06-28"); // 최신 우선
  });

  it("미분석 갭은 구간을 끊지 않음 (스펙: 다른 분류가 끼어야 분할)", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch"), /* 3주 갭 */ row("2025-07-12", "watch"),
    ]);
    expect(segs).toHaveLength(1);
    expect(segs[0].weeks).toHaveLength(2); // 갭 주는 세지 않음
  });

  it("구간 대표값(pattern/confidence/reasoning)은 구간 첫 주 기준", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch", { pattern: "flat_base", reasoning: "전환 사유" }),
      row("2025-06-21", "watch", { pattern: "cup_with_handle", reasoning: "후속 사유" }),
    ]);
    expect(segs[0].pattern).toBe("flat_base");
    expect(segs[0].reasoning).toBe("전환 사유");
  });

  it("disqualified 도 하나의 구간 (NULL 필드 유지)", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch"),
      row("2025-06-21", "disqualified", { pattern: null, confidence: null, reasoning: null }),
    ]);
    expect(segs[0].classification).toBe("disqualified");
    expect(segs[0].pattern).toBeNull();
  });

  it("가장 오래된 구간에만 truncatedStart=true (창-잘림 보수 표기, 스펙 §4)", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch"), row("2025-06-21", "entry"),
    ]);
    const oldest = segs[segs.length - 1];
    expect(oldest.truncatedStart).toBe(true);
    expect(segs[0].truncatedStart).toBe(false);
  });

  it("입력이 정렬 안 돼 있어도 방어 정렬", () => {
    const segs = groupHistorySegments([row("2025-06-21", "watch"), row("2025-06-14", "watch")]);
    expect(segs[0].startDate).toBe("2025-06-14");
  });
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd web && npx vitest run src/lib/historySegments.test.ts`
Expected: FAIL — 모듈 없음

- [ ] **Step 3: 구현** — `web/src/lib/historySegments.ts`:

```ts
import type { ClassificationHistoryRow } from "./types";

/** 분류 히스토리의 변화점 구간 (스펙 §4).
 *  - 구간 = 연속 동일 classification (미분석 갭은 끊지 않음 — 다른 분류가 끼어야 분할)
 *  - 대표값(pattern/confidence/reasoning) = 구간 첫 주("왜 전환됐나"에 답하는 값)
 *  - weeks = 실제 분석 행만 (갭 주를 세지 않음 — 백테스트 해석 왜곡 방지)
 *  - truncatedStart: 가장 오래된 구간 — 조회 창에 잘려 시작일이 전환일이라
 *    단정 불가("기간 이전부터 ~" 보수 표기용) */
export interface HistorySegment {
  classification: string;
  startDate: string;
  endDate: string;
  pattern: string | null;
  confidence: number | null;
  reasoning: string | null;
  weeks: ClassificationHistoryRow[]; // 날짜 오름차순
  truncatedStart: boolean;
}

/** 주간 분류 행(임의 순서 허용)을 변화점 구간으로 그룹핑. 반환은 최신 구간 먼저. */
export function groupHistorySegments(rows: ClassificationHistoryRow[]): HistorySegment[] {
  if (rows.length === 0) return [];
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));

  const segments: HistorySegment[] = [];
  for (const r of sorted) {
    const cur = segments[segments.length - 1];
    if (cur && cur.classification === r.classification) {
      cur.endDate = r.date;
      cur.weeks.push(r);
    } else {
      segments.push({
        classification: r.classification,
        startDate: r.date,
        endDate: r.date,
        pattern: r.pattern,
        confidence: r.confidence,
        reasoning: r.reasoning,
        weeks: [r],
        truncatedStart: false,
      });
    }
  }
  segments[0].truncatedStart = true; // 가장 오래된 구간 — 창-잘림 보수 표기
  return segments.reverse(); // 최신 구간 먼저
}
```

- [ ] **Step 4: 통과 확인**

Run: `cd web && npx vitest run src/lib/historySegments.test.ts`
Expected: 8 passed

- [ ] **Step 5: 커밋**

```bash
git add web/src/lib/historySegments.ts web/src/lib/historySegments.test.ts
git commit -m "feat(web): groupHistorySegments — 분류 변화점 구간 그룹핑 (vitest 8건)"
```

---

### Task 4: ClassificationHistoryTable 컴포넌트

**Files:**
- Create: `web/src/components/panels/ClassificationHistoryTable.tsx`

- [ ] **Step 1: 컴포넌트 작성** (TriggerHistoryTable 스타일 미러 — Card/칩/아코디언):

```tsx
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ClassificationHistoryRow } from "../../lib/types";
import { groupHistorySegments } from "../../lib/historySegments";
import { Card } from "./Card";

// 칩 색 — disqualified 는 차트 밴드 "미통과/탈락"(빨강)과 통일 (스펙 §3).
// 미지 값은 회색 fallback (렌더 크래시 금지 — P2-10 DecisionPill 가드와 동일 패턴).
const TONES: Record<string, string> = {
  entry: "bg-success-soft text-success",
  watch: "bg-tint-blue text-accent",
  ignore: "bg-tint-stone text-muted",
  disqualified: "bg-rose-50 text-danger",
};

function Chip({ classification }: { classification: string }) {
  const tone = TONES[classification] ?? "bg-tint-stone text-muted";
  return <span className={`chip ${tone}`}>{classification}</span>;
}

interface Props {
  rows: ClassificationHistoryRow[] | undefined; // ChartPage 의 classHistoryQ.data 재사용
  loading: boolean;
}

export function ClassificationHistoryTable({ rows, loading }: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (loading) return <Card title="분류 이력">불러오는 중…</Card>;
  const segments = groupHistorySegments(rows ?? []);
  if (segments.length === 0) {
    return <Card title="분류 이력">이 기간 분류 이력이 없습니다.</Card>;
  }

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <Card title={`분류 이력 (변화점 ${segments.length}건)`}>
      <table className="w-full text-data">
        <thead className="text-faint">
          <tr>
            <th className="text-left py-1.5 pr-3">기간</th>
            <th className="text-left py-1.5 pr-3">분류</th>
            <th className="text-left py-1.5 pr-3">패턴</th>
            <th className="text-right py-1.5 pr-4">확신도</th>
            <th className="text-left py-1.5">분석</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((s) => {
            const key = `${s.classification}-${s.startDate}`;
            const open = expanded.has(key);
            return (
              <FragmentRow
                key={key}
                segment={s}
                open={open}
                onToggle={() => toggle(key)}
              />
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}

function FragmentRow({
  segment: s,
  open,
  onToggle,
}: {
  segment: ReturnType<typeof groupHistorySegments>[number];
  open: boolean;
  onToggle: () => void;
}) {
  // 창-잘림 구간: 시작일을 전환일로 단정하지 않음 (스펙 §4)
  const period = s.truncatedStart
    ? `기간 이전부터 ~ ${s.endDate}`
    : s.startDate === s.endDate
    ? s.startDate
    : `${s.startDate} ~ ${s.endDate}`;
  return (
    <>
      <tr
        onClick={onToggle}
        className="border-t border-hairline cursor-pointer hover:bg-cream/60"
      >
        <td className="py-2 pr-3 num text-data-xs whitespace-nowrap">
          <span className="inline-flex items-center gap-1 text-faint">
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </span>{" "}
          {period}
        </td>
        <td className="py-2 pr-3"><Chip classification={s.classification} /></td>
        <td className="py-2 pr-3 text-muted">{s.pattern ?? "—"}</td>
        <td className="py-2 pr-4 num text-right">
          {s.confidence != null ? s.confidence.toFixed(2) : "—"}
        </td>
        <td className="py-2 text-data-xs text-faint">{s.weeks.length}주 분석</td>
      </tr>
      {open && (
        <tr className="bg-cream/40">
          <td colSpan={5} className="px-4 py-3">
            <div className="text-data-xs leading-relaxed mb-2">
              <span className="caps text-faint mr-2">
                사유{s.truncatedStart && " (기간 내 첫 기록 기준)"}
              </span>
              {s.reasoning ?? "사유 기록 없음"}
            </div>
            <table className="w-full text-data-xs">
              <thead className="text-faint">
                <tr>
                  <th className="text-left py-1 pr-3">날짜</th>
                  <th className="text-left py-1 pr-3">분류</th>
                  <th className="text-left py-1 pr-3">패턴</th>
                  <th className="text-right py-1 pr-4">conf</th>
                  <th className="text-left py-1">출처</th>
                </tr>
              </thead>
              <tbody>
                {[...s.weeks].reverse().map((w) => (
                  <tr key={w.date} className="border-t border-hairline/60">
                    <td className="py-1 pr-3 num">{w.date}</td>
                    <td className="py-1 pr-3"><Chip classification={w.classification} /></td>
                    <td className="py-1 pr-3 text-muted">{w.pattern ?? "—"}</td>
                    <td className="py-1 pr-4 num text-right">
                      {w.confidence != null ? w.confidence.toFixed(2) : "—"}
                    </td>
                    <td className="py-1 text-faint">{w.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </>
  );
}
```

- [ ] **Step 2: 타입 검증**

Run: `cd web && npx tsc -b`
Expected: 에러 0

- [ ] **Step 3: 커밋**

```bash
git add web/src/components/panels/ClassificationHistoryTable.tsx
git commit -m "feat(web): ClassificationHistoryTable — 변화점 아코디언 (사유+구간 주간 기록)"
```

---

### Task 5: ChartPage 통합 + 전체 검증

**Files:**
- Modify: `web/src/pages/ChartPage.tsx` (import 블록 + ~line 605 카드 그리드)

- [ ] **Step 1: import 추가** — `ChartPage.tsx` 의 `TriggerHistoryTable` import 줄 아래에:

```tsx
import { ClassificationHistoryTable } from "../components/panels/ClassificationHistoryTable";
```

- [ ] **Step 2: 배치** — 카드 그리드의 `TriggerHistoryTable` 블록 **위**에 (스펙 §5: 전폭, 트리거 기록 위):

```tsx
          <div className="lg:col-span-2">
            <ClassificationHistoryTable
              rows={classHistoryQ.data}
              loading={classHistoryQ.isLoading}
            />
          </div>
          <div className="lg:col-span-2">
            <TriggerHistoryTable ticker={ticker} />
          </div>
```

(기존 `<div className="lg:col-span-2"><TriggerHistoryTable ...` 블록을 위 형태로 교체 — 새 섹션이 위, 기존이 아래.)

- [ ] **Step 3: 전체 프론트 검증**

Run: `cd web && npx tsc -b && npm test && npm run build`
Expected: tsc 에러 0 / vitest 전부 PASS (기존 10 + 신규 8 = 18) / `✓ built`

- [ ] **Step 4: 백엔드 전체 회귀**

Run: `uv run pytest tests/ -q`
Expected: baseline(±23 failed) 유지 — 신규 실패 0. 실패 수가 늘면 stash 비교로 회귀 분리.

- [ ] **Step 5: 실데이터 육안 확인** — dev 서버(8001)가 떠 있으므로:

Run: `curl -s "http://127.0.0.1:8001/api/classifications/history/000660?start=2025-06-01&end=2026-06-01" | head -c 400`
Expected: SK하이닉스 백필 행들에 `pattern`/`confidence`/`reasoning` 포함. 웹 `/chart/000660` 에서 "분류 이력" 섹션 렌더 확인 (백필 30+행 → 변화점 구간 표시).

- [ ] **Step 6: 커밋 + 푸시**

```bash
git add web/src/pages/ChartPage.tsx
git commit -m "feat(web): 차트 페이지에 분류 이력 전폭 섹션 추가 (트리거 기록 위)"
git push origin main
```
