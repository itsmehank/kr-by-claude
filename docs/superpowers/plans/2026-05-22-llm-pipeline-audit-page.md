# LLM 분석 검증 페이지 (`/docs/llm-pipeline/audit`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Minervini / O'Neil 전문가가 한 페이지만 보고 시스템 전체 (스케줄링 / 5 stage / Minervini 8조건 / 9 base 패턴 / 13 risk_flag / ZIP 13 / 3 prompt / 변경 이력) 를 line-by-line 검증할 수 있는 `/docs/llm-pipeline/audit` 페이지 추가.

**Architecture:** 좌 sticky 목차 + 우 메인 본문 (9 섹션). 정적 데이터 (Minervini 8조건 / base 패턴 / risk flag / cron / ZIP / change log / stage details) 와 prompt raw string 을 별도 `web/src/data/llm-pipeline-audit/` + `web/src/data/prompts/` 디렉터리로 분리. 공용 컴포넌트 (Section / TableOfContents / BookCitation / CollapsiblePrompt / StageCardDeep / ConditionTable / PatternCards / RiskFlagTable) 가 데이터를 렌더링. `LlmPipelineAuditPage` 는 데이터 + 컴포넌트 조립만.

**Tech Stack:** React 19, TypeScript, Tailwind, lucide-react, react-router-dom. 라이브러리 추가 없음.

**Spec:** `docs/superpowers/specs/2026-05-22-llm-pipeline-audit-page-design.md` (commit 521cc7c)

---

## File Structure

### 신규
```
web/src/data/
  llm-pipeline-audit/
    minervini.ts          # MINERVINI_CONDITIONS (8)
    base-patterns.ts      # BASE_PATTERNS (9) + PIVOT_RULES (9)
    risk-flags.ts         # RISK_FLAGS (13) + AUTO_RULES
    cron.ts               # CRON_SCHEDULE (3)
    zip-files.ts          # ZIP_FILES (13) + README_BODY (string)
    stages.ts             # STAGE_DETAILS (5 stage 깊은 카드)
    change-log.ts         # CHANGE_LOG (변경 이력 + 검토 사항)
  prompts/
    analyze-chart-v3.ts                 # ANALYZE_CHART_V3 raw string (309 행)
    evaluate-pivot-trigger-v1.ts        # EVALUATE_PIVOT_TRIGGER_V1 (127 행)
    calculate-entry-params-v2-0.ts      # CALCULATE_ENTRY_PARAMS_V2_0 (580 행)

web/src/pages/
  LlmPipelineAuditPage.tsx              # 페이지 조립

web/src/pages/llm-pipeline-audit/
  Section.tsx                           # <section id> wrapper
  TableOfContents.tsx                   # sticky 목차 + IntersectionObserver
  BookCitation.tsx                      # 책 인용 박스
  CollapsiblePrompt.tsx                 # <details> wrapper
  StageCardDeep.tsx                     # 5 stage 깊은 카드
  ConditionTable.tsx                    # Minervini 8조건 표
  PatternCards.tsx                      # 9 base 패턴 카드 + pivot 규칙 표
  RiskFlagTable.tsx                     # 13 risk_flag 표 + 자동 추가 규칙
```

### 수정
- `web/src/App.tsx` — `LlmPipelineAuditPage` import + NAV_ITEMS + Route

---

## Task 1: 공용 컴포넌트 (Section / BookCitation / CollapsiblePrompt)

먼저 의존성 없는 단순 컴포넌트 3개. TOC / StageCardDeep / ConditionTable / PatternCards / RiskFlagTable 은 정적 데이터가 필요하므로 Task 2-3 후 Task 5 에서.

**Files:**
- Create: `web/src/pages/llm-pipeline-audit/Section.tsx`
- Create: `web/src/pages/llm-pipeline-audit/BookCitation.tsx`
- Create: `web/src/pages/llm-pipeline-audit/CollapsiblePrompt.tsx`

- [ ] **Step 1: Create `Section.tsx`**

Create `web/src/pages/llm-pipeline-audit/Section.tsx`:

```tsx
import type { ReactNode } from "react";

interface Props {
  id: string;
  title: string;
  children: ReactNode;
}

export function Section({ id, title, children }: Props) {
  return (
    <section id={id} className="bento p-6 mb-6 scroll-mt-20">
      <h2 className="text-headline font-bold text-ink mb-4">{title}</h2>
      {children}
    </section>
  );
}
```

- [ ] **Step 2: Create `BookCitation.tsx`**

Create `web/src/pages/llm-pipeline-audit/BookCitation.tsx`:

```tsx
import { BookOpen } from "lucide-react";

interface Props {
  book: string;            // "Minervini, Trade Like a Stock Market Wizard"
  chapter?: string;        // "Ch.5"
  page?: string;           // "p.119"
  englishQuote: string;
  koreanSummary: string;
  codeRef?: string;        // "kr_pipeline/indicators/compute/minervini.py:27"
}

export function BookCitation({
  book,
  chapter,
  page,
  englishQuote,
  koreanSummary,
  codeRef,
}: Props) {
  return (
    <div className="bg-cream border border-hairline rounded-xl p-4 my-3">
      <div className="flex items-baseline gap-2 mb-2">
        <BookOpen size={14} className="text-accent shrink-0" strokeWidth={2} />
        <div className="text-data-xs">
          <span className="font-semibold text-ink">{book}</span>
          {chapter && <span className="text-muted">, {chapter}</span>}
          {page && <span className="text-muted">, {page}</span>}
        </div>
      </div>
      <blockquote className="text-data text-ink italic border-l-2 border-accent pl-3 my-2">
        "{englishQuote}"
      </blockquote>
      <div className="text-data text-muted">
        <span className="caps text-faint mr-1">KR</span>
        {koreanSummary}
      </div>
      {codeRef && (
        <div className="mt-2 pt-2 border-t border-hairline text-data-xs">
          <span className="caps text-faint">코드</span>{" "}
          <code className="num bg-tint-stone px-1.5 py-0.5 rounded">{codeRef}</code>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create `CollapsiblePrompt.tsx`**

Create `web/src/pages/llm-pipeline-audit/CollapsiblePrompt.tsx`:

```tsx
interface Props {
  summary: string;       // "1. analyze_chart_v3.md (309 행)"
  content: string;       // raw markdown text
}

export function CollapsiblePrompt({ summary, content }: Props) {
  return (
    <details className="bento p-4 mb-3">
      <summary className="cursor-pointer font-semibold text-ink text-data hover:text-accent">
        {summary}
      </summary>
      <pre className="mt-4 bg-cream border border-hairline rounded-xl p-4 overflow-auto text-data-xs max-h-[600px]">
        <code className="num">{content}</code>
      </pre>
    </details>
  );
}
```

- [ ] **Step 4: Type-check**

Run: `cd ~/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/llm-pipeline-audit/
git commit -m "feat(audit): Section / BookCitation / CollapsiblePrompt 공용 컴포넌트"
```

---

## Task 2: 정적 데이터 #1 — Minervini 8조건 + Base 패턴 9 + Risk Flag 13

**Files:**
- Create: `web/src/data/llm-pipeline-audit/minervini.ts`
- Create: `web/src/data/llm-pipeline-audit/base-patterns.ts`
- Create: `web/src/data/llm-pipeline-audit/risk-flags.ts`

- [ ] **Step 1: Create `minervini.ts`**

Create `web/src/data/llm-pipeline-audit/minervini.ts`:

```ts
// Minervini Trend Template 8조건 (spec audit §4)

export interface MinerviniCondition {
  num: number;             // 1-8
  korean: string;
  threshold: string;       // "—" / "22 거래일" / "1.25×" / "0.75×" / "70"
  codeRef: string;         // "minervini.py:27"
  englishOriginal: string;
  note?: string;           // 추가 코멘트 (예: c6 의 두 저작 차이)
}

export const MINERVINI_PASS_FORMULA = `
minervini_pass = (
    minervini_c1 IS TRUE AND minervini_c2 IS TRUE AND
    minervini_c3 IS TRUE AND minervini_c4 IS TRUE AND
    minervini_c5 IS TRUE AND minervini_c6 IS TRUE AND
    minervini_c7 IS TRUE AND (rs_rating >= 70)
)
`.trim();

export const MINERVINI_PASS_REF = "kr_pipeline/indicators/store.py:91-96 (SQL UPDATE SET)";

export const MINERVINI_CONDITIONS: MinerviniCondition[] = [
  {
    num: 1,
    korean: "close > sma_150 AND sma_150 > sma_200",
    threshold: "—",
    codeRef: "minervini.py:27",
    englishOriginal: "Price > MA150 AND MA150 > MA200",
  },
  {
    num: 2,
    korean: "sma_150 > sma_200",
    threshold: "—",
    codeRef: "minervini.py:29",
    englishOriginal: "MA150 > MA200",
  },
  {
    num: 3,
    korean: "오늘 sma_200 > 22거래일 전 sma_200",
    threshold: "22 거래일 (default)",
    codeRef: "minervini.py:31-32",
    englishOriginal: "MA200 trending up for ≥1 month (≥22 trading days)",
    note: "sma_200_lookback=22 default 인자. '연속 상승' 이 아니라 한 번 비교.",
  },
  {
    num: 4,
    korean: "sma_50 > sma_150 AND sma_150 > sma_200",
    threshold: "—",
    codeRef: "minervini.py:34",
    englishOriginal: "MA50 > MA150 > MA200",
  },
  {
    num: 5,
    korean: "close > sma_50",
    threshold: "—",
    codeRef: "minervini.py:36",
    englishOriginal: "Price > MA50",
  },
  {
    num: 6,
    korean: "close ≥ w52_low × 1.25",
    threshold: "1.25×",
    codeRef: "minervini.py:38",
    englishOriginal:
      "Price ≥ 52w-low × 1.25 (TTLC Ch.6 — 최신작) / × 1.30 (TLSMW Ch.5)",
    note: "두 저작 간 버전 차이 — TTLC Ch.6 (+25%) 와 TLSMW Ch.5 (+30%) 모두 책 근거. 우리는 최신작 채택.",
  },
  {
    num: 7,
    korean: "close ≥ w52_high × 0.75",
    threshold: "0.75×",
    codeRef: "minervini.py:40",
    englishOriginal: "Price ≥ 52w-high × 0.75 (within 25% of 52w high)",
  },
  {
    num: 8,
    korean: "rs_rating ≥ 70",
    threshold: "70",
    codeRef: "store.py:91 (SQL UPDATE SET)",
    englishOriginal: "RS Rating ≥ 70",
    note: "RS Rating 개념은 O'Neil HMMS, 임계 70은 Minervini TLSMW Ch.5 — c1-c7 과 함께 minervini_pass 의 8 번째 조건.",
  },
];

