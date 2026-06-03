# 차트 페이지 종목명 검색 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 차트 페이지의 코드 전용 입력을 코드/종목명 자동완성 콤보박스로 교체해, 이름으로도 종목 차트를 찾을 수 있게 한다.

**Architecture:** 신규 `StockSearch` 컴포넌트(전 종목 1회 fetch + 클라이언트 필터, PromptPage 의 `StockPicker` 패턴 재사용)를 만들고, ChartPage 의 기존 검색 폼을 그것으로 교체한다. 백엔드/라우트 변경 없음 — URL 은 계속 `/chart/{ticker}`.

**Tech Stack:** React 19 + TypeScript, @tanstack/react-query, lucide-react, Tailwind, Vite. **주의: web/ 에는 단위테스트 프레임워크가 없다**(vitest/jest 없음). 검증은 타입체크(`npx tsc -b`) + lint(`npm run lint`) + 앱 수동 실행으로 한다.

**Spec:** `docs/superpowers/specs/2026-06-03-chart-name-search-design.md`

---

## File Structure

- `web/src/components/StockSearch.tsx` — 신규. 자동완성 입력 + 후보 드롭다운. props `onSelect(ticker)`. 라우팅/navigate 는 하지 않음(부모 책임). PromptPage 의 `StockPicker`(src/pages/PromptPage.tsx:212-299)를 모델로 하되 ChartPage 용으로 단순화(selectedTicker 없음, placeholder 변경). *주: 의도적으로 StockPicker 와 유사 — PromptPage 통합은 spec 상 deferred 후속.*
- `web/src/pages/ChartPage.tsx` — 변경. 기존 "종목 코드" 폼(267-284) 을 `<StockSearch>` 로 교체, `inputTicker` state(133) 와 `handleTickerSubmit`(237-244) 제거. 차트/토글/패널 로직 불변.

작업 디렉터리: `web/` 기준 명령 실행. (예: `cd web && npx tsc -b`)

---

### Task 1: `StockSearch` 컴포넌트 생성

**Files:**
- Create: `web/src/components/StockSearch.tsx`

- [ ] **Step 1: 컴포넌트 작성**

`web/src/components/StockSearch.tsx` 신규 생성:

```tsx
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "../lib/api";
import type { Stock } from "../lib/types";

interface StockSearchProps {
  onSelect: (ticker: string) => void;
  placeholder?: string;
}

export function StockSearch({ onSelect, placeholder }: StockSearchProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  // PromptPage 의 StockPicker 와 같은 queryKey → 캐시 공유.
  const stocksQ = useQuery<Stock[]>({
    queryKey: ["stocks-all"],
    queryFn: () => api<Stock[]>("/stocks?limit=10000"),
    staleTime: 5 * 60 * 1000,
  });

  const filtered = useMemo(() => {
    if (!stocksQ.data) return [];
    const q = query.trim().toLowerCase();
    if (!q) return stocksQ.data.slice(0, 20);
    return stocksQ.data
      .filter(
        (s) =>
          s.ticker.toLowerCase().includes(q) ||
          s.name.toLowerCase().includes(q)
      )
      .slice(0, 20);
  }, [stocksQ.data, query]);

  const handleSelect = (ticker: string) => {
    setQuery("");
    setOpen(false);
    onSelect(ticker);
  };

  return (
    <div className="relative w-72">
      <div className="relative">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-faint pointer-events-none"
        />
        <input
          type="text"
          value={query}
          placeholder={placeholder ?? "코드 또는 종목명 (예: 000660, 하이닉스)"}
          className="w-full border border-hairline rounded-lg pl-10 pr-3 py-2 text-data bg-cream focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
          onFocus={() => setOpen(true)}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && filtered.length > 0) {
              e.preventDefault();
              handleSelect(filtered[0].ticker);
            }
          }}
        />
      </div>

      {open && (
        <div className="absolute z-10 mt-1.5 w-full bg-paper border border-hairline rounded-xl shadow-bento overflow-hidden max-h-64 overflow-y-auto">
          {stocksQ.isError && (
            <div className="px-4 py-3 text-data text-danger">목록 오류</div>
          )}
          {!stocksQ.isError && filtered.length === 0 && (
            <div className="px-4 py-3 text-data text-muted">검색 결과 없음</div>
          )}
          {filtered.map((s) => (
            <button
              key={s.ticker}
              type="button"
              className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-tint-blue transition-colors"
              onClick={() => handleSelect(s.ticker)}
            >
              <span className="num text-data text-accent font-semibold w-20 shrink-0">
                {s.ticker}
              </span>
              <span className="text-data text-ink truncate">{s.name}</span>
              <span className="ml-auto text-data-xs text-faint shrink-0">
                {s.market}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

설계 근거 메모(코드에 넣지 말 것):
- 후보 버튼은 `onClick` + 입력 `onBlur` 150ms 지연 — PromptPage 에서 검증된 패턴(blur 가 click 보다 먼저 발생해 닫히는 문제 회피).
- `value={query}` 로 항상 입력값을 보여줌(ChartPage 는 현재 종목을 헤더에 따로 표시하므로 selectedTicker 표시 불필요).
- Enter → 첫 후보 선택(정확 코드 입력 시 그 후보가 최상단).

- [ ] **Step 2: 타입체크로 검증**

Run: `cd web && npx tsc -b`
Expected: 에러 없이 통과 (StockSearch.tsx 가 아직 import 되지 않아도 컴파일은 됨; 미사용 export 는 에러 아님).

- [ ] **Step 3: Lint**

Run: `cd web && npm run lint`
Expected: 새 파일 관련 에러/경고 없음.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/StockSearch.tsx
git commit -m "feat(chart): StockSearch 자동완성 컴포넌트 추가 (코드/종목명)"
```

