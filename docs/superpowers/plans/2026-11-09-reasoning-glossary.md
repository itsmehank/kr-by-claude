# Reasoning 용어 사전 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reasoning 글 안의 용어에 점선 밑줄 + 마우스 오버 쉬운 설명(현재 기준값 포함)을 붙이고, 모든 페이지에서 쓰는 따라오는 검색 창을 만든다.

**Architecture:** 정적 사전(`reasoningGlossary.ts`) → 순수 함수 매칭기(`glossaryMatch.ts`: 텍스트 → 세그먼트, hast 트리 변환) →
React 컴포넌트(`GlossaryText`, `GlossaryMarkdown`, `GlossaryTerm`, `GlossaryPanel`, 열림 상태는 `GlossaryProvider` 컨텍스트) →
기존 reasoning 렌더 위치 교체. 백엔드·프롬프트·DB 무변경.

**Tech Stack:** React 19, TypeScript, Tailwind, `@radix-ui/react-tooltip`(이미 의존성, Portal 로 overflow 잘림·모달 z-index 회피),
react-markdown 10(rehype 플러그인), vitest(순수 함수 테스트만 — jsdom 없음), Python(용어 빈도 스크립트, psycopg 읽기 전용).

**Spec:** `docs/superpowers/specs/2026-11-09-reasoning-glossary-design.md`

## Global Constraints

- 프롬프트·백엔드·DB·`thresholds.py` 변경 금지. 변경 = `web/`, `scripts/reasoning_term_frequency.py`, 문서.
- 기준값은 `thresholds.generated.ts` 에 있으면 반드시 import(리터럴 재기재 금지), 없으면 리터럴 + `source: "prompts/analyze_chart_v3.md §x"`.
- 기준값 표시 앞에 "현재 기준" 문구.
- 설명 문안: 비유 금지, 실제 숫자 예시, 초보자 눈높이.
- 범위 = reasoning 필드만(`notes` 등 제외). `PriceChart.tsx` 대상 아님.
- 버튼형 행(TriggerHistoryTable·TriggersPage·StockTimeline·ReviewPage): 펼친 상태에서만 표시, 용어 클릭 stopPropagation, 용어는 Tab 포커스 대상 아님.
- 툴팁·검색 창은 Modal(`z-50`) 위에 뜬다(`z-[60]`).
- `git add` 명시 경로만, 브랜치 `reasoning-glossary`.

## Review Focus

1. 흔한 영어 단어 오매칭(`baseline`, 문장 속 `base`/`entry`) — 단어 경계 테스트 + 단독 흔한 단어 alias 금지 무결성 테스트(Task 1·2).
2. 겹치는 alias(`confirmed_uptrend` vs `uptrend`, `Gate0` vs `Gate`) — 긴 것 우선 테스트(Task 1).
3. 정규식 특수문자 alias(`pattern=none`, `§3.5`, `c1·c2`) — 이스케이프 테스트(Task 1).
4. overflow-auto 박스(Classifications Reasoning `max-h-96 overflow-auto`) 안 툴팁 잘림 — Radix Portal 사용, 브라우저 확인(Task 3·5).
5. 버튼형 행에서 용어 클릭 시 행 접힘 — stopPropagation, 브라우저 확인(Task 4·5).

---

### Task 1: 매칭기 (순수 함수)

**Files:**
- Create: `web/src/lib/glossaryTypes.ts`, `web/src/lib/glossaryMatch.ts`
- Test: `web/src/lib/glossaryMatch.test.ts`

**Interfaces:**
- Produces:
  - `type GlossaryCategory = '시장 상황' | '베이스·패턴' | '진입 신호' | '위험 플래그' | '추세 템플릿' | '게이트·규칙' | '분류 결과' | '참고 문헌·절 번호'`
  - `type GlossaryThreshold = { label: string; value: number | string; unit?: string; source: string }`
  - `type GlossaryEntry = { id; title; aliases: string[]; category; short; thresholds?: GlossaryThreshold[]; meaning?; example?; related?: string[] }` (spec D1)
  - `type Segment = { kind: 'text'; text: string } | { kind: 'term'; text: string; id: string }`
  - `buildMatcher(entries: GlossaryEntry[]): (text: string) => Segment[]`
  - `rehypeGlossaryWith(match: (t: string) => Segment[]): () => (tree: HastRoot) => void` — text 노드를 `span[data-glossary-id]` 요소로 쪼갬. `a` 요소 하위는 건너뜀.