export const NAN_POLICY = `
입력 중 하나라도 NaN 이면 조건도 NaN (boolean 강제 안 함, minervini.py:42-55).
SMA 데이터 부족 종목은 minervini_pass = NULL → 게이트 통과 안 함.
`.trim();

export const WEEKLY_MINERVINI_NOTE = `
weekly_indicators 에도 동일 8조건 + minervini_pass 계산 (store.py:168-182).
LLM payload 의 minervini.json 은 일봉 기준 (minervini_detail_builder.py).
`.trim();
```

- [ ] **Step 2: Create `base-patterns.ts`**

Create `web/src/data/llm-pipeline-audit/base-patterns.ts`:

```ts
// Base 패턴 9개 (spec audit §5) — analyze_chart_v3.md §4 line 88-92, 105-111 표 그대로

export interface BasePattern {
  id: string;
  definition: string;       // 영어 원문 (prompt 표 그대로)
  source: string;
}

export const BASE_PATTERNS: BasePattern[] = [
  {
    id: "flat_base",
    definition:
      "5+ weeks sideways; ≤15% correction from high to low; prior uptrend ≥20% from previous base",
    source: "Minervini, *TLSMW* Ch.10",
  },
  {
    id: "cup_with_handle",
    definition:
      "U-shape (not V); 7–45 weeks; depth ≤33% (up to 50% if forming during/after bear market recovery, per O'Neil); handle forms in upper half of cup on lower volume; handle ≥1 week",
    source: "O'Neil, *HMMS* Ch.2",
  },
  {
    id: "vcp",
    definition:
      "Successive price contractions (each tighter, typically ~half the prior); volume contracting with each contraction; 2–6 contractions (typically 2–4)",
    source: "Minervini, *TLSMW* Ch.10",
  },
  {
    id: "double_bottom",
    definition:
      "Two lows near the same level; second undercuts first (W-shape, shakeout); 7+ weeks total; pivot at middle peak of W",
    source: "O'Neil, *HMMS* Ch.2",
  },
  {
    id: "high_tight_flag",
    definition:
      "Flagpole: stock advances 100–120%+ in 4–8 weeks. Flag: sideways consolidation of no more than 25% over 3–6 weeks. Total duration 7–14 weeks. Rare and powerful; use with high confidence. narrow_base flag does NOT apply.",
    source: "O'Neil HMM 'High Tight Flag' / Minervini Power Play",
  },
  {
    id: "3c_cheat",
    definition:
      "Early entry pivot in lower or middle third of a cup that has not yet completed ('3-C cheat area'). Same cup-with-handle structure, earlier buy point. Lower volume requirement. Note '3-C / cheat early entry' in reasoning.",
    source: "Minervini *TLSMW* Ch.10 / *TTLC* Ch.7",
  },
  {
    id: "base_on_base",
    definition:
      "First base breaks out but unable to advance normal 20–30%. Stock builds second consolidation just on top of previous base. Strong signal during latter stages of bear market — aggressive new leadership. Second base typically 5–15 weeks.",
    source: "O'Neil HMM 'Base on Top of a Base'",
  },
  {
    id: "ascending_base",
    definition:
      "Three pullbacks of 10–20%, each low point higher than the preceding one. Forms over 9–16 weeks while general market declining — leadership stock immune to market pressure.",
    source: "O'Neil HMM 'Ascending Base'",
  },
  {
    id: "none",
    definition:
      "No structure matching above. Use for climax runs, early-stage, wide-and-loose action, or ambiguous structure.",
    source: "—",
  },
];

// 패턴별 최소 기간 → narrow_base flag (prompt §4 line 94-98)
export const NARROW_BASE_THRESHOLDS = [
  { pattern: "flat_base", minWeeks: 5 },
  { pattern: "cup_with_handle", minWeeks: 7 },
  { pattern: "double_bottom", minWeeks: 7 },
  { pattern: "vcp", minWeeks: 5 },
  // high_tight_flag 은 narrow_base 적용 안 됨
];

export const DEPTH_RULES = `
정상 시장: depth > 33% → invalid, use 'none'.
Bear market 회복기 (post-bear correction ≥ 25%): depth ≤ 50% 까지 허용 (O'Neil).
어느 시장이든 depth > 50% → invalid, use 'none'.
`.trim();

// Pivot price 계산 규칙 (prompt §4.6 line 147-156)
export interface PivotRule {
  pattern: string;
  formula: string;
  basisLabel: string;
}

export const PIVOT_RULES: PivotRule[] = [
  { pattern: "flat_base", formula: "range_high + 0.1", basisLabel: "range_high" },
  { pattern: "cup_with_handle", formula: "handle_high + 0.1", basisLabel: "handle_high" },
  { pattern: "vcp", formula: "final_T_high + 0.1", basisLabel: "final_T_high" },
  { pattern: "double_bottom", formula: "mid_W_peak + 0.1 (두 low 사이 최고점)", basisLabel: "mid_W_peak" },
  { pattern: "high_tight_flag", formula: "top of flag (consolidation 최고점)", basisLabel: "top_of_flag" },
  { pattern: "3c_cheat", formula: "high of cheat area (low/mid cup pivot)", basisLabel: "cheat_pivot" },
  { pattern: "base_on_base", formula: "top of second (upper) base", basisLabel: "top_of_upper_base" },
  { pattern: "ascending_base", formula: "top of third pullback peak", basisLabel: "top_of_third_peak" },
  { pattern: "none", formula: "null", basisLabel: "null" },
];
```

- [ ] **Step 3: Create `risk-flags.ts`**

Create `web/src/data/llm-pipeline-audit/risk-flags.ts`:

```ts
// Risk Flags 13개 (spec audit §6) — analyze_chart_v3.md §6 line 176-188 표 그대로

export interface RiskFlag {
  id: string;
  definition: string;
}

export const RISK_FLAGS: RiskFlag[] = [
  {
    id: "climax_run",
    definition:
      "Price up ≥25% in 1–3 weeks; largest weekly price spread and heaviest volume of current move (Minervini Stage 3 warning)",
  },
  {
    id: "late_stage_base",
    definition: "3rd or later base in current Stage 2 advance",
  },
  {
    id: "extended_from_ma",
    definition: "Price > SMA-50 by more than 15%",
  },
  {
    id: "faulty_pivot",
    definition: "Pivot is at a prior resistance level that has failed 2+ times",
  },
  {
    id: "low_volume_breakout",
    definition:
      "Breakout volume < 1.4× the 50-day average (O'Neil: 40-50% above normal at minimum)",
  },
  {
    id: "narrow_base",
    definition: "Base duration below pattern-specific minimum (see §5)",
  },
  {
    id: "wide_and_loose",
    definition:
      "Weekly price swings > 10–15% during base; erratic, difficult to trade (O'Neil: 1.5–2.5× general market correction)",
  },
  {
    id: "thin_liquidity_us_only",
    definition:
      "US individual stock only: avg daily dollar volume (volume_ma20 × current_price) < $5M",
  },
  {
    id: "prior_uptrend_insufficient",
    definition:
      "Less than 20% run from prior base before current consolidation (flat_base requirement)",
  },
  {
    id: "volume_contraction_on_advance",
    definition: "Price advancing on declining volume — distribution warning or weak demand",
  },
  {
    id: "reverse_split_distortion",
    definition: "Reverse split within past ~12 weeks confirmed in price_data_notes",
  },
  {
    id: "unfavorable_market_context",
    definition:
      "Market direction is downtrend/correction/unconfirmed rally_attempt, OR distribution day count ≥ 5 over last 25 sessions",
  },
  {
    id: "etf_methodology_mismatch",
    definition: "Instrument is an ETF/fund (handled in Pre-Check)",
  },
];

// 자동 추가 규칙 (prompt line 45, 75-77, 201)
export interface AutoRule {
  flag: string;
  trigger: string;
}

export const AUTO_RULES: AutoRule[] = [
  {
    flag: "reverse_split_distortion",
    trigger: "corporate_actions 에 최근 12주 내 reverse split 있음 (prompt line 45)",
  },
  {
    flag: "unfavorable_market_context",
    trigger:
      "market_context.current_status == 'downtrend' | 'correction' (line 75) → 분류 강제 watch",
  },
  {
    flag: "unfavorable_market_context",
    trigger:
      "current_status == 'rally_attempt' AND follow-through day 없음 (line 76)",
  },
  {
    flag: "unfavorable_market_context",
    trigger:
      "distribution_day_count_last_25_sessions ≥ 5 (line 77) → confidence -0.15, prefer watch",
  },
  {
    flag: "volume_contraction_on_advance",
    trigger: "종목 자체 최근 25일 distribution day ≥ 4 (line 201)",
  },
];

export const KR_NOTE =
  "thin_liquidity_us_only 는 KR 종목 (KOSPI/KOSDAQ) 에 적용 안 됨 (prompt line 194).";
```

- [ ] **Step 4: Type-check**

Run: `cd ~/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 5: Commit**

```bash
git add web/src/data/llm-pipeline-audit/
git commit -m "feat(audit): 정적 데이터 #1 — Minervini 8조건 + Base 9 + Risk 13"
```

---

## Task 3: 정적 데이터 #2 — Cron + ZIP + Stages + Change Log

**Files:**
- Create: `web/src/data/llm-pipeline-audit/cron.ts`
- Create: `web/src/data/llm-pipeline-audit/zip-files.ts`
- Create: `web/src/data/llm-pipeline-audit/stages.ts`
- Create: `web/src/data/llm-pipeline-audit/change-log.ts`

- [ ] **Step 1: Create `cron.ts`**

Create `web/src/data/llm-pipeline-audit/cron.ts`:

```ts
// 실행 스케줄 (spec audit §2) — pipeline_specs.py 의 cron 정확한 인용

export interface CronEntry {
  pipeline: string;
  cron: string;
  kstTime: string;
  stages: string;
  llmCalls: string;
}

export const CRON_SCHEDULE: CronEntry[] = [
  {
    pipeline: "llm-weekend",
    cron: "20 3 * * 6",
    kstTime: "토 03:20",
    stages: "weekend (분류 batch)",
    llmCalls: "Yes",
  },
  {
    pipeline: "llm-full-daily",
    cron: "0 20 * * 1-5",
    kstTime: "평일 20:00",
    stages: "daily_delta → evaluate_pivot → entry_params → performance",
    llmCalls: "Yes (4 단계 중 3 개)",
  },
  {
    pipeline: "llm-performance",
    cron: "0 23 * * *",
    kstTime: "매일 23:00",
    stages: "performance",
    llmCalls: "No (가격 backfill)",
  },
];

export const CRON_CODE_REF = "kr_pipeline/llm_runner/pipeline_specs.py:181, 205, 223";
```

- [ ] **Step 2: Create `zip-files.ts`**

Create `web/src/data/llm-pipeline-audit/zip-files.ts`:

```ts
// LLM Payload ZIP 13 파일 (spec audit §7) — zip_builder.py

export interface ZipFile {
  num: number;
  filename: string;
  content: string;
  codeRef: string;
}

export const ZIP_FILES: ZipFile[] = [
  {
    num: 1,
    filename: "README.md",
    content: "2 단계 워크플로우 안내 (Step 1 분류 → Step 2 entry_params)",
    codeRef: "zip_builder.py:21 (README_TEMPLATE)",
  },
  {
    num: 2,
    filename: "prompt_step1_analyze.md",
    content: "analyze_chart_v3.md 사본",
    codeRef: "zip_builder.py:88",
  },
  {
    num: 3,
    filename: "prompt_step2_entry_params.md",
    content: "calculate_entry_params_v2_0.md 사본",
    codeRef: "zip_builder.py:89",
  },
  {
    num: 4,
    filename: "payload.json",
    content: "통합 핵심 데이터 (LLM 입력 핵심)",
    codeRef: "payload_builder.py",
  },
  {
    num: 5,
    filename: "market_context.json",
    content: "시장 컨텍스트 (current_status, distribution_day_count, follow-through day)",
    codeRef: "market_context",
  },
  {
    num: 6,
    filename: "corporate_actions.json",
    content: "액면분할 / reverse split / 자본감소 이력",
    codeRef: "corporate_actions",
  },
  {
    num: 7,
    filename: "minervini.json",
    content: "8 조건 detail (c1-c8 + values + margin_pct, 일봉 기준)",
    codeRef: "minervini_detail_builder.py",
  },
  {
    num: 8,
    filename: "daily.csv",
    content: "종목 60 거래일 OHLCV + 지표",
    codeRef: "csv_builder.py (days=60)",
  },
  {
    num: 9,
    filename: "weekly.csv",
    content: "종목 104 주 OHLCV + 지표",
    codeRef: "csv_builder.py (weeks=104)",
  },
  {
    num: 10,
    filename: "market_index_daily.csv",
    content: "종목 시장의 인덱스 일봉 (KOSPI=1001 또는 KOSDAQ=2001)",
    codeRef: "csv_builder.py (lookback=60)",
  },
  {
    num: 11,
    filename: "market_index_weekly.csv",
    content: "같은 인덱스 주봉",
    codeRef: "csv_builder.py (lookback=104)",
  },
  {
    num: 12,
    filename: "daily_chart.png",
    content: "일봉 차트 이미지 (range_days=365)",
    codeRef: "chart_render.render_daily_chart",
  },
  {
    num: 13,
    filename: "weekly_chart.png",
    content: "주봉 차트 이미지 (range_weeks=104)",
    codeRef: "chart_render.render_weekly_chart",
  },
];

export const README_BODY = `# LLM 분석 패키지

이 ZIP 는 종목 {ticker} 의 LLM 분석을 위한 통합 패키지입니다.

## 2 단계 워크플로우

1. **Step 1**: \`prompt_step1_analyze.md\` 와 함께 다음을 입력:
   - \`payload.json\` (텍스트로)
   - \`daily_chart.png\`, \`weekly_chart.png\` (이미지)
   - LLM 출력: classification (entry/watch/ignore) + pattern + pivot + risk_flags

2. **Step 2** (Step 1 결과가 \`entry\` 일 때만): \`prompt_step2_entry_params.md\` 와 함께:
   - \`payload.json\` + Step 1 결과를 \`prior_analysis\` 로 포함
   - \`daily_chart.png\`, \`weekly_chart.png\`
   - LLM 출력: 17 필드 매수 계획

## 파일 목록

- \`payload.json\`: 통합 페이로드 (LLM 입력 핵심)
- \`market_context.json\`: 시장 컨텍스트 (audit)
- \`corporate_actions.json\`: 기업행위 이력 (audit)
- \`minervini.json\`: 8 조건 detail (보조)
- \`daily.csv\` / \`weekly.csv\`: 종목 시계열 (사람용)
- \`market_index_daily.csv\` / \`market_index_weekly.csv\`: 종목 시장 인덱스 시계열 (audit)
- \`daily_chart.png\` / \`weekly_chart.png\`: 차트 이미지 (LLM 멀티모달 입력)
`;
```

- [ ] **Step 3: Create `stages.ts`**

Create `web/src/data/llm-pipeline-audit/stages.ts`:

```ts
// 5 stage 깊은 카드 데이터 (spec audit §3.1-3.5)

export interface StageDetail {
  id: string;
  num: number;          // 1-5
  label: string;
  schedule: string;     // KST 시각
  inputFilter: string;  // SQL or 설명
  inputFilterCodeRef: string;
  deterministicLogic: string | null;  // null = 없음
  promptFile: string;
  promptLines: number;
  promptSummary: string;
  outputTable: string;
  outputColumns: string;
  insertPolicy: string;
  sideEffects: string;
  bookCitations: Array<{
    book: string;
    chapter?: string;
    englishQuote: string;
    koreanSummary: string;
  }>;
  codeRefs: string[];
  notes?: string;       // 추가 노트 (예: 잠재 버그, retry 정책)
}