---

### Task 2: ChartPage 에 StockSearch 연결 + 기존 폼/state 제거

**Files:**
- Modify: `web/src/pages/ChartPage.tsx`

- [ ] **Step 1: import 추가**

`web/src/pages/ChartPage.tsx` 상단 import 블록(다른 컴포넌트 import 들이 모인 27-31 줄 부근)에 추가:

```tsx
import { StockSearch } from "../components/StockSearch";
```

- [ ] **Step 2: 기존 검색 폼을 StockSearch 로 교체**

`ChartPage.tsx` 의 다음 블록(현재 267-284 줄, `<form onSubmit={handleTickerSubmit} ...>` ~ `</form>`):

```tsx
          <form onSubmit={handleTickerSubmit} className="flex flex-col gap-1.5">
            <label className="caps">종목 코드</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={inputTicker}
                onChange={(e) => setInputTicker(e.target.value)}
                placeholder="예: 005930"
                className="border border-hairline rounded-lg px-3 py-2 text-data bg-cream w-44 focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              />
              <button
                type="submit"
                className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold hover:bg-accent-light transition-colors"
              >
                이동
              </button>
            </div>
          </form>
```

을 다음으로 교체:

```tsx
          <div className="flex flex-col gap-1.5">
            <label className="caps">종목 검색</label>
            <StockSearch onSelect={(t) => navigate(`/chart/${t}`)} />
          </div>
```

- [ ] **Step 3: 사용하지 않게 된 state 와 핸들러 제거**

(a) `inputTicker` state 선언 제거 (현재 133 줄):

```tsx
  const [inputTicker, setInputTicker] = useState("");
```

→ 이 줄 삭제.

(b) `handleTickerSubmit` 함수 제거 (현재 237-244 줄):

```tsx
  function handleTickerSubmit(e: React.FormEvent) {
    e.preventDefault();
    const t = inputTicker.trim();
    if (t) {
      navigate(`/chart/${t}`);
      setInputTicker("");
    }
  }
```

→ 이 함수 전체 삭제.

(주의: `useState` import 는 ChartPage 의 다른 토글 state 들이 계속 쓰므로 유지. `navigate`(useNavigate) 도 다른 곳에서 쓰이고 StockSearch onSelect 에서도 쓰므로 유지.)

- [ ] **Step 4: 타입체크로 검증 (미사용 변수 제거 확인 포함)**

Run: `cd web && npx tsc -b`
Expected: 통과. 만약 `inputTicker`/`handleTickerSubmit` 잔존 참조나 미사용 경고가 나면 해당 부분을 마저 제거. (Step 2/3 를 정확히 하면 클린.)

- [ ] **Step 5: 빌드 + Lint**

Run: `cd web && npm run build && npm run lint`
Expected: `tsc -b && vite build` 성공, lint 에러 없음.

- [ ] **Step 6: 앱 수동 검증**

Run: `cd web && npm run dev` (또는 프로젝트의 앱 실행 방식). 브라우저에서 `/chart` 접속 후:
1. 검색창에 `하이닉스` 입력 → 드롭다운에 `000660 · SK하이닉스 · KOSPI` 류 후보가 뜬다.
2. 후보 클릭 → `/chart/000660` 으로 이동하고 차트가 그려진다.
3. 검색창에 `000660` (코드) 입력 → 동일 후보가 뜨고, Enter → 해당 차트로 이동.
4. 옆의 "RS 상위 종목" 빠른선택 드롭다운이 그대로 동작한다.
5. 매칭 없는 문자열(예: `zzzz`) → "검색 결과 없음" 표시.

Expected: 위 5가지 모두 정상. (자동 테스트 프레임워크가 없으므로 이 수동 확인이 기능 검증임 — verify/run 스킬 활용 가능.)

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/ChartPage.tsx
git commit -m "feat(chart): 차트 검색을 코드/종목명 자동완성으로 교체"
```

---

## Self-Review (작성자 점검)

**1. Spec coverage**
- 자동완성 콤보박스(코드/이름) → Task 1 `StockSearch` + Task 2 연결 ✓
- 클라이언트 필터(전 종목 1회 fetch, 코드 OR 이름) → Task 1 `stocksQ` + `filtered` ✓
- 라우트 `/chart/{ticker}` 불변 → Task 2 `onSelect={(t) => navigate(\`/chart/${t}\`)}` ✓
- 미너비니 빠른선택 유지 → Task 2 는 검색 폼만 교체, quickList select(286-304) 불변 ✓
- 엣지(로딩/0건/대소문자·공백/Enter) → Task 1 컴포넌트에 모두 반영 ✓
- 백엔드 변경 없음 → 기존 `/stocks?limit=10000` 재사용, Python 변경 0 ✓
- 테스트 방식(프레임워크 유무) → 확인 결과 없음 → typecheck+lint+수동 검증으로 명시 ✓

**2. Placeholder scan:** 없음 — 모든 코드 스텝에 완전한 코드 포함. (TBD/TODO/“적절히 처리” 없음.)

**3. Type consistency:** `StockSearchProps.onSelect: (ticker: string) => void` 가 Task 1 정의와 Task 2 사용(`(t) => navigate(...)`)에서 일치. `Stock`(ticker/name/market) 은 기존 `web/src/lib/types.ts` 와 일치. queryKey `["stocks-all"]` 는 PromptPage 와 동일(캐시 공유 의도).