- [ ] **Step 1: 실패 테스트 작성** — 테스트용 entries 4개로:
  - `confirmed_uptrend 전환` → 첫 세그먼트 `{kind:'term', id:'confirmed_uptrend', text:'confirmed_uptrend'}` (alias `uptrend` 가진 항목 있어도)
  - `baseline 대비` + alias `base` → term 없음 / `flat base 형성` + alias `flat base` → term
  - `Follow-Through Day` (대소문자 다름) → term, `text` 는 원문 대소문자 유지
  - `pattern=none, rejected_gate=gate1` → `pattern=none` 통째 term
  - `§3.5 하드룰` → term(`§3.5`), `§3.55` → 미매칭
  - `분배일 5회` 한국어 alias → term
  - 세그먼트 text 를 이어 붙이면 원문과 동일(모든 케이스)
  - 매칭 없는 문장 → `[{kind:'text', text}]`
  - rehype: `{type:'root', children:[{type:'element', tagName:'p', children:[{type:'text', value:'FTD 확인'}]}]}` → p 의 첫 자식이 `element span` + `properties.dataGlossaryId === 'ftd'`
- [ ] **Step 2: 실패 확인** — `cd web && npx vitest run src/lib/glossaryMatch.test.ts` → FAIL(모듈 없음)
- [ ] **Step 3: 구현** — alias 를 길이 내림차순 정렬·정규식 이스케이프해 대안(`|`) 하나로 결합, 플래그 `gi`. ASCII 로 시작/끝나는 alias 는 `(?<![A-Za-z0-9_])` / `(?![A-Za-z0-9_.])`(끝이 숫자인 경우 `.\d` 방지 포함) 경계. 매칭 텍스트 → id 는 소문자 alias 맵으로 조회.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS
- [ ] **Step 5: 커밋** — `git add web/src/lib/glossaryTypes.ts web/src/lib/glossaryMatch.ts web/src/lib/glossaryMatch.test.ts`

### Task 2: 용어 수집 스크립트 + 사전 본문

**Files:**
- Create: `scripts/reasoning_term_frequency.py`, `web/src/data/reasoningGlossary.ts`, `web/src/data/reasoningGlossary.test.ts`, `web/src/data/__fixtures__/reasoningSamples.ts`
- Modify: `docs/GLOSSARY.md`(머리 포인터 1줄)

**Interfaces:**
- Consumes: Task 1 타입, `buildMatcher`
- Produces: `export const GLOSSARY: GlossaryEntry[]`, `export const GLOSSARY_BY_ID: Record<string, GlossaryEntry>`, `export const matchGlossary: (text: string) => Segment[]`(= `buildMatcher(GLOSSARY)`)

- [ ] **Step 1: 스크립트** — `uv run python scripts/reasoning_term_frequency.py [--top 300]`: `DATABASE_URL` 로 `weekly_classification`·`trigger_evaluation_log` 의 reasoning 을 SELECT 만, 정규식 범주별(snake_case 플래그, `key=value`, `§n(.n)`, 영문 구(2~4단어 Title/소문자), `Gate\d|G\d`, `c\d(·c\d)*`, 책 약어 HMMS/TLSMW 등) 빈도를 stdout 표로. 결과 파일 저장·커밋 안 함.
- [ ] **Step 2: 실행** → 후보 목록 확보(scratchpad 에 메모).
- [ ] **Step 3: 실패 테스트 작성** (`reasoningGlossary.test.ts`)
  - id 유일, 서로 다른 항목 간 alias(소문자) 중복 없음, `related` 는 존재하는 id
  - 금지 단독 alias: `base`, `entry`, `watch`, `pivot`, `gate`, `stage`, `market`, `volume`, `trend` (소문자 비교) 없음
  - 모든 항목 `short` 비어있지 않음, `thresholds[].source` 비어있지 않음
  - fixture(DB 에서 복사한 실제 reasoning 3~4건) 매칭 결과 id 집합이 사용자 예시 용어 전부 포함:
    `follow_through_day, downtrend, flat_base, pocket_pivot, confirmed_uptrend, unfavorable_market_context, climax, topping, tt_marginal, distribution_day, bear_recovery_exception, prior_uptrend, leadership, extended_from_ma, wide_and_loose, gate0, tightening, setup, pattern_none, stage2, confidence, base_forming, trend_template` (id 는 이 이름으로 고정)
  - 분배일 항목 thresholds 값이 `MARKET_DIST_NORMAL_MAX_25S`·`MARKET_DIST_DEMOTION_COUNT_25S`·`MARKET_DISTRIBUTION_LOOKBACK_DAYS` 와 같음