export const STAGE_DETAILS: StageDetail[] = [
  {
    id: "weekend",
    num: 1,
    label: "weekend stage",
    schedule: "토 03:20 (KST), cron `20 3 * * 6`",
    inputFilter: `target_date 동적 결정 (load.py:18-24):
- as_of 가 토요일이면 MAX(date) <= as_of 로 직전 금요일 행 사용
- as_of=None 이면 daily_indicators 의 전체 MAX(date)

종목 필터 SQL (load.py:26-39):

SELECT i.ticker, s.market
  FROM daily_indicators i
  JOIN stocks s ON s.ticker = i.ticker
 WHERE i.date = %s
   AND i.minervini_pass = TRUE
   AND s.delisted_at IS NULL
 ORDER BY i.ticker`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/load.py:get_qualifying_tickers",
    deterministicLogic: null,
    promptFile: "prompts/analyze_chart_v3.md",
    promptLines: 309,
    promptSummary:
      "Stage 2 확인 → 시장 컨텍스트 (downtrend/correction 시 watch 강제) → base 패턴 식별 → risk flags 적용 → pivot 산출. 출력: classification + pattern + pivot + risk_flags + confidence + reasoning",
    outputTable: "weekly_classification (kr_pipeline/db/schema.sql:256)",
    outputColumns:
      "symbol, classified_at, analyzed_for_date, market, classification, pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date, risk_flags (JSONB), confidence, reasoning, source='weekend', llm_call_duration_s, llm_input_tokens, llm_output_tokens, created_at",
    insertPolicy:
      "ON CONFLICT (symbol, classified_at) DO NOTHING — append-only. '현재 분류' 조회는 DISTINCT ON (symbol) ORDER BY symbol, classified_at DESC.",
    sideEffects:
      "notify_weekend_digest() — Slack digest 알림 (entry/watch/ignore 카운트). End-of-run 1회 retry (weekend.py:66-76) — daily_delta/evaluate_pivot/entry_params 와 다른 정책. 단일 종목 디버깅: weekend.py:38-39 ticker 인자.",
    bookCitations: [
      {
        book: "Minervini, *Trade Like a Stock Market Wizard*",
        chapter: "Ch.5 'Trend Template'",
        englishQuote: "A stock must meet all eight criteria of the Trend Template...",
        koreanSummary: "8조건 모두 충족 종목만 가능 (§4 참조).",
      },
    ],
    codeRefs: [
      "kr_pipeline/llm_runner/modes.py:run_weekend",
      "kr_pipeline/llm_runner/load.py:get_qualifying_tickers",
      "kr_pipeline/llm_runner/weekend.py",
    ],
  },
  {
    id: "daily_delta",
    num: 2,
    label: "daily_delta stage",
    schedule: "평일 20:00 (KST), `llm-full-daily` 1단계",
    inputFilter: `신규 후보 — 오늘 결정론 통과 + 최근 7일 분류 없음 (compute/delta.py:22-37):

SELECT i.ticker
  FROM daily_indicators i
  JOIN stocks s ON s.ticker = i.ticker
 WHERE i.date = %s
   AND i.minervini_pass = TRUE
   AND s.delisted_at IS NULL
   AND NOT EXISTS (
     SELECT 1 FROM weekly_classification wc
      WHERE wc.symbol = i.ticker
        AND wc.classified_at >= %s
   )
 ORDER BY i.ticker

상수: RECENT_WINDOW_DAYS = 7 (compute/delta.py:12)`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/compute/delta.py:find_new_tickers",
    deterministicLogic: null,
    promptFile: "prompts/analyze_chart_v3.md (weekend 와 동일)",
    promptLines: 309,
    promptSummary:
      "weekend 와 동일 prompt. 차이는 입력 필터 (신규 조건) 와 source 컬럼만.",
    outputTable: "weekly_classification",
    outputColumns: "weekend 와 동일 + source='daily_delta'",
    insertPolicy: "weekend 와 동일",
    sideEffects:
      "retry 없음 — weekend 와 다름. 실패 종목은 log only, 다음 평일 cron 에서 후보가 되면 재처리. 전문가 자문 (2026-05-22) 확인 — 데이터 일관성 관점에서 합리적 (대량 batch 아님, 자연 복구).",
    bookCitations: [
      {
        book: "Minervini, *Trade Like a Stock Market Wizard*",
        chapter: "Ch.5 'Trend Template'",
        englishQuote: "A stock must meet all eight criteria of the Trend Template...",
        koreanSummary: "weekend 와 동일 prompt 사용.",
      },
    ],
    codeRefs: [
      "kr_pipeline/llm_runner/compute/delta.py:find_new_tickers",
      "kr_pipeline/llm_runner/daily_delta.py",
    ],
  },
  {
    id: "evaluate_pivot",
    num: 3,
    label: "evaluate_pivot stage",
    schedule: "평일 20:00 (KST), `llm-full-daily` 2단계",
    inputFilter: `3 단계로 구성:

1) Active 종목 조회 (load.py:48-57):
SELECT DISTINCT ON (symbol)
       symbol, classified_at, market, classification, pattern,
       pivot_price, base_low, base_high
  FROM weekly_classification
 ORDER BY symbol, classified_at DESC

2) classification 필터 — Python 리스트 컴프리헨션 (load.py:72):
return [
    {...} for r in rows
    if r[3] in ("entry", "watch")
]

3) 오늘 시장 데이터 조인 + 6 필수 컬럼 NULL 체크 (evaluate_pivot.py:36-40):
if not all(
    a.get(k) is not None
    for k in ("close", "pivot_price", "volume", "avg_volume_50d",
              "stop_loss", "sma_50")
):
    continue

stop_loss = weekly_classification.base_low alias (load.py:109).`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/load.py:get_active_with_current",
    deterministicLogic: `결정론 게이트 (compute/trigger_gate.py:18-52):

# 임계 상수
BREAKOUT_VOLUME_MULTIPLIER = 1.0   # 1.5×→1.0× 완화 (2026-05-21)
PROMOTION_THRESHOLD_RATIO = 0.95   # 시스템 자체 설계, 책 근거 없음

def evaluate(*, close, pivot_price, volume, avg_volume_50d,
             stop_loss, sma_50, classification):
    # 1) 하향 트리거 우선
    if close < stop_loss:
        return "invalidation"
    if close < sma_50:
        return "invalidation"

    # 2) entry: pivot 돌파 + 거래량 >= 평균
    if classification == "entry":
        if close > pivot_price and volume >= avg_volume_50d * 1.0:
            return "breakout"

    # 3) watch: pivot 95% 근접 + 거래량 >= 평균 (staging)
    if classification == "watch":
        if close >= pivot_price * 0.95 and volume >= avg_volume_50d:
            return "promotion"

    return None`,
    promptFile: "prompts/evaluate_pivot_trigger_v1.md",
    promptLines: 127,
    promptSummary: `inline JSON payload (ZIP 아님). build_for_5b 응답:
- symbol, market, evaluation_date, trigger_type
- prior_analysis: classified_at, days_since_classification, classification, pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct, risk_flags, reasoning
- recent_daily_ohlcv_20d: 최근 20영업일
- current_metrics: close, volume, avg_volume_50d, volume_ratio, sma_50, sma_21 (≈ 20-day line)
- recent_evaluation_history: 최근 7일 (5b) 이력

Trigger 별 결정 규칙:
- breakout: go_now/wait/abort (1.4× / 일중 상단 / distribution / SMA-21 가드)
- invalidation: abort/wait (SMA-50 이탈 + SMA-21 보조)
- promotion: go_now 발생 안 함 (staging 신호)`,
    outputTable: "trigger_evaluation_log (kr_pipeline/db/schema.sql:293)",
    outputColumns:
      "symbol, evaluated_at, trigger_type, close, volume, pivot_price, decision, confidence, reasoning, abort_reason, prior_classification_at, llm_call_duration_s, llm_input_tokens, llm_output_tokens, created_at",
    insertPolicy:
      "분류는 변경 안 함 (prompt §1). abort decision 이라도 weekly_classification 그대로. 다음 weekend batch 에서 재분류 시 갱신.",
    sideEffects: "retry 없음",
    bookCitations: [
      {
        book: "O'Neil, *How to Make Money in Stocks*",
        chapter: "Ch.2 'Volume Percent Change'",
        englishQuote:
          "Volume should rise 40 to 50% or more above its average daily volume on the day a stock breaks out of its base.",
        koreanSummary:
          "돌파일 거래량 평균 대비 40-50% 이상. 코드는 LLM prompt 에서 정밀 판정 (1.4×), 게이트는 1.0× 로 사전 배제 최소화 (§9 변경 이력).",
      },
      {
        book: "Minervini, *Think & Trade Like a Champion*",
        chapter: "Ch.1 'WATCH THE 20-DAY LINE SOON AFTER A BASE BREAKOUT'",
        englishQuote:
          "If price closes below the 20-day moving average soon after a proper VCP breakout, the probability of success before getting stopped out is cut in about half.",
        koreanSummary:
          "돌파 직후 20일선 종가 이탈 시 성공률 약 절반으로 감소. 단 책 단서: 단독 무의미, 추가 위반 동반 시 의미.",
      },
    ],
    codeRefs: [
      "kr_pipeline/llm_runner/evaluate_pivot.py",
      "kr_pipeline/llm_runner/load.py:get_active_with_current",
      "kr_pipeline/llm_runner/compute/trigger_gate.py",
      "kr_pipeline/llm_runner/compute/payload_lite.py:build_for_5b",
    ],
  },
  {
    id: "entry_params",
    num: 4,
    label: "entry_params stage",
    schedule: "평일 20:00 (KST), `llm-full-daily` 3단계",
    inputFilter: `🚨 promotion staging 안전장치 포함 (entry_params.py:34-43):

SELECT symbol, evaluated_at, prior_classification_at
  FROM trigger_evaluation_log
 WHERE (evaluated_at AT TIME ZONE 'UTC')::date = %s
   AND decision = 'go_now'
   AND trigger_type = 'breakout'    -- ← 안전장치
 ORDER BY evaluated_at

trigger_type='breakout' 필터로 promotion + go_now 조합이 매수 시그널로 진입 차단 (이중 방어 — prompt §3.3 + 코드).`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/entry_params.py:34-43",
    deterministicLogic: null,
    promptFile: "prompts/calculate_entry_params_v2_0.md",
    promptLines: 580,
    promptSummary: `entry_mode 감지 (prompt §0.5):
- prior_analysis.reasoning 에 "pocket_pivot" 텍스트 → entry_mode = "pocket_pivot"
- 없으면 → entry_mode = "pivot_breakout"
- 정의 값 3개: pivot_breakout | pocket_pivot | early_entry

dual stop_loss reporting (prompt §2.1-2.4):
- Standard: max(absolute -7.0, logical from base_low) — 더 타이트
- Pocket pivot: max(sma50_pct, logical, absolute -5.5) — 더 타이트
- 모두 floor -10.0 으로 clamp

position_size_pct (prompt §3.1-3.3):
- Base tier (pattern + entry_mode 별 5-15%)
- Risk flag multipliers (cumulative): 대부분 × 0.7, unfavorable_market_context × 0.5
- confidence < 0.7 시 × 0.7
- 최종 clamp [3.0, 25.0]`,
    outputTable: "entry_params (kr_pipeline/db/schema.sql:321)",
    outputColumns: `17 필드:
1. entry_mode (pivot_breakout / pocket_pivot / early_entry)
2. trigger_price (pivot × 1.001, IBD practice)
3. entry_price
4. stop_loss (절대 가격)
5. stop_loss_pct_from_pivot
6. stop_loss_pct_from_current_price
7. stop_loss_basis (logical / absolute / sma50)
8. expected_target_price
9. expected_target_pct
10. risk_reward_ratio
11. position_size_pct (3-25%)
12. position_size_basis
13. breakout_volume_requirement (ge_1.3x / 1.4x / 1.5x_50day_avg / pocket_pivot_signature)
14. observed_breakout_volume_ratio
15. known_warnings (JSONB 15 화이트리스트)
16. other_warnings
17. notes (50-600자)`,
    insertPolicy: "PK: (symbol, signal_at)",
    sideEffects: "retry 없음",
    bookCitations: [
      {
        book: "O'Neil, *How to Make Money in Stocks*",
        chapter: "Ch.2-3 'Buy at the Buy Point'",
        englishQuote:
          "Make your buy as the stock is going through its exact pivot point... Do not pursue a stock more than 5% past its pivot point.",
        koreanSummary: "pivot 근처 진입, 5% 추격 한도.",
      },
      {
        book: "Minervini, *Trade Like a Stock Market Wizard*",
        chapter: "'Risk Management'",
        englishQuote: "Risk 1 to 3% of your total portfolio per trade.",
        koreanSummary: "거래당 자본의 1-3% 위험.",
      },
      {
        book: "Morales & Kacher, *Trade Like an O'Neil Disciple*",
        chapter: "Ch.5 'Pocket Pivot'",
        englishQuote:
          "A pocket pivot is an early entry signal that occurs within a base, before the standard pivot point breakout.",
        koreanSummary: "Pocket pivot entry 패턴.",
      },
    ],
    codeRefs: [
      "kr_pipeline/llm_runner/entry_params.py",
      "kr_pipeline/llm_runner/store.py:insert_entry_params",
    ],
  },
  {
    id: "performance",
    num: 5,
    label: "performance stage",
    schedule: "두 실행 경로: 평일 20:00 (full-daily 4단계) + 매일 23:00 (`llm-performance` cron)",
    inputFilter: `지난 90일 entry_params 시그널 + 부분 missing (performance.py:27-40):

SELECT ep.symbol, ep.signal_at, ep.entry_price,
       sp.price_1w, sp.price_2w, sp.price_4w, sp.price_8w,
       sp.market_return_1w_pct, sp.market_return_2w_pct,
       sp.market_return_4w_pct, sp.market_return_8w_pct
  FROM entry_params ep
  LEFT JOIN signal_performance sp
    ON sp.symbol = ep.symbol AND sp.signal_at = ep.signal_at
 WHERE ep.signal_at::date >= %s - INTERVAL '90 days'
   AND ep.signal_at::date <= %s`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/performance.py:27-40",
    deterministicLogic: `LLM 없음. 가격 backfill 만.

기간: PERIODS = [("1w", 7), ("2w", 14), ("4w", 28), ("8w", 56)]  # 달력일

가격 조회 fallback (휴장일 대비):
SELECT adj_close FROM daily_prices
 WHERE ticker = %s AND date <= %s
 ORDER BY date DESC LIMIT 1

market_code: KOSPI=1001, KOSDAQ=2001 (performance.py:59)

계산식:
- return_Nw_pct = (future_price - entry_price) / entry_price * 100
- market_return_Nw_pct = (end_index - base_index) / base_index * 100
- α (alpha) = 종목 - 시장 — UI 계산, DB 직접 저장 안 됨

Skip 조건:
- target_date > as_of (미래 데이터 없음)
- 가격 + 시장수익률 둘 다 이미 있으면 skip`,
    promptFile: "— (LLM 없음)",
    promptLines: 0,
    promptSummary: "LLM 호출 없음. 순수 가격 조회 backfill.",
    outputTable: "signal_performance (kr_pipeline/db/schema.sql:362)",
    outputColumns: "price_1w/2w/4w/8w, return_*_pct, market_return_*_pct, entry_price, updated_at",
    insertPolicy:
      "UPSERT: INSERT ... ON CONFLICT (symbol, signal_at) DO UPDATE SET ..., updated_at = NOW(). 가격이 이미 있으면 시장 수익률만 채우는 부분 갱신 가능.",
    sideEffects: "없음. LLM 호출 없음.",
    bookCitations: [],
    codeRefs: ["kr_pipeline/llm_runner/performance.py"],
    notes: "성과 추적은 시스템 자체 설계 — 책 근거 없음.",
  },
];
```

- [ ] **Step 4: Create `change-log.ts`**

Create `web/src/data/llm-pipeline-audit/change-log.ts`:

```ts
// 비일관성 / 변경 이력 (spec audit §9)

export interface ChangeEntry {
  letter: string;           // A, B, C, D, E, F
  date: string;             // 2026-05-21 etc
  commit: string;           // commit hash
  title: string;
  rationale: string;
  changes: string[];
}