- [ ] **Step 4: 실패 확인** — `npx vitest run src/data/reasoningGlossary.test.ts` → FAIL
- [ ] **Step 5: 사전 작성** — 후보 상위 + 위 id 전부, 60~120 항목. 기준값은 `analyze_chart_v3.md` 에서 확인, generated 상수 우선. 파일 머리 주석: 작성 규칙·수동 동기화 대상 명시. `docs/GLOSSARY.md` 머리에 포인터 1줄.
- [ ] **Step 6: 통과 확인** → PASS. 스크립트 상위 후보 중 미수록 목록을 PR 본문용으로 메모.
- [ ] **Step 7: 커밋**

### Task 3: 컴포넌트 (Provider·Term·Text·Markdown·Panel)

**Files:**
- Create: `web/src/components/glossary/GlossaryProvider.tsx`, `GlossaryTerm.tsx`, `GlossaryText.tsx`, `GlossaryMarkdown.tsx`, `GlossaryPanel.tsx`
- Modify: `web/src/App.tsx`(Provider 로 감싸고 `<GlossaryPanel/>` 1회 마운트)

**Interfaces:**
- Consumes: `GLOSSARY`, `GLOSSARY_BY_ID`, `matchGlossary`, `rehypeGlossaryWith`
- Produces:
  - `useGlossary(): { open: boolean; setOpen(b: boolean): void; focusId: string | null; openEntry(id: string): void }`
  - `<GlossaryTerm id text inButton?: boolean />` — Radix Tooltip(Portal, `z-[60]`, delay 150ms). 내용 = title·short·"현재 기준: label value unit"·meaning. 클릭 → `stopPropagation()` + `openEntry(id)`. `inButton` 이면 `span`(tabIndex 없음), 아니면 `tabIndex=0` + Enter 로 openEntry.
  - `<GlossaryText text inButton? />` — `matchGlossary` 세그먼트 렌더.
  - `<GlossaryMarkdown components? children: string />` — `ReactMarkdown` + `rehypePlugins=[rehypeGlossaryWith(matchGlossary)]` + `components.span` 이 `data-glossary-id` 있으면 `GlossaryTerm`.
  - `<GlossaryPanel/>` — 우하단 버튼 "용어"(`fixed bottom-4 right-4 z-[60]`), 열면 `fixed right-4 bottom-16 w-80 max-h-[70vh] z-[60]` 창: 검색 입력(title·aliases·short, 대소문자 무시), 비었으면 카테고리별 목록, 항목 펼침 = short·현재 기준·meaning·example·related(클릭 이동). `focusId` 변경 시 그 항목 펼치고 scrollIntoView. 열림·검색어 localStorage(`kr.glossary.open`, `kr.glossary.q`) try/catch.
- [ ] **Step 1: 구현** (jsdom 없음 → 컴포넌트 단위 테스트 대신 `npm run build` 와 Task 5 브라우저 확인)
- [ ] **Step 2: `cd web && npm run build && npm run lint`** → 오류 0
- [ ] **Step 3: 커밋**

### Task 4: reasoning 렌더 위치 교체

**Files (Modify):**
- `web/src/pages/ClassificationsPage.tsx:270-286` — `ReactMarkdown` → `GlossaryMarkdown`(기존 `components` 유지)
- `web/src/components/panels/ClassificationCard.tsx:70` → `GlossaryText`; `:162` → `GlossaryMarkdown`
- `web/src/components/panels/ClassificationHistoryTable.tsx:126` → `GlossaryText`(reasoning 있을 때만)
- `web/src/components/StockTimeline.tsx:103`, `web/src/components/panels/TriggerHistoryTable.tsx:130`, `web/src/pages/TriggersPage.tsx:242`, `web/src/pages/ReviewPage.tsx:260` — `isOpen ? <GlossaryText text inButton/> : 원문`
- `web/src/pages/llm-pipeline/SimulationModal.tsx:75` → `GlossaryText`
- [ ] **Step 1: 교체** 후 `grep -rn "reasoning}" web/src --include=*.tsx` 로 누락 없음 확인(PriceChart 제외)
- [ ] **Step 2: `npm run build && npm run lint && npm test`** → 오류 0, 테스트 전부 PASS
- [ ] **Step 3: 커밋**

### Task 5: 전체 검증

- [ ] `pgrep -f pytest` 비어있음 확인 후 `uv run pytest tests/` → 실패 0, 1 deselected, 1 skipped
- [ ] 브라우저(`localhost:5173`): `/classifications` 종목 클릭 → Reasoning 밑줄·툴팁(박스 밖으로 안 잘림)·클릭 시 검색 창 항목 펼침 / `/triggers` 행 펼침 후 용어 클릭 → 행 유지 / 검색 창 스크롤 추적·검색 / `/docs/llm-pipeline` 시뮬레이션 모달 위 툴팁
- [ ] 결과 보고 + PR 생성(사용자 확인 후)