export const CHANGE_LOG: ChangeEntry[] = [
  {
    letter: "A",
    date: "2026-05-21",
    commit: "59a1e82 + cca4054",
    title: "drawdown_filter 제거 (2 단계)",
    rationale:
      "(w52_high − w52_low) / w52_high 공식이 시간 순서 무시 → 정통 강세 종목 (저점 대비 100~300% 상승) false negative 80% 발생.",
    changes: [
      "1차 (59a1e82): 게이트만 제거. weekend.py / compute/delta.py 의 SQL WHERE 절에서 drawdown_filter_pass=TRUE 제거. 컬럼/계산 함수는 보존.",
      "2차 (cca4054): 컬럼/계산 완전 제거 (YAGNI). DB ALTER TABLE DROP COLUMN, compute_drawdown() 함수 삭제, API/TS 필드 제거.",
    ],
  },
  {
    letter: "B",
    date: "2026-05-21",
    commit: "fabe319",
    title: "avg_volume_20d → avg_volume_50d 전면 리네임",
    rationale:
      "전문가 자문 — Minervini TLSMW Ch.10 + O'Neil HMMS Ch.2 의 breakout 거래량 baseline 은 50일 평균. 책에 20일 거래량 평균 근거 없음. 20일은 *가격* MA (Minervini TTLC Ch.1) 로만 등장.",
    changes: [
      "DB SELECT 는 처음부터 avg_volume_50d. 변수명/dict key/함수 인자/prompt 참조만 잘못된 20d 이름이었음. 실제 값/동작 변화 없음 (단순 리네임).",
    ],
  },
  {
    letter: "C",
    date: "2026-05-21",
    commit: "5c6bf06",
    title: "trigger_gate breakout 게이트 1.5× → 1.0× 완화",
    rationale:
      "전문가 자문 — 책 표준 (1.4-1.5×) 정밀 판정 + pocket pivot 예외 (O'Neil 제자 책 Ch.5 BIDU 사례) 는 LLM 이 차트 보고 결정. 게이트가 1.5× 로 사전 배제하던 false negative 해소.",
    changes: [
      "BREAKOUT_VOLUME_MULTIPLIER = 1.5 → 1.0 (compute/trigger_gate.py:12)",
      "게이트는 '거래량 죽지 않은 정도' (avg 이상) 만 확인. LLM 이 표준/예외 판단.",
    ],
  },
  {
    letter: "D",
    date: "2026-05-21",
    commit: "5c6bf06",
    title: "promotion staging 안전장치 (이중 방어)",
    rationale:
      "promotion 트리거는 watch 분류의 'LLM 평가 시작' staging 신호일 뿐 매수 시그널 아님. 0.95× pivot 임계는 책 근거 없는 시스템 자체 설계 (O'Neil 은 pivot 도달 전 매수 경고).",
    changes: [
      "Prompt: evaluate_pivot_trigger_v1.md §3.3 신규 추가 — promotion 트리거에서 go_now 발생 금지 명시.",
      "Code: entry_params.py:34-43 SQL 에 WHERE trigger_type = 'breakout' 필터 추가. prompt 위반 시에도 promotion + go_now → entry_params 직행 차단.",
    ],
  },
  {
    letter: "E",
    date: "2026-05-22",
    commit: "a215cfa",
    title: "spec audit Part 1-7 검토 후 코드 정합성 fix",
    rationale: "spec v2 작성 과정의 line-by-line 비교에서 발견된 코드 정합성 이슈 사전 정리.",
    changes: [
      "daily_delta SQL 에 JOIN stocks WHERE s.delisted_at IS NULL 추가 (compute/delta.py). weekend 와 일관성 회복.",
      "ZIP payload 의 kospi_*.csv → market_index_*.csv 일반화 (zip_builder.py + README + 테스트). KOSDAQ 종목 분석 시 파일명 혼동 해소.",
      "LlmPipelinePage mermaid 정정. DIAGRAM_DATA_FLOW 에 weekend 노드 + trigger_type='breakout' 안전장치 반영. DIAGRAM_STATE 의 잘못된 promotion + go_now 전이 제거.",
    ],
  },
  {
    letter: "F",
    date: "2026-05-22",
    commit: "0e0976c",
    title: "전문가 자문 #2 + #3 반영 (c6 주석 + SMA-21 가드)",
    rationale:
      "spec audit 작성 후 잔존 3 항목 전문가 자문 요청 → 답변 받음 (#1 retry / #2 c6 임계 / #3 SMA-20).",
    changes: [
      "#2 c6: minervini.py:38 주석 보강 — TTLC Ch.6 +25% (최신작, 코드 일치) vs TLSMW Ch.5 +30% 두 저작 간 버전 차이 명시.",
      "#3 SMA-20 가드 (옵션 2 채택): payload_lite.py 에 current_metrics.sma_21 + prior_analysis.days_since_classification 추가. evaluate_pivot_trigger_v1.md §3.1 breakout abort + §3.2 invalidation abort 에 20일선 가드 + '단독은 wait' 단서 + squat reversal recovery 여지.",
      "#1 retry: 책 밖 (엔지니어링). 현행 합리적. 코드 변경 없음.",
    ],
  },
];

// 검토 사항 (모두 해결 표기)
export interface ReviewItem {
  title: string;
  status: "resolved" | "open";
  detail: string;
}

export const REVIEW_ITEMS: ReviewItem[] = [
  {
    title: "Minervini c6 임계 (1.25 vs 1.30)",
    status: "resolved",
    detail:
      "두 저작 차이 — TTLC Ch.6 +25% (최신작, 현재 코드 일치) vs TLSMW Ch.5 +30%. 그대로 유지 + minervini.py:38 주석 보강 (commit 0e0976c).",
  },
  {
    title: "daily_delta SQL delisted_at 필터 누락",
    status: "resolved",
    detail: "compute/delta.py 에 JOIN stocks WHERE s.delisted_at IS NULL 추가 (commit a215cfa).",
  },
  {
    title: "retry 정책 일관성",
    status: "resolved",
    detail:
      "전문가 결론 — 책 밖 (엔지니어링). weekend 대량/평일 소량 차이라 현행 정책이 데이터 일관성 관점에서 합리적. 코드 변경 없음.",
  },
  {
    title: "kospi_*.csv 파일명 혼동",
    status: "resolved",
    detail: "market_index_*.csv 로 일반화 (commit a215cfa).",
  },
  {
    title: "기존 안내 페이지 mermaid 다이어그램 정정",
    status: "resolved",
    detail:
      "DIAGRAM_DATA_FLOW + DIAGRAM_STATE 정정 (commit a215cfa). weekend 노드 추가 + 잘못된 promotion go_now 전이 제거.",
  },
  {
    title: "invalidation 에 SMA-20 가격 MA 추가",
    status: "resolved",
    detail:
      "옵션 2 채택 (게이트는 SMA-50, SMA-21 은 LLM prompt 재료). payload_lite.py + evaluate_pivot_trigger_v1.md 갱신 (commit 0e0976c). 책 직접 인용: Minervini TTLC Ch.1 'WATCH THE 20-DAY LINE'.",
  },
];

// 향후 모니터링
export const FUTURE_MONITORING = [
  "1.0× 게이트 완화 후 LLM 호출 종목 수 / 비용 추이 모니터링",
  "pocket pivot 케이스 발견 시 LLM 이 정상 판정하는지 확인",
  "분류 변경 추이 (entry → ignore 강등이 정상 흐름인지)",
];
```

- [ ] **Step 5: Type-check**

Run: `cd ~/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 6: Commit**

```bash
git add web/src/data/llm-pipeline-audit/
git commit -m "feat(audit): 정적 데이터 #2 — Cron + ZIP + Stages + Change Log"
```

---

## Task 4: Prompt raw string 3개

prompts/ 디렉터리의 3 파일을 `.ts` 로 그대로 export. 백틱 escape 처리.

**Files:**
- Create: `web/src/data/prompts/analyze-chart-v3.ts`
- Create: `web/src/data/prompts/evaluate-pivot-trigger-v1.ts`
- Create: `web/src/data/prompts/calculate-entry-params-v2-0.ts`

- [ ] **Step 1: Create `analyze-chart-v3.ts`**

`prompts/analyze_chart_v3.md` 의 309 행 내용 그대로를 TypeScript template literal 로 wrap. 백틱(\`) 과 `${` 만 escape.

```bash
# 헬퍼 스크립트로 변환 (수동 검토 필요)
cd ~/kr-by-claude/web/src/data/prompts/
```

Create `web/src/data/prompts/analyze-chart-v3.ts`:

```ts
// prompts/analyze_chart_v3.md (309 행) raw content.
// 빌드 시 수동 동기화. 원본 변경 시 이 파일도 갱신 필요.

export const ANALYZE_CHART_V3 = String.raw`{prompts/analyze_chart_v3.md 의 전체 내용을 그대로 붙여넣기 — 309 행}`;
```

**구체 작업**:
1. `cat prompts/analyze_chart_v3.md` 로 전체 내용 확보
2. 백틱 (\`) 을 `\` + 백틱 으로 escape (`String.raw` 안에서도 필요)
3. `${` 가 있으면 `${` 또는 별도 처리
4. `web/src/data/prompts/analyze-chart-v3.ts` 에 `export const ANALYZE_CHART_V3 = ...` 형태로 저장

**대안 — Vite `?raw` import 사용 시도** (단순):

`web/vite.config.ts` 에 prompts/ 디렉터리를 root 외부에서 import 가능하게 `fs.allow` 설정 추가:

```ts
// vite.config.ts
import { defineConfig } from "vite";
import path from "path";

export default defineConfig({
  // ...기존 설정...
  server: {
    fs: {
      allow: [path.resolve(__dirname, ".."), path.resolve(__dirname, "..", "prompts")],
    },
  },
});
```

그 후 `.ts` 파일에서:
```ts
// web/src/data/prompts/analyze-chart-v3.ts
import promptText from "../../../../prompts/analyze_chart_v3.md?raw";
export const ANALYZE_CHART_V3 = promptText;
```

**권고**: Vite `?raw` 가 단순. vite config 한 줄 추가로 prompts/ 디렉터리 import 가능. 수동 복사 시 백틱/dollar 처리 복잡.

이 task 의 실제 진행:

(a) `web/vite.config.ts` 확인 후 `server.fs.allow` 에 prompts 추가
(b) 3 `.ts` 파일 생성 — 각각 `?raw` import + re-export
(c) tsc 통과 확인

- [ ] **Step 2: Vite config 수정**

Read `web/vite.config.ts` 현재 내용. `server.fs.allow` 가 없으면 추가:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      allow: [
        path.resolve(__dirname, ".."),
      ],
    },
  },
});
```

`path.resolve(__dirname, "..")` 가 repo root 까지 허용 — prompts/ 디렉터리 포함.

기존 `vite.config.ts` 에 `server` 설정이 이미 있으면 `fs.allow` 만 추가.

- [ ] **Step 3: Create 3 prompt re-export files**

Create `web/src/data/prompts/analyze-chart-v3.ts`:

```ts
import promptText from "../../../../prompts/analyze_chart_v3.md?raw";
export const ANALYZE_CHART_V3 = promptText;
```

Create `web/src/data/prompts/evaluate-pivot-trigger-v1.ts`:

```ts
import promptText from "../../../../prompts/evaluate_pivot_trigger_v1.md?raw";
export const EVALUATE_PIVOT_TRIGGER_V1 = promptText;
```

Create `web/src/data/prompts/calculate-entry-params-v2-0.ts`:

```ts
import promptText from "../../../../prompts/calculate_entry_params_v2_0.md?raw";
export const CALCULATE_ENTRY_PARAMS_V2_0 = promptText;
```

- [ ] **Step 4: TS 타입 선언 추가** (`.md?raw` import 인식)

Create or modify `web/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />

declare module "*.md?raw" {
  const content: string;
  export default content;
}
```

기존에 `vite-env.d.ts` 있으면 `declare module "*.md?raw"` 만 추가.

- [ ] **Step 5: Type-check + smoke test**

Run: `cd ~/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

Run build (vite import 검증):
```bash
cd ~/kr-by-claude/web && npm run build 2>&1 | tail -20
```

Expected: build 통과. prompts/ import 가 resolve 됨.

- [ ] **Step 6: Commit**

```bash
git add web/vite.config.ts web/src/vite-env.d.ts web/src/data/prompts/
git commit -m "feat(audit): 3 prompt raw string import via Vite ?raw

vite.config.ts: server.fs.allow 에 repo root 추가 (prompts/ 접근).
vite-env.d.ts: *.md?raw module 선언.
data/prompts/: 3 prompt re-export."
```

---

## Task 5: 나머지 공용 컴포넌트 + LlmPipelineAuditPage 조립

Task 1 의 단순 컴포넌트 다음으로 정적 데이터를 사용하는 5 컴포넌트 + 페이지 조립.

**Files:**
- Create: `web/src/pages/llm-pipeline-audit/TableOfContents.tsx`
- Create: `web/src/pages/llm-pipeline-audit/StageCardDeep.tsx`
- Create: `web/src/pages/llm-pipeline-audit/ConditionTable.tsx`
- Create: `web/src/pages/llm-pipeline-audit/PatternCards.tsx`
- Create: `web/src/pages/llm-pipeline-audit/RiskFlagTable.tsx`
- Create: `web/src/pages/LlmPipelineAuditPage.tsx`

- [ ] **Step 1: Create `TableOfContents.tsx`**

Create `web/src/pages/llm-pipeline-audit/TableOfContents.tsx`:

```tsx
import { useEffect, useState } from "react";

interface TocItem {
  id: string;
  label: string;
  depth: 0 | 1;
}

const TOC: TocItem[] = [
  { id: "overview", label: "1. 시스템 개요", depth: 0 },
  { id: "schedule", label: "2. 실행 스케줄", depth: 0 },
  { id: "stages", label: "3. 단계별 상세", depth: 0 },
  { id: "stage-weekend", label: "3.1 weekend", depth: 1 },
  { id: "stage-daily-delta", label: "3.2 daily_delta", depth: 1 },
  { id: "stage-evaluate-pivot", label: "3.3 evaluate_pivot", depth: 1 },
  { id: "stage-entry-params", label: "3.4 entry_params", depth: 1 },
  { id: "stage-performance", label: "3.5 performance", depth: 1 },
  { id: "minervini-8", label: "4. Minervini 8조건", depth: 0 },
  { id: "base-patterns", label: "5. Base 패턴 9개", depth: 0 },
  { id: "risk-flags", label: "6. Risk Flags 13개", depth: 0 },
  { id: "zip-payload", label: "7. LLM Payload (ZIP 13)", depth: 0 },
  { id: "prompts", label: "8. Prompt 전체 (3개)", depth: 0 },
  { id: "change-log", label: "9. 비일관성 / 변경 이력", depth: 0 },
];

export function TableOfContents() {
  const [activeId, setActiveId] = useState<string>(TOC[0].id);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
            return;
          }
        }
      },
      { rootMargin: "-20% 0px -70% 0px" },
    );

    for (const item of TOC) {
      const el = document.getElementById(item.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <nav className="sticky top-6 max-h-[calc(100vh-3rem)] overflow-y-auto">
      <div className="caps text-faint mb-3">목차</div>
      <ul className="space-y-1 text-data">
        {TOC.map((item) => (
          <li
            key={item.id}
            className={item.depth === 1 ? "pl-3" : ""}
          >
            <a
              href={`#${item.id}`}
              className={`block py-1 hover:text-accent transition-colors ${
                activeId === item.id ? "text-accent font-semibold" : "text-muted"
              }`}
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
```

- [ ] **Step 2: Create `StageCardDeep.tsx`**

Create `web/src/pages/llm-pipeline-audit/StageCardDeep.tsx`:

```tsx
import type { StageDetail } from "../../data/llm-pipeline-audit/stages";
import { BookCitation } from "./BookCitation";

interface Props {
  stage: StageDetail;
}

export function StageCardDeep({ stage }: Props) {
  return (
    <div id={`stage-${stage.id}`} className="scroll-mt-20 mb-8">
      <h3 className="text-subhead font-bold text-ink mb-3">
        {stage.num}. {stage.label}
      </h3>

      <Field title="시기" value={stage.schedule} />

      <Field title="입력 필터" code={stage.inputFilter} />
      <div className="text-data-xs text-faint mb-3">
        코드: <code className="num bg-tint-stone px-1 rounded">{stage.inputFilterCodeRef}</code>
      </div>

      {stage.deterministicLogic && (
        <Field title="결정론 로직" code={stage.deterministicLogic} />
      )}

      <Field
        title={`LLM Prompt — ${stage.promptFile}${stage.promptLines > 0 ? ` (${stage.promptLines} 행)` : ""}`}
        value={stage.promptSummary}
      />

      <Field title="출력 — 테이블" value={stage.outputTable} />
      <Field title="출력 — 컬럼" code={stage.outputColumns} />
      <Field title="INSERT 정책" value={stage.insertPolicy} />
      <Field title="Side Effects" value={stage.sideEffects} />

      {stage.bookCitations.length > 0 && (
        <div className="mt-4">
          <h4 className="caps text-faint mb-2">책 근거</h4>
          {stage.bookCitations.map((c, i) => (
            <BookCitation
              key={i}
              book={c.book}
              chapter={c.chapter}
              englishQuote={c.englishQuote}
              koreanSummary={c.koreanSummary}
            />
          ))}
        </div>
      )}

      {stage.codeRefs.length > 0 && (
        <div className="mt-3">
          <h4 className="caps text-faint mb-1">코드 참조</h4>
          <ul className="text-data-xs space-y-0.5">
            {stage.codeRefs.map((ref) => (
              <li key={ref}>
                <code className="num bg-tint-stone px-1.5 py-0.5 rounded">{ref}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      {stage.notes && (
        <div className="mt-3 p-3 bg-cream border border-hairline rounded-xl text-data-xs text-muted">
          📝 {stage.notes}
        </div>
      )}
    </div>
  );
}

function Field({ title, value, code }: { title: string; value?: string; code?: string }) {
  return (
    <div className="mb-3">
      <h4 className="caps text-faint mb-1">{title}</h4>
      {value && <p className="text-data text-ink leading-relaxed">{value}</p>}
      {code && (
        <pre className="bg-cream border border-hairline rounded-xl p-3 text-data-xs overflow-auto">
          <code className="num">{code}</code>
        </pre>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create `ConditionTable.tsx`**

Create `web/src/pages/llm-pipeline-audit/ConditionTable.tsx`:

```tsx
import {
  MINERVINI_CONDITIONS,
  MINERVINI_PASS_FORMULA,
  MINERVINI_PASS_REF,
  NAN_POLICY,
  WEEKLY_MINERVINI_NOTE,
} from "../../data/llm-pipeline-audit/minervini";

export function ConditionTable() {
  return (
    <div>
      <div className="mb-4">
        <h4 className="caps text-faint mb-1">minervini_pass 정의</h4>
        <pre className="bg-cream border border-hairline rounded-xl p-3 text-data-xs overflow-auto">
          <code className="num">{MINERVINI_PASS_FORMULA}</code>
        </pre>
        <div className="text-data-xs text-faint mt-1">
          코드: <code className="num">{MINERVINI_PASS_REF}</code>
        </div>
      </div>

      <h4 className="caps text-faint mb-2">8 조건 표</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr className="border-b border-hairline text-faint">
              <th className="text-left py-2 pr-3">#</th>
              <th className="text-left py-2 pr-3">한국어 정의</th>
              <th className="text-left py-2 pr-3">임계</th>
              <th className="text-left py-2 pr-3">코드</th>
              <th className="text-left py-2">책 원문 (영어)</th>
            </tr>
          </thead>
          <tbody>
            {MINERVINI_CONDITIONS.map((c) => (
              <tr key={c.num} className="border-b border-hairline align-top">
                <td className="py-2 pr-3 num text-faint">{c.num}</td>
                <td className="py-2 pr-3 num text-ink">{c.korean}</td>
                <td className="py-2 pr-3 num">{c.threshold}</td>
                <td className="py-2 pr-3">
                  <code className="num text-data-xs bg-tint-stone px-1 rounded">{c.codeRef}</code>
                </td>
                <td className="py-2 text-data-xs text-muted">
                  <div>"{c.englishOriginal}"</div>
                  {c.note && <div className="mt-1 text-faint italic">{c.note}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">NaN 처리</div>
        <div className="text-muted whitespace-pre-wrap">{NAN_POLICY}</div>
      </div>

      <div className="mt-3 p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">주봉 (weekly) Minervini</div>
        <div className="text-muted whitespace-pre-wrap">{WEEKLY_MINERVINI_NOTE}</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create `PatternCards.tsx`**

Create `web/src/pages/llm-pipeline-audit/PatternCards.tsx`:

```tsx
import {
  BASE_PATTERNS,
  NARROW_BASE_THRESHOLDS,
  DEPTH_RULES,
  PIVOT_RULES,
} from "../../data/llm-pipeline-audit/base-patterns";

export function PatternCards() {
  return (
    <div>
      <h4 className="caps text-faint mb-2">5.1 패턴 정의</h4>
      <div className="overflow-x-auto mb-4">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr className="border-b border-hairline text-faint">
              <th className="text-left py-2 pr-3">Pattern</th>
              <th className="text-left py-2 pr-3">Definition</th>
              <th className="text-left py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {BASE_PATTERNS.map((p) => (
              <tr key={p.id} className="border-b border-hairline align-top">
                <td className="py-2 pr-3">
                  <code className="num font-semibold text-ink">{p.id}</code>
                </td>
                <td className="py-2 pr-3 text-data-xs text-muted">{p.definition}</td>
                <td className="py-2 text-data-xs text-faint italic">{p.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mb-4 p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">narrow_base 패턴별 최소 기간</div>
        <ul className="text-muted space-y-0.5">
          {NARROW_BASE_THRESHOLDS.map((t) => (
            <li key={t.pattern}>
              <code className="num">{t.pattern}</code>: &lt; {t.minWeeks} 주
            </li>
          ))}
          <li className="text-faint italic">high_tight_flag 는 narrow_base 적용 안 됨</li>
        </ul>
      </div>

      <div className="mb-4 p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">Depth 무효화 규칙</div>
        <div className="text-muted whitespace-pre-wrap">{DEPTH_RULES}</div>
      </div>

      <h4 className="caps text-faint mb-2">5.2 Pivot price 계산 규칙</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr className="border-b border-hairline text-faint">
              <th className="text-left py-2 pr-3">Pattern</th>
              <th className="text-left py-2 pr-3">Pivot Formula</th>
              <th className="text-left py-2">Pivot Basis Label</th>
            </tr>
          </thead>
          <tbody>
            {PIVOT_RULES.map((r) => (
              <tr key={r.pattern} className="border-b border-hairline">
                <td className="py-2 pr-3">
                  <code className="num">{r.pattern}</code>
                </td>
                <td className="py-2 pr-3 text-data text-ink num">{r.formula}</td>
                <td className="py-2 text-data-xs text-faint num">{r.basisLabel}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create `RiskFlagTable.tsx`**

Create `web/src/pages/llm-pipeline-audit/RiskFlagTable.tsx`:

```tsx
import {
  RISK_FLAGS,
  AUTO_RULES,
  KR_NOTE,
} from "../../data/llm-pipeline-audit/risk-flags";

export function RiskFlagTable() {
  return (
    <div>
      <h4 className="caps text-faint mb-2">6.1 정의</h4>
      <div className="overflow-x-auto mb-4">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr className="border-b border-hairline text-faint">
              <th className="text-left py-2 pr-3">Flag</th>
              <th className="text-left py-2">Definition</th>
            </tr>
          </thead>
          <tbody>
            {RISK_FLAGS.map((f) => (
              <tr key={f.id} className="border-b border-hairline align-top">
                <td className="py-2 pr-3">
                  <code className="num font-semibold text-ink">{f.id}</code>
                </td>
                <td className="py-2 text-data-xs text-muted">{f.definition}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4 className="caps text-faint mb-2">6.2 시장 컨텍스트 자동 추가 규칙</h4>
      <ul className="mb-4 space-y-2 text-data-xs">
        {AUTO_RULES.map((r, i) => (
          <li key={i} className="flex gap-2">
            <code className="num text-ink font-semibold shrink-0">{r.flag}</code>
            <span className="text-muted">— {r.trigger}</span>
          </li>
        ))}
      </ul>

      <div className="p-3 bg-cream border border-hairline rounded-xl text-data-xs">
        <div className="caps text-faint mb-1">6.3 KR 시장 제약</div>
        <div className="text-muted">{KR_NOTE}</div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Create `LlmPipelineAuditPage.tsx`**

Create `web/src/pages/LlmPipelineAuditPage.tsx`:

```tsx
import { MermaidDiagram } from "../components/MermaidDiagram";
import { Section } from "./llm-pipeline-audit/Section";
import { TableOfContents } from "./llm-pipeline-audit/TableOfContents";
import { StageCardDeep } from "./llm-pipeline-audit/StageCardDeep";
import { ConditionTable } from "./llm-pipeline-audit/ConditionTable";
import { PatternCards } from "./llm-pipeline-audit/PatternCards";
import { RiskFlagTable } from "./llm-pipeline-audit/RiskFlagTable";
import { CollapsiblePrompt } from "./llm-pipeline-audit/CollapsiblePrompt";
import { BookCitation } from "./llm-pipeline-audit/BookCitation";

import { CRON_SCHEDULE, CRON_CODE_REF } from "../data/llm-pipeline-audit/cron";
import { ZIP_FILES, README_BODY } from "../data/llm-pipeline-audit/zip-files";
import { STAGE_DETAILS } from "../data/llm-pipeline-audit/stages";
import {
  CHANGE_LOG,
  REVIEW_ITEMS,
  FUTURE_MONITORING,
} from "../data/llm-pipeline-audit/change-log";

import { ANALYZE_CHART_V3 } from "../data/prompts/analyze-chart-v3";
import { EVALUATE_PIVOT_TRIGGER_V1 } from "../data/prompts/evaluate-pivot-trigger-v1";
import { CALCULATE_ENTRY_PARAMS_V2_0 } from "../data/prompts/calculate-entry-params-v2-0";

const SYSTEM_FLOW_DIAGRAM = `graph LR
  WEEKEND["weekend batch<br/>(토 03:20)<br/>minervini_pass 전체 재분류"] -->|source='weekend'| WC[("weekly_classification<br/>watch / entry / ignore<br/>append-only")]
  DD["daily_delta<br/>(평일 20:00, 신규만)<br/>minervini_pass + 최근 7일 미분류"] -->|source='daily_delta'| WC
  WC -->|매일 active 종목<br/>DISTINCT ON| EV{"evaluate_pivot<br/>결정론 게이트"}
  EV -->|"breakout / promotion /<br/>invalidation"| LLM["LLM 평가<br/>(go_now/wait/abort)"]
  LLM --> TEL[("trigger_evaluation_log<br/>append-only")]
  TEL -->|"decision='go_now'<br/>AND trigger_type='breakout'<br/>(promotion staging 안전장치)"| EP["entry_params<br/>LLM 호출"]
  EP --> EPR[("entry_params<br/>17 필드 매수 계획")]
  EPR -->|매일 자동| PF["performance<br/>가격 backfill"]
  PF --> SP[("signal_performance<br/>1w/2w/4w/8w 수익률 + α")]
`;

export default function LlmPipelineAuditPage() {
  return (
    <div className="px-8 py-8 max-w-[1400px] mx-auto">
      <header className="mb-8">
        <div className="caps text-faint mb-2">Audit Documentation</div>
        <h1 className="font-display text-display-xl font-bold tracking-tight">
          LLM 분석 검증
        </h1>
        <p className="text-data text-muted mt-3 leading-relaxed">
          Minervini / O'Neil 책 전문가가 한 페이지만 보고 시스템 전체
          (스케줄링 / 5 stage / Minervini 8조건 / 9 base 패턴 / 13 risk_flag /
          ZIP 13 / 3 prompt / 변경 이력) 를 line-by-line 검증할 수 있는 페이지.
        </p>
      </header>

      <div className="flex gap-8">
        <aside className="hidden lg:block w-64 shrink-0">
          <TableOfContents />
        </aside>

        <main className="flex-1 min-w-0">
          {/* §1 시스템 개요 */}
          <Section id="overview" title="1. 시스템 개요">
            <p className="text-data text-muted mb-4">
              주말 1 단계 (전체 재분류) + 평일 4 단계 (신규 분류 → 트리거 평가 →
              매수 계획 → 성과 추적).
            </p>
            <MermaidDiagram chart={SYSTEM_FLOW_DIAGRAM} idPrefix="audit-flow" />
            <div className="mt-4 p-4 bg-cream border border-hairline rounded-xl text-data text-muted">
              <div className="caps text-faint mb-2">핵심 설계 철학</div>
              결정론 게이트는 싸고 느슨한 사전 필터 — 명백한 비후보만 제거.
              정밀 임계 (1.4~1.5× 표준, pocket pivot 예외, 일중 강도 등) 와
              예외 판단은 LLM 이 차트와 함께 수행. 게이트를 책 표준에 맞추면
              (1) LLM 이 무력화되고 (2) 책이 인정한 예외 (pocket pivot, 시장 맥락) 가
              사전 배제되는 false negative 발생.
            </div>
          </Section>

          {/* §2 실행 스케줄 */}
          <Section id="schedule" title="2. 실행 스케줄">
            <p className="text-data-xs text-muted mb-3">
              <code className="num">{CRON_CODE_REF}</code>
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-data border-collapse">
                <thead>
                  <tr className="border-b border-hairline text-faint">
                    <th className="text-left py-2 pr-3">Pipeline</th>
                    <th className="text-left py-2 pr-3">Cron</th>
                    <th className="text-left py-2 pr-3">KST 시각</th>
                    <th className="text-left py-2 pr-3">실행 단계</th>
                    <th className="text-left py-2">LLM 호출</th>
                  </tr>
                </thead>
                <tbody>
                  {CRON_SCHEDULE.map((c) => (
                    <tr key={c.pipeline} className="border-b border-hairline align-top">
                      <td className="py-2 pr-3"><code className="num">{c.pipeline}</code></td>
                      <td className="py-2 pr-3"><code className="num text-data-xs">{c.cron}</code></td>
                      <td className="py-2 pr-3 text-data-xs">{c.kstTime}</td>
                      <td className="py-2 pr-3 text-data-xs">{c.stages}</td>
                      <td className="py-2 text-data-xs">{c.llmCalls}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          {/* §3 단계별 상세 */}
          <Section id="stages" title="3. 단계별 상세">
            {STAGE_DETAILS.map((stage) => (
              <StageCardDeep key={stage.id} stage={stage} />
            ))}
          </Section>

          {/* §4 Minervini 8조건 */}
          <Section id="minervini-8" title="4. Minervini Trend Template 8조건">
            <ConditionTable />
            <div className="mt-4">
              <BookCitation
                book="Minervini, *Trade Like a Stock Market Wizard*"
                chapter="Ch.5 'Trend Template'"
                englishQuote="A stock must meet all eight criteria of the Trend Template..."
                koreanSummary="8조건 모두 충족 종목만 LLM 분석 대상."
              />
            </div>
          </Section>

          {/* §5 Base 패턴 */}
          <Section id="base-patterns" title="5. Base 패턴 9개 (analyze_chart_v3.md §4)">
            <PatternCards />
          </Section>

          {/* §6 Risk Flags */}
          <Section id="risk-flags" title="6. Risk Flags 13개 (analyze_chart_v3.md §6)">
            <RiskFlagTable />
          </Section>

          {/* §7 ZIP Payload */}
          <Section id="zip-payload" title="7. LLM Payload — ZIP 13 파일">
            <h4 className="caps text-faint mb-2">7.1 파일 목록</h4>
            <div className="overflow-x-auto mb-4">
              <table className="w-full text-data border-collapse">
                <thead>
                  <tr className="border-b border-hairline text-faint">
                    <th className="text-left py-2 pr-3">#</th>
                    <th className="text-left py-2 pr-3">파일명</th>
                    <th className="text-left py-2 pr-3">내용</th>
                    <th className="text-left py-2">코드 ref</th>
                  </tr>
                </thead>
                <tbody>
                  {ZIP_FILES.map((f) => (
                    <tr key={f.num} className="border-b border-hairline align-top">
                      <td className="py-2 pr-3 num text-faint">{f.num}</td>
                      <td className="py-2 pr-3"><code className="num text-data-xs">{f.filename}</code></td>
                      <td className="py-2 pr-3 text-data-xs text-muted">{f.content}</td>
                      <td className="py-2 text-data-xs">
                        <code className="num bg-tint-stone px-1 rounded">{f.codeRef}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h4 className="caps text-faint mb-2">7.2 종목 시장별 인덱스 선택</h4>
            <p className="text-data-xs text-muted mb-4">
              <code className="num">zip_builder.py:75</code> —{" "}
              <code className="num">index_code = INDEX_CODE_MAP.get(market, "1001")</code>:
              종목 market 에 따라 KOSPI(1001) 또는 KOSDAQ(2001) 의 인덱스 사용.
              파일명 <code className="num">market_index_*</code> 로 시장 중립적 표기.
            </p>

            <h4 className="caps text-faint mb-2">7.3 README 본문</h4>
            <pre className="bg-cream border border-hairline rounded-xl p-3 text-data-xs overflow-auto max-h-[400px]">
              <code className="num">{README_BODY}</code>
            </pre>
          </Section>

          {/* §8 Prompt 전체 */}
          <Section id="prompts" title="8. Prompt 전체 (3개)">
            <CollapsiblePrompt
              summary="1. analyze_chart_v3.md (weekend + daily_delta 공통, 309 행)"
              content={ANALYZE_CHART_V3}
            />
            <CollapsiblePrompt
              summary="2. evaluate_pivot_trigger_v1.md (evaluate_pivot, 127 행)"
              content={EVALUATE_PIVOT_TRIGGER_V1}
            />
            <CollapsiblePrompt
              summary="3. calculate_entry_params_v2_0.md (entry_params, 580 행)"
              content={CALCULATE_ENTRY_PARAMS_V2_0}
            />
          </Section>

          {/* §9 변경 이력 */}
          <Section id="change-log" title="9. 비일관성 / 변경 이력">
            <h4 className="caps text-faint mb-2">9.1 최근 변경</h4>
            <div className="space-y-4 mb-6">
              {CHANGE_LOG.map((entry) => (
                <div key={entry.letter} className="bg-cream border border-hairline rounded-xl p-4">
                  <div className="flex items-baseline gap-3 mb-2">
                    <span className="text-data-xs font-semibold text-accent">{entry.letter}.</span>
                    <span className="text-data font-semibold text-ink">{entry.title}</span>
                    <span className="text-data-xs text-faint ml-auto">
                      {entry.date} · <code className="num">{entry.commit}</code>
                    </span>
                  </div>
                  <p className="text-data-xs text-muted mb-2">{entry.rationale}</p>
                  <ul className="text-data-xs text-muted space-y-1 list-disc list-inside">
                    {entry.changes.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            <h4 className="caps text-faint mb-2">9.2 검토 사항 (모두 해결)</h4>
            <ul className="space-y-2 mb-6">
              {REVIEW_ITEMS.map((item, i) => (
                <li
                  key={i}
                  className="flex gap-3 text-data-xs"
                >
                  <span
                    className={
                      item.status === "resolved"
                        ? "text-green-700 font-semibold shrink-0"
                        : "text-yellow-700 font-semibold shrink-0"
                    }
                  >
                    {item.status === "resolved" ? "✓" : "○"}
                  </span>
                  <div>
                    <span className="font-semibold text-ink">{item.title}</span>
                    <div className="text-muted mt-0.5">{item.detail}</div>
                  </div>
                </li>
              ))}
            </ul>

            <h4 className="caps text-faint mb-2">9.3 향후 모니터링</h4>
            <ul className="space-y-1 text-data-xs text-muted list-disc list-inside">
              {FUTURE_MONITORING.map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ul>
          </Section>
        </main>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Type-check**

Run: `cd ~/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 8: Commit**

```bash
git add web/src/pages/llm-pipeline-audit/ web/src/pages/LlmPipelineAuditPage.tsx
git commit -m "feat(audit): TOC + 컴포넌트 5개 + LlmPipelineAuditPage 조립

TableOfContents (sticky + IntersectionObserver), StageCardDeep,
ConditionTable, PatternCards, RiskFlagTable + 페이지 본체."
```

---

## Task 6: NAV + Route 등록 + 수동 검증

**Files:**
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Add import + NAV item + Route**

In `web/src/App.tsx`:

1. lucide-react imports 에 `ShieldCheck` 추가:
```tsx
import {
  // ... 기존 ...
  ShieldCheck,
} from "lucide-react";
```

2. `LlmPipelineAuditPage` import (다른 page import 옆):
```tsx
import LlmPipelineAuditPage from "./pages/LlmPipelineAuditPage";
```

3. `NAV_ITEMS` 에 `LLM Pipeline Guide` 다음에 추가:
```tsx
{ to: "/docs/llm-pipeline", label: "LLM Pipeline Guide", kr: "LLM 분석 안내", Icon: BookOpen },
{ to: "/docs/llm-pipeline/audit", label: "LLM Audit", kr: "LLM 분석 검증", Icon: ShieldCheck },
```

4. Routes 에 `/docs/llm-pipeline` 다음에 추가:
```tsx
<Route path="/docs/llm-pipeline" element={<LlmPipelinePage />} />
<Route path="/docs/llm-pipeline/audit" element={<LlmPipelineAuditPage />} />
```

- [ ] **Step 2: Type-check**

Run: `cd ~/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 3: Manual smoke test**

```bash
cd ~/kr-by-claude/web && npm run dev
```

브라우저에서 `http://localhost:5173/docs/llm-pipeline/audit` 방문 후 다음 확인:

- 사이드바에 "LLM 분석 검증" 항목이 보이고 클릭 시 페이지 이동
- 좌측 sticky 목차 (14 항목) 표시
- 목차 클릭 시 해당 섹션으로 부드럽게 스크롤
- 스크롤 시 현재 위치 항목 강조 (IntersectionObserver)
- §1 시스템 개요 의 mermaid 다이어그램 정상 렌더링 (weekend + daily_delta + trigger_type='breakout' 안전장치 노드 포함)
- §2 cron 표 (3 행) 정상
- §3 stage 카드 5개 표시 — 각 stage 의 입력 SQL / 결정론 로직 (해당 시) / prompt 요약 / 출력 컬럼 / 책 인용 / 코드 ref 모두 표시
- §4 Minervini 8조건 표 정상 + c6 의 두 저작 차이 note 표시
- §5 base 패턴 9개 표 + pivot 계산 규칙 표
- §6 risk_flag 13개 표 + 자동 추가 규칙
- §7 ZIP 13 파일 표 + README 본문
- §8 3 prompt details 펼침 → 309/127/580 행 raw 내용 표시. 펼치고 접기 동작
- §9 변경 이력 6 entry (A-F) + 검토 사항 6 ✓ + 향후 모니터링 3 항목

- [ ] **Step 4: Commit**

```bash
git add web/src/App.tsx
git commit -m "feat(audit): NAV + Route 등록 — /docs/llm-pipeline/audit"
```

---

## Self-Review Notes

**Spec coverage check** (against spec audit v2 (commit 521cc7c)):

| 스펙 항목 | 구현 task |
|---|---|
| 페이지 자리 (/docs/llm-pipeline/audit) | Task 6 (Route) |
| sticky 목차 14 항목 | Task 5 Step 1 (TableOfContents) |
| §1 시스템 개요 + 신규 mermaid | Task 5 Step 6 (LlmPipelineAuditPage) |
| §2 cron 표 3 행 | Task 3 Step 1 (cron.ts) + Task 5 Step 6 |
| §3 stage 5 카드 — 입력 SQL / 결정론 로직 / prompt / 출력 / 책 근거 / 코드 ref | Task 3 Step 3 (stages.ts) + Task 5 Step 2 (StageCardDeep) |
| §3.4 trigger_type='breakout' 안전장치 SQL 명시 | Task 3 Step 3 (entry_params stage) |
| §4 Minervini 8조건 표 + c6 두 저작 차이 | Task 2 Step 1 (minervini.ts) + Task 5 Step 3 (ConditionTable) |
| §5 9 base 패턴 + pivot 계산 규칙 | Task 2 Step 2 (base-patterns.ts) + Task 5 Step 4 (PatternCards) |
| §6 13 risk_flag + 자동 추가 규칙 | Task 2 Step 3 (risk-flags.ts) + Task 5 Step 5 (RiskFlagTable) |
| §7 ZIP 13 + README 본문 | Task 3 Step 2 (zip-files.ts) + Task 5 Step 6 |
| §8 3 prompt 전체 (접기) | Task 4 (prompt raw imports) + Task 1 Step 3 (CollapsiblePrompt) + Task 5 Step 6 |
| §9 변경 이력 (A-F) + 검토 사항 6 + 향후 모니터링 3 | Task 3 Step 4 (change-log.ts) + Task 5 Step 6 |
| 책 인용 박스 (📖 + 영어 + 한국어 + 코드) | Task 1 Step 2 (BookCitation) + Task 5 Step 2 (StageCardDeep) + 페이지 본체 |

빠진 항목 없음.

**Type / 네이밍 일관성**:

- `MinerviniCondition` / `BasePattern` / `RiskFlag` / `CronEntry` / `ZipFile` / `StageDetail` / `ChangeEntry` / `ReviewItem` 모두 Task 2-3 에서 정의 → Task 5 에서 import.
- `ANALYZE_CHART_V3` / `EVALUATE_PIVOT_TRIGGER_V1` / `CALCULATE_ENTRY_PARAMS_V2_0` 모두 Task 4 에서 export → Task 5 Step 6 에서 import.
- `Section`, `BookCitation`, `CollapsiblePrompt` 컴포넌트 Task 1 → Task 5 Step 6 에서 import.
- `TocItem.id` ↔ Section `id` 가 일치 (overview, schedule, stages, minervini-8, base-patterns, risk-flags, zip-payload, prompts, change-log, stage-weekend ~ stage-performance).

**Risks**:

- prompt raw import (Task 4) 가 Vite `?raw` 로 동작 안 할 경우 → 대안: 수동 복사로 .ts 파일에 백틱 string 저장. 시간 비용 크지만 가능.
- TableOfContents 의 IntersectionObserver 가 다른 페이지에서 anchor link 깨질 가능성 — 페이지 전용이라 영향 없음.
- 길이 매우 긴 페이지 — 모바일에서 사이드바 hidden 처리 (`hidden lg:block`). 모바일은 메인만 보이지만 scroll-mt-20 으로 anchor link 동작.
