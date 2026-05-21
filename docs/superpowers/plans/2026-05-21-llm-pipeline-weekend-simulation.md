# LLM 분석 안내 페이지 v2 (주말 + 1주일 시뮬레이션) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/docs/llm-pipeline` 페이지에 주말 분석 (weekend batch) 설명을 추가하고, 10개 가상 종목이 1주일 동안 각 stage 를 어떻게 통과하는지 격자 매트릭스 + 셀 클릭 모달로 시각화한다.

**Architecture:** 기존 `LlmPipelinePage.tsx` 의 STAGES 배열에 weekend stage 를 order=0 으로 추가하고, daily_delta / evaluate_pivot 카드 설명을 갱신한다. 새 `web/src/data/llm-pipeline-simulation.ts` 가 10 종목 × 8 일 정적 데이터 + 모달 콘텐츠를 보유한다. `SimulationMatrix` 컴포넌트가 격자 렌더링, `SimulationModal` 컴포넌트가 셀 클릭 시 상세 표시. LlmPipelinePage 가 이들을 조립한다.

**Tech Stack:** React 19, TypeScript, Tailwind, lucide-react (icons). 라이브러리 추가 없음.

**Spec:** `docs/superpowers/specs/2026-05-21-llm-pipeline-weekend-simulation-design.md` (commit 0bbdaeb)

---

## File Structure

### 신규
- `web/src/data/llm-pipeline-simulation.ts` — 시뮬레이션 정적 데이터 + 타입 정의
- `web/src/pages/llm-pipeline/SimulationMatrix.tsx` — 격자 컴포넌트
- `web/src/pages/llm-pipeline/SimulationModal.tsx` — dialog

### 수정
- `web/src/pages/LlmPipelinePage.tsx`
  - STAGES 배열에 weekend stage 추가 (order=0)
  - daily_delta / evaluate_pivot stage 텍스트 갱신
  - GLOSSARY 추가 (weekend 관련)
  - FAQ 추가
  - return JSX 에 시뮬레이션 섹션 삽입

---

## Task 1: STAGES 에 weekend 추가 + 기존 카드 텍스트 갱신

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx:22-96` (STAGES 배열)

- [ ] **Step 1: STAGES 배열에 weekend stage 추가 (order=0, 맨 앞)**

In `web/src/pages/LlmPipelinePage.tsx`, locate `const STAGES: PipelineStage[] = [` (line 22). Insert the following object as the first element (before the existing `daily_delta` entry):

```ts
  {
    id: "weekend",
    order: 0,
    label: "주말 batch — 전체 재분류",
    summary:
      "결정론 통과 모든 종목을 토 새벽 LLM 으로 재분류 (전체 갱신). daily_delta 와 같은 prompt, 차이는 입력 필터.",
    targets:
      "토요일 03:20 cron. daily_indicators 의 직전 금요일 행 기준 minervini_pass=TRUE AND drawdown_filter_pass=TRUE AND stocks.delisted_at IS NULL 전체.",
    inputs: ["daily_indicators", "weekly_indicators", "market_context_daily", "corporate_actions", "stocks"],
    outputs: ["weekly_classification (source='weekend')"],
    deterministic: "결정론 필터 — minervini_pass + drawdown_filter_pass. 추가 게이트 없음.",
    llm:
      "analyze_chart_v3.md prompt (daily_delta 와 동일). ZIP 13개 파일 (payload.json + 일/주봉 OHLCV + 차트 PNG + 시장 컨텍스트 + corporate actions + minervini detail 등). 9개 base 패턴 + 13 risk flag taxonomy.",
    decisions: ["entry", "watch", "ignore"],
    actions:
      "weekly_classification 에 INSERT (source='weekend'). ON CONFLICT (symbol, classified_at) DO NOTHING. 이전 분류가 있어도 새 row 추가 — '현재 분류'는 DISTINCT ON (symbol) ORDER BY classified_at DESC. Slack digest 알림 (entry/watch/ignore 카운트).",
    sources: [
      "Minervini Trend Template (8 conditions)",
      "Minervini drawdown filter (≤50% from 52w high)",
      "O'Neil HMM base patterns",
    ],
    codeRef: "kr_pipeline/llm_runner/weekend.py + modes.py:run_weekend",
  },
```

- [ ] **Step 2: daily_delta stage 의 summary / targets / llm 갱신**

In the same STAGES array, locate the existing `daily_delta` entry (currently at the top, soon to be at index 1). Replace it with:

```ts
  {
    id: "daily_delta",
    order: 1,
    label: "신규 후보 분류",
    summary:
      "오늘 새로 결정론 통과한 신규 종목만 LLM 분류 — weekend 와 같은 prompt, 신규 종목만 다룸.",
    targets:
      "daily_indicators 의 오늘 행 중 minervini_pass=TRUE AND drawdown_filter_pass=TRUE + 최근 7일 내 분류 이력 없음 (= 신규 후보). weekend 와의 차이: weekend 는 결정론 통과 전체를 매주 재분석. daily_delta 는 그 사이 평일에 새로 결정론 통과한 종목만 빠르게 분류.",
    inputs: ["daily_indicators", "daily_prices", "weekly_indicators", "market_context_daily"],
    outputs: ["weekly_classification (source='daily_delta')"],
    deterministic: "결정론 필터 — minervini_pass + drawdown_filter + 신규성 (7일).",
    llm:
      "analyze_chart_v3.md prompt (weekend 와 동일) + zip 13개 파일 (payload.json + market_context + corporate_actions + minervini detail + daily/weekly chart 이미지 등). 9개 base 패턴 + 13 risk flag taxonomy 적용. 차이는 source 컬럼 ('daily_delta' vs 'weekend') 과 입력 필터 (신규성 추가).",
    decisions: ["watch", "entry", "ignore"],
    actions:
      "weekly_classification 에 INSERT (source='daily_delta'). watch/entry 는 evaluate_pivot 의 다음 평가 대상, ignore 는 7일 후 재진입 가능.",
    sources: ["Minervini Trend Template", "O'Neil HMM 'How to Read Charts Like a Pro'"],
    codeRef: "kr_pipeline/llm_runner/daily_delta.py",
  },
```

- [ ] **Step 3: evaluate_pivot stage 의 actions 끝에 분류 미변경 명시 추가**

Locate the existing `evaluate_pivot` entry. Replace its `actions` value with:

```ts
    actions:
      "trigger_evaluation_log 에 INSERT. 분류 자체는 변경 안 함 (prompt 명시) — abort decision 이라도 weekly_classification 의 row 는 그대로 유지. 다음 토요일 weekend batch 에서 LLM 이 재분석 후 ignore 로 분류해야 비로소 강등됨. decision='go_now' 인 종목은 entry_params 가 자동 수집.",
```

- [ ] **Step 4: Type-check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "feat(docs): LlmPipelinePage STAGES 에 weekend 추가 + daily_delta/evaluate_pivot 갱신

- weekend stage (order=0) 신규: 토 03:20 batch, 결정론 통과 모든 종목 재분류.
- daily_delta: weekend 와의 관계 (동일 prompt, 신규 종목만) 명시.
- evaluate_pivot: abort 가 분류 변경 안 함 명시."
```

---

## Task 2: 용어 사전 + FAQ 추가

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx:155-206` (GLOSSARY + FAQ 배열)

- [ ] **Step 1: GLOSSARY 에 weekend 관련 5 항목 추가**

In `web/src/pages/LlmPipelinePage.tsx`, locate `const GLOSSARY` (line 155). Add the following entries at the top of the array (before the existing `classification` entry) so they appear first:

```ts
  {
    term: "weekend batch",
    meaning: "토 03:20 cron 으로 실행되는 LLM 분석 — 결정론 통과 모든 종목 재분류. weekly_classification 에 source='weekend' 로 INSERT.",
  },
  {
    term: "결정론 필터",
    meaning: "minervini_pass + drawdown_filter_pass. LLM 호출 전 무료 필터. daily_indicators 컬럼 직접 SELECT.",
  },
  {
    term: "신규 종목 (daily_delta)",
    meaning: "결정론 통과 + 최근 7일 분류 이력 없음. 평일 daily_delta 의 대상.",
  },
  {
    term: "재분석 (weekend)",
    meaning: "이미 분류된 종목도 weekend batch 마다 같은 prompt 로 다시 분류. 이전 분류와 다를 수 있음 (예: entry → ignore).",
  },
  {
    term: "현재 분류",
    meaning: "DISTINCT ON (symbol) ORDER BY classified_at DESC — 가장 최근 weekly_classification row 가 곧 '현재 상태'. UPDATE 안 함, append-only 설계.",
  },
```

- [ ] **Step 2: FAQ 에 weekend 관련 3 항목 추가**

Locate `const FAQ` (line 189). Append the following entries at the end of the array:

```ts
  {
    q: "주말 batch 와 daily_delta 가 같은 prompt 라면 둘 다 필요한가?",
    a: "시점이 다름. weekend = 매주 한 번 전체 결산 (시각차 확보, 분류 갱신). daily_delta = 평일에 새로 결정론 통과한 종목을 7일 기다리지 않고 즉시 분류 (조기 포착). 결과적으로 모든 minervini 통과 종목은 주 1회 weekend 로 재분류되고, 그 사이 신규는 daily_delta 로 즉시 합류.",
  },
  {
    q: "evaluate_pivot 의 abort 가 종목 분류를 ignore 로 바꾸나?",
    a: "아니오. evaluate_pivot 은 trigger_evaluation_log 만 INSERT. weekly_classification 의 row 는 그대로. abort 가 누적되어도 분류는 entry 로 유지됨. 다음 weekend batch 에서 LLM 이 base 가 깨졌다고 판단하면 비로소 ignore 로 재분류.",
  },
  {
    q: "한 종목이 한 주에 여러 번 분류될 수 있나?",
    a: "가능. 예: 토 weekend (entry 재분석). 다음 평일에 daily_delta 가 같은 종목을 다시 분류할 수는 없음 (최근 7일 분류 이력 있어서 신규 아님). 다만 다음 주 토 weekend 에서 또 재분석되어 row 가 추가. 결국 한 종목은 weekend 마다 매주 1번 재분석.",
  },
```

- [ ] **Step 3: Type-check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "feat(docs): GLOSSARY + FAQ 에 weekend 관련 항목 추가

- GLOSSARY 5 항목: weekend batch / 결정론 필터 / 신규 종목 / 재분석 / 현재 분류.
- FAQ 3 항목: weekend vs daily_delta 둘 다 필요한 이유 / abort 가 분류 안 바꾸는 이유 / 한 주에 여러 번 분류 가능 여부."
```

---

## Task 3: 시뮬레이션 정적 데이터

**Files:**
- Create: `web/src/data/llm-pipeline-simulation.ts`

- [ ] **Step 1: Create the data file with types + days**

Create `web/src/data/llm-pipeline-simulation.ts`:

```ts
// LLM 분석 안내 페이지의 1주일 시뮬레이션 정적 데이터.
// 10 종목 × 8 날짜 (토 W1 → 다음 토 W2). 코드 / prompt 의 실제 동작에 기반한 가상 시나리오.

export type SimClassification = "entry" | "watch" | "ignore";
export type SimTrigger = "breakout" | "promotion" | "invalidation";
export type SimDecision = "go_now" | "wait" | "abort";

export interface SimDay {
  date: string;       // YYYY-MM-DD
  label: string;      // "토 (W1)" / "월" / "다음 토 (W2)"
  stage: "weekend" | "daily-pipeline" | "market-closed" | null;
}

export interface SimModalRow {
  label: string;
  value: string;
}

export interface SimModal {
  title: string;
  inputs: SimModalRow[];
  outputs: SimModalRow[];
  reasoning: string;
  impact: string;
}

export interface SimCell {
  classification?: SimClassification;
  trigger?: SimTrigger;
  decision?: SimDecision;
  newlyDiscovered?: boolean;   // daily_delta 첫 등장
  reanalyzed?: boolean;         // weekend 재분석 (W 배지)
  notIncluded?: boolean;        // 결정론 미통과 종목 (회색)
  modal?: SimModal;
}

export interface SimRow {
  symbol: string;
  note?: string;
  cells: Record<string, SimCell>;  // date → cell
}

export const SIMULATION_DAYS: SimDay[] = [
  { date: "2026-05-16", label: "토 (W1)", stage: "weekend" },
  { date: "2026-05-17", label: "일",      stage: "market-closed" },
  { date: "2026-05-18", label: "월",      stage: "daily-pipeline" },
  { date: "2026-05-19", label: "화",      stage: "daily-pipeline" },
  { date: "2026-05-20", label: "수",      stage: "daily-pipeline" },
  { date: "2026-05-21", label: "목",      stage: "daily-pipeline" },
  { date: "2026-05-22", label: "금",      stage: "daily-pipeline" },
  { date: "2026-05-23", label: "토 (W2)", stage: "weekend" },
];
```

- [ ] **Step 2: Add SIMULATION_ROWS — first 5 symbols (weekend-initial)**

Append to the same file:

```ts
export const SIMULATION_ROWS: SimRow[] = [
  // ── SYM_001: entry → 월 breakout/go_now → 토 W2 entry 유지
  {
    symbol: "SYM_001",
    cells: {
      "2026-05-16": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_001 · 토 (W1) · weekend batch · 분류 = entry",
          inputs: [
            { label: "결정론 필터", value: "minervini_pass=TRUE, drawdown_filter_pass=TRUE" },
            { label: "패턴 분석", value: "cup_with_handle (handle 완성)" },
            { label: "시장 상태", value: "confirmed_uptrend, distribution_day_count=2" },
            { label: "RS Rating", value: "92" },
          ],
          outputs: [
            { label: "classification", value: "entry" },
            { label: "pattern", value: "cup_with_handle" },
            { label: "pivot_price", value: "84,500" },
            { label: "base_low (= stop_loss)", value: "76,200" },
            { label: "confidence", value: "0.88" },
          ],
          reasoning:
            "Stage 2 강함, cup 형성 35주, handle 7거래일 tight contraction. pivot 84,500 (handle high + 0.1). RS Line 52w high 선행. 거래량 contraction 양호. 위험 플래그 없음.",
          impact:
            "다음 평일부터 evaluate_pivot 의 active 대상. close > pivot + volume ≥ 1.5× avg 시 breakout 트리거.",
        },
      },
      "2026-05-18": {
        trigger: "breakout",
        decision: "go_now",
        modal: {
          title: "SYM_001 · 월 · evaluate_pivot · breakout → go_now",
          inputs: [
            { label: "현재 분류", value: "entry (토 W1)" },
            { label: "pivot_price", value: "84,500" },
            { label: "오늘 close", value: "85,200" },
            { label: "오늘 volume", value: "12,150,000 (1.82× avg_volume_20d)" },
            { label: "결정론 게이트", value: "close > pivot AND volume ≥ 1.5× avg → breakout" },
          ],
          outputs: [
            { label: "decision", value: "go_now" },
            { label: "confidence", value: "0.84" },
            { label: "abort_reason", value: "null" },
          ],
          reasoning:
            "Pivot 명확 돌파, 거래량 1.82× (1.4× 기준 충족), 종가 일중 range 상단. 최근 3일 distribution day 없음. handle 깨끗.",
          impact:
            "entry_params 단계로 진행 → 17 필드 매수 계획 생성. 분류는 entry 유지.",
        },
      },
      "2026-05-23": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_001 · 토 (W2) · weekend batch · 분류 = entry (유지)",
          inputs: [
            { label: "이전 분류", value: "entry (지난주 W1)" },
            { label: "이번 주 행동", value: "월요일 breakout + go_now → 매수 시그널 활성" },
            { label: "stage", value: "stage 2 유지" },
          ],
          outputs: [
            { label: "classification", value: "entry (유지)" },
            { label: "confidence", value: "0.87" },
          ],
          reasoning: "Pivot 돌파 후 정상 흐름. 매수 시그널 entry_params 에 기록됨. base 무효화 신호 없음.",
          impact: "다음 주에도 active. 추가 트리거는 매도/추가매수 신호로 작동.",
        },
      },
    },
  },

  // ── SYM_002: watch → 화 promotion/wait → 토 W2 entry 승격
  {
    symbol: "SYM_002",
    cells: {
      "2026-05-16": {
        classification: "watch",
        reanalyzed: true,
        modal: {
          title: "SYM_002 · 토 (W1) · weekend batch · 분류 = watch",
          inputs: [
            { label: "패턴", value: "flat_base 형성 중 (handle 미완성)" },
            { label: "pivot_price 후보", value: "80,000" },
            { label: "현재 close", value: "72,300 (pivot 의 약 90%)" },
            { label: "RS Rating", value: "78" },
          ],
          outputs: [
            { label: "classification", value: "watch" },
            { label: "pivot_price", value: "80,000" },
            { label: "confidence", value: "0.72" },
          ],
          reasoning:
            "Stage 2 진입, base 형성 중. pivot 도달 임박이지만 거래량 패턴 아직 보강 필요. 평일 promotion 트리거 대기.",
          impact:
            "evaluate_pivot 의 watch 대상. close ≥ pivot × 0.95 + volume ≥ avg 시 promotion 트리거.",
        },
      },
      "2026-05-19": {
        trigger: "promotion",
        decision: "wait",
        modal: {
          title: "SYM_002 · 화 · evaluate_pivot · promotion → wait",
          inputs: [
            { label: "현재 분류", value: "watch" },
            { label: "pivot_price", value: "80,000" },
            { label: "오늘 close", value: "76,500 (pivot 의 95.6%)" },
            { label: "오늘 volume", value: "3,420,000 (1.05× avg)" },
            { label: "결정론 게이트", value: "close ≥ pivot × 0.95 AND volume ≥ avg → promotion" },
          ],
          outputs: [
            { label: "decision", value: "wait" },
            { label: "confidence", value: "0.62" },
            { label: "abort_reason", value: "null" },
          ],
          reasoning:
            "pivot 95% 도달 + 거래량 1.0× — 게이트는 통과했지만 거래량이 1.4× 기준에 못 미침. 종가 일중 range 중간. 한두 일 더 보기.",
          impact:
            "분류는 watch 유지. trigger_evaluation_log 에 기록. 다음 평일 다시 게이트 평가.",
        },
      },
      "2026-05-23": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_002 · 토 (W2) · weekend batch · 분류 변경 watch → entry",
          inputs: [
            { label: "이전 분류", value: "watch (지난주 W1)" },
            { label: "이번 주 행동", value: "화요일 promotion + wait — 그 후 거래량 점진적 증가" },
            { label: "주간 마감 close", value: "81,200 (pivot 80,000 위)" },
            { label: "handle 형성", value: "완성됨" },
          ],
          outputs: [
            { label: "classification", value: "entry (승격)" },
            { label: "pivot_price", value: "80,000 (유지)" },
            { label: "confidence", value: "0.81" },
          ],
          reasoning:
            "Base 완성 + handle tight. 주간 mark 가 pivot 위. RS Line 강화. 다음 주 breakout 가능성 높음 — entry 분류 새 row INSERT.",
          impact:
            "다음 주부터 evaluate_pivot 의 breakout 게이트 대상 (watch 의 promotion 게이트 아님).",
        },
      },
    },
  },

  // ── SYM_003: watch → 변화 없음 → 토 W2 watch 유지
  {
    symbol: "SYM_003",
    cells: {
      "2026-05-16": {
        classification: "watch",
        reanalyzed: true,
        modal: {
          title: "SYM_003 · 토 (W1) · weekend batch · 분류 = watch",
          inputs: [
            { label: "패턴", value: "base 형성 초기 (depth 만 완성, length 부족)" },
            { label: "pivot_price 후보", value: "없음 (미정)" },
            { label: "RS Rating", value: "71" },
          ],
          outputs: [
            { label: "classification", value: "watch" },
            { label: "pivot_price", value: "null (base 미완성)" },
            { label: "confidence", value: "0.55" },
          ],
          reasoning: "Stage 2 진입했지만 base 가 5주 미만으로 짧음. 더 발전 필요. RS Line 도 아직 약함.",
          impact:
            "pivot_price=null 이므로 evaluate_pivot 의 결정론 게이트 자동 skip (필수 컬럼 NULL). 매일 평가에서 빠짐.",
        },
      },
      "2026-05-23": {
        classification: "watch",
        reanalyzed: true,
        modal: {
          title: "SYM_003 · 토 (W2) · weekend batch · 분류 = watch (유지)",
          inputs: [
            { label: "이번 주 변화", value: "거의 없음 (base 형성 지속)" },
            { label: "현재 close", value: "지난주 +1.2%" },
          ],
          outputs: [
            { label: "classification", value: "watch (유지)" },
            { label: "confidence", value: "0.58" },
          ],
          reasoning: "Base 7주로 성장, 아직 handle 형성 안 됨. RS Line 점진 강화. pivot 후보 아직 미정.",
          impact: "다음 주 weekend 까지 watch. pivot 확정되면 evaluate_pivot 대상으로 합류.",
        },
      },
    },
  },

  // ── SYM_004: entry → 수 invalidation/abort → 토 W2 ignore 강등
  {
    symbol: "SYM_004",
    cells: {
      "2026-05-16": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_004 · 토 (W1) · weekend batch · 분류 = entry",
          inputs: [
            { label: "패턴", value: "vcp (4 contractions)" },
            { label: "pivot_price", value: "152,000" },
            { label: "base_low (stop_loss)", value: "138,000" },
            { label: "RS Rating", value: "85" },
          ],
          outputs: [
            { label: "classification", value: "entry" },
            { label: "pattern", value: "vcp" },
            { label: "pivot_price", value: "152,000" },
            { label: "confidence", value: "0.82" },
          ],
          reasoning: "VCP 완성. tight 한 4번째 contraction. 거래량 점진 감소. pivot 152,000.",
          impact: "evaluate_pivot 의 entry 게이트. close > pivot + volume 1.5× 시 breakout.",
        },
      },
      "2026-05-20": {
        trigger: "invalidation",
        decision: "abort",
        modal: {
          title: "SYM_004 · 수 · evaluate_pivot · invalidation → abort",
          inputs: [
            { label: "현재 분류", value: "entry" },
            { label: "stop_loss (= base_low)", value: "138,000" },
            { label: "sma_50", value: "145,200" },
            { label: "오늘 close", value: "141,800" },
            { label: "결정론 게이트", value: "close < sma_50 → invalidation" },
            { label: "오늘 volume", value: "5,820,000 (1.62× avg, distribution)" },
          ],
          outputs: [
            { label: "decision", value: "abort" },
            { label: "confidence", value: "0.79" },
            { label: "abort_reason", value: "sma50_breach_distribution_volume" },
          ],
          reasoning:
            "Close < sma_50 (2.34% 이탈) + 거래량 1.62× distribution. base 신뢰 상실. 추가 매수 금지.",
          impact:
            "**분류는 entry 그대로**. trigger_evaluation_log 에 abort 기록. 토 W2 weekend batch 가 재분석해야 비로소 ignore 로 강등 가능.",
        },
      },
      "2026-05-23": {
        classification: "ignore",
        reanalyzed: true,
        modal: {
          title: "SYM_004 · 토 (W2) · weekend batch · 분류 변경 entry → ignore",
          inputs: [
            { label: "이전 분류", value: "entry (지난주 W1)" },
            { label: "이번 주 행동", value: "수요일 invalidation + abort 기록" },
            { label: "주간 마감 close", value: "140,500 (pivot 아래 7.6%)" },
            { label: "sma_50 위치", value: "여전히 close > sma_50 회복 못 함" },
          ],
          outputs: [
            { label: "classification", value: "ignore (강등)" },
            { label: "confidence", value: "0.74" },
            { label: "risk_flags", value: '["base_broken"]' },
          ],
          reasoning:
            "VCP base 가 sma_50 이탈로 무효화. 추세 손상. stage 2 종료 가능성. 새 base 형성까지 ignore.",
          impact: "evaluate_pivot 의 평가 대상에서 빠짐. 새 base 형성 시 다시 weekend 가 watch/entry 로 승격.",
        },
      },
    },
  },

  // ── SYM_005: ignore → 변화 없음 → 토 W2 ignore 유지
  {
    symbol: "SYM_005",
    cells: {
      "2026-05-16": {
        classification: "ignore",
        reanalyzed: true,
        modal: {
          title: "SYM_005 · 토 (W1) · weekend batch · 분류 = ignore",
          inputs: [
            { label: "패턴", value: "climax_run" },
            { label: "RS Rating", value: "98 (과열)" },
            { label: "52w high 대비", value: "+62% (climax)" },
          ],
          outputs: [
            { label: "classification", value: "ignore" },
            { label: "pattern", value: "climax_run" },
            { label: "confidence", value: "0.81" },
            { label: "risk_flags", value: '["climax_run", "wide_and_loose", "late_stage_base"]' },
          ],
          reasoning:
            "최근 12주간 +85% 상승 후 wide-and-loose 흔들림. 매수 적기 아님 (이미 진행). climax 위험 명확.",
          impact: "evaluate_pivot 대상 아님 (ignore). 다음 weekend 에서 stage 변경 시 재진입 가능.",
        },
      },
      "2026-05-23": {
        classification: "ignore",
        reanalyzed: true,
        modal: {
          title: "SYM_005 · 토 (W2) · weekend batch · 분류 = ignore (유지)",
          inputs: [
            { label: "이번 주 변화", value: "-8.2% (high volatility)" },
            { label: "stage", value: "여전히 climax 진행 또는 phase 3 진입" },
          ],
          outputs: [
            { label: "classification", value: "ignore (유지)" },
            { label: "confidence", value: "0.83" },
          ],
          reasoning: "Climax run 지속. 새 base 형성 아직 안 됨. 변동성만 큼.",
          impact: "ignore 유지.",
        },
      },
    },
  },
];
```

- [ ] **Step 3: Append SIMULATION_ROWS — symbols 6~8 (daily_delta 신규)**

Append to the same SIMULATION_ROWS array (inside the brackets, before the closing `];`):

```ts
  // ── SYM_006: 화 daily_delta entry → 목 breakout/go_now → 토 W2 entry 유지
  {
    symbol: "SYM_006",
    cells: {
      "2026-05-19": {
        classification: "entry",
        newlyDiscovered: true,
        modal: {
          title: "SYM_006 · 화 · daily_delta · 신규 분류 = entry",
          inputs: [
            { label: "트리거", value: "오늘 새로 minervini_pass + drawdown_filter_pass 통과" },
            { label: "최근 7일 분류 이력", value: "없음 (신규)" },
            { label: "패턴", value: "cup_with_handle (handle 7거래일 완성)" },
            { label: "pivot_price 후보", value: "98,500" },
          ],
          outputs: [
            { label: "classification", value: "entry" },
            { label: "pattern", value: "cup_with_handle" },
            { label: "pivot_price", value: "98,500" },
            { label: "confidence", value: "0.83" },
          ],
          reasoning:
            "Cup 32주 + handle 7거래일 tight. Stage 2 강함. RS Line 강세. pivot 명확. 위험 플래그 없음. analyze_chart_v3 prompt (weekend 와 동일) — 신규 후보로 즉시 entry 분류.",
          impact:
            "이 시점부터 evaluate_pivot 의 active 대상. 다음 평일부터 breakout 게이트 평가.",
        },
      },
      "2026-05-21": {
        trigger: "breakout",
        decision: "go_now",
        modal: {
          title: "SYM_006 · 목 · evaluate_pivot · breakout → go_now",
          inputs: [
            { label: "현재 분류", value: "entry (화요일 daily_delta)" },
            { label: "pivot_price", value: "98,500" },
            { label: "오늘 close", value: "99,800" },
            { label: "오늘 volume", value: "4,250,000 (1.93× avg_volume_20d)" },
          ],
          outputs: [
            { label: "decision", value: "go_now" },
            { label: "confidence", value: "0.87" },
          ],
          reasoning:
            "Pivot 돌파 +1.3% + 거래량 1.93× (1.4× 기준 초과). 종가 일중 range 상단. handle 깨끗.",
          impact: "entry_params 단계로 진행 → 매수 계획 생성.",
        },
      },
      "2026-05-23": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_006 · 토 (W2) · weekend batch · 분류 = entry (유지)",
          inputs: [
            { label: "이전 분류", value: "entry (화 daily_delta)" },
            { label: "이번 주 행동", value: "목요일 breakout + go_now" },
          ],
          outputs: [
            { label: "classification", value: "entry (유지)" },
            { label: "confidence", value: "0.85" },
          ],
          reasoning: "Pivot 돌파 후 정상 진입 상태. 추가 변화 없음.",
          impact: "다음 주에도 active.",
        },
      },
    },
  },

  // ── SYM_007: 수 daily_delta watch
  {
    symbol: "SYM_007",
    cells: {
      "2026-05-20": {
        classification: "watch",
        newlyDiscovered: true,
        modal: {
          title: "SYM_007 · 수 · daily_delta · 신규 분류 = watch",
          inputs: [
            { label: "트리거", value: "오늘 새로 결정론 통과 (minervini_pass + drawdown_filter)" },
            { label: "패턴", value: "flat_base 형성 초기 (4주)" },
            { label: "RS Rating", value: "73" },
          ],
          outputs: [
            { label: "classification", value: "watch" },
            { label: "pattern", value: "flat_base" },
            { label: "pivot_price", value: "null (base 미완성)" },
            { label: "confidence", value: "0.61" },
          ],
          reasoning:
            "Stage 2 진입했지만 base 짧음 (4주). 더 발전 필요. handle 미형성. watch 분류로 대기.",
          impact: "pivot null 이므로 evaluate_pivot skip. 다음 weekend 까지 watch.",
        },
      },
      "2026-05-23": {
        classification: "watch",
        reanalyzed: true,
        modal: {
          title: "SYM_007 · 토 (W2) · weekend batch · 분류 = watch (유지)",
          inputs: [
            { label: "이전 분류", value: "watch (수 daily_delta)" },
            { label: "이번 주 변화", value: "base 5주로 성장, 아직 handle 미형성" },
          ],
          outputs: [
            { label: "classification", value: "watch (유지)" },
            { label: "confidence", value: "0.64" },
          ],
          reasoning: "Base 발전 중이지만 미완성. pivot 후보 아직 미정.",
          impact: "watch 유지.",
        },
      },
    },
  },

  // ── SYM_008: 목 daily_delta ignore
  {
    symbol: "SYM_008",
    cells: {
      "2026-05-21": {
        classification: "ignore",
        newlyDiscovered: true,
        modal: {
          title: "SYM_008 · 목 · daily_delta · 신규 분류 = ignore",
          inputs: [
            { label: "트리거", value: "오늘 새로 결정론 통과" },
            { label: "패턴", value: "late_stage_base (5번째 base)" },
            { label: "RS Rating", value: "76" },
          ],
          outputs: [
            { label: "classification", value: "ignore" },
            { label: "pattern", value: "late_stage_base" },
            { label: "confidence", value: "0.78" },
            { label: "risk_flags", value: '["late_stage_base"]' },
          ],
          reasoning:
            "Stage 2 후반. 5번째 base — 실패 확률 높음 (Minervini: 1-2번째 base 가 가장 안전). watch 도 위험.",
          impact: "ignore. 7일 후 (다음 weekend 또는 daily_delta) 까지 재진입 가능 (조건 충족 시).",
        },
      },
      "2026-05-23": {
        classification: "ignore",
        reanalyzed: true,
        modal: {
          title: "SYM_008 · 토 (W2) · weekend batch · 분류 = ignore (유지)",
          inputs: [
            { label: "이전 분류", value: "ignore (목 daily_delta)" },
            { label: "이번 주 변화", value: "거의 없음" },
          ],
          outputs: [
            { label: "classification", value: "ignore (유지)" },
          ],
          reasoning: "late_stage_base 위험 그대로.",
          impact: "ignore 유지.",
        },
      },
    },
  },
];
```

- [ ] **Step 4: Append SIMULATION_ROWS — symbols 9, 10 (결정론 미통과 참조)**

Append two more entries to SIMULATION_ROWS:

```ts
SIMULATION_ROWS.push(
  {
    symbol: "SYM_009",
    note: "결정론 미통과 — minervini_pass=FALSE (예: 가격 < sma_50)",
    cells: {
      "2026-05-16": { notIncluded: true },
      "2026-05-23": { notIncluded: true },
    },
  },
  {
    symbol: "SYM_010",
    note: "결정론 미통과 — drawdown_filter_pass=FALSE (52w high 대비 -55%)",
    cells: {
      "2026-05-16": { notIncluded: true },
      "2026-05-23": { notIncluded: true },
    },
  },
);
```

> **Note**: TypeScript `const` 배열에 `.push()` 는 가능 (referential mutation OK). 또는 더 깨끗하게: SIMULATION_ROWS 배열을 처음부터 만들 때 모든 10 종목을 한 번에 정의. 가독성 위해 .push 로 분리 — 9/10 은 명확히 "참조용" 으로 표현.

- [ ] **Step 5: Type-check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 6: Commit**

```bash
git add web/src/data/llm-pipeline-simulation.ts
git commit -m "feat(docs): LLM 안내 페이지의 1주일 시뮬레이션 정적 데이터

10 종목 × 8 날짜. 각 셀에 분류/트리거/decision + 모달 콘텐츠 (LLM 입출력
+ reasoning + 영향). 코드/prompt 기반 가상 시나리오:
- SYM_001 (entry → breakout/go_now)
- SYM_002 (watch → promotion/wait → 토 entry 승격)
- SYM_003 (watch → 변화 없음)
- SYM_004 (entry → invalidation/abort → 토 ignore 강등)
- SYM_005 (ignore → 유지)
- SYM_006~008 (평일 daily_delta 신규 분류)
- SYM_009/010 (결정론 미통과 참조)"
```

---

## Task 4: `SimulationMatrix` 컴포넌트

**Files:**
- Create: `web/src/pages/llm-pipeline/SimulationMatrix.tsx`

- [ ] **Step 1: Create file with cell + legend rendering**

Create the directory `web/src/pages/llm-pipeline/` if it doesn't exist, then create `web/src/pages/llm-pipeline/SimulationMatrix.tsx`:

```tsx
import type {
  SimCell,
  SimClassification,
  SimDay,
  SimRow,
} from "../../data/llm-pipeline-simulation";

interface Props {
  days: SimDay[];
  rows: SimRow[];
  onCellClick: (row: SimRow, day: SimDay) => void;
}

const CLASS_STYLE: Record<SimClassification, { bg: string; emoji: string; label: string }> = {
  entry:  { bg: "bg-green-100 border-green-300",   emoji: "🟢", label: "entry" },
  watch:  { bg: "bg-yellow-100 border-yellow-300", emoji: "🟡", label: "watch" },
  ignore: { bg: "bg-gray-200 border-gray-300",     emoji: "⬜", label: "ignore" },
};

const DECISION_BADGE: Record<string, { emoji: string; title: string }> = {
  go_now: { emoji: "✨", title: "go_now (즉시 매수)" },
  wait:   { emoji: "⏸",  title: "wait (보류)" },
  abort:  { emoji: "⚠️", title: "abort (베이스 무효화)" },
};

function CellContent({ cell }: { cell: SimCell }) {
  if (cell.notIncluded) {
    return <span className="text-faint text-data-xs">결정론 미통과</span>;
  }

  const cls = cell.classification;
  const style = cls ? CLASS_STYLE[cls] : null;
  const badge = cell.decision ? DECISION_BADGE[cell.decision] : null;

  return (
    <div className="flex items-center justify-between gap-1">
      <div className="flex items-center gap-1">
        {style && (
          <>
            <span>{style.emoji}</span>
            <span className="text-data-xs">{style.label}</span>
          </>
        )}
        {cell.trigger && (
          <span className="text-faint text-data-xs ml-1">{cell.trigger}</span>
        )}
        {cell.newlyDiscovered && (
          <span
            className="text-data-xs bg-blue-100 text-blue-700 px-1 rounded ml-1"
            title="daily_delta 신규 분류"
          >
            ⚡
          </span>
        )}
      </div>
      {badge && (
        <span className="text-data-xs" title={badge.title}>
          {badge.emoji}
        </span>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-data-xs text-muted mb-3">
      <span>🟢 entry</span>
      <span>🟡 watch</span>
      <span>⬜ ignore</span>
      <span className="text-faint">|</span>
      <span>✨ go_now</span>
      <span>⏸ wait</span>
      <span>⚠️ abort</span>
      <span className="text-faint">|</span>
      <span>⚡ daily_delta 신규</span>
      <span>W weekend 재분석</span>
    </div>
  );
}

export function SimulationMatrix({ days, rows, onCellClick }: Props) {
  return (
    <div>
      <Legend />
      <div className="overflow-x-auto">
        <table className="w-full text-data border-collapse">
          <thead>
            <tr>
              <th className="text-left py-2 pr-3 caps text-faint">종목</th>
              {days.map((d) => (
                <th
                  key={d.date}
                  className="text-left py-2 px-2 caps text-faint border-l border-hairline"
                >
                  <div className="font-semibold text-ink">{d.label}</div>
                  <div className="num text-data-xs text-faint">{d.date}</div>
                  {d.stage && (
                    <div className="text-data-xs text-muted">
                      {d.stage === "weekend"
                        ? "weekend"
                        : d.stage === "daily-pipeline"
                          ? "full-daily"
                          : d.stage === "market-closed"
                            ? "휴장"
                            : ""}
                    </div>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.symbol} className="border-t border-hairline">
                <td className="py-2 pr-3 align-top">
                  <div className="num font-semibold text-ink">{row.symbol}</div>
                  {row.note && (
                    <div className="text-data-xs text-faint mt-0.5">{row.note}</div>
                  )}
                </td>
                {days.map((d) => {
                  const cell = row.cells[d.date];
                  const hasContent =
                    cell &&
                    (cell.classification ||
                      cell.trigger ||
                      cell.notIncluded);
                  const style = cell?.classification
                    ? CLASS_STYLE[cell.classification].bg
                    : cell?.notIncluded
                      ? "bg-stone-50"
                      : "";
                  const clickable = hasContent && cell?.modal;
                  return (
                    <td
                      key={d.date}
                      onClick={() => clickable && cell && onCellClick(row, d)}
                      className={`py-2 px-2 align-top border-l border-hairline relative ${style} ${clickable ? "cursor-pointer hover:opacity-80" : ""}`}
                    >
                      {cell?.reanalyzed && (
                        <span
                          className="absolute top-0.5 left-0.5 text-data-xs bg-violet-100 text-violet-700 px-1 rounded"
                          title="weekend 재분석"
                        >
                          W
                        </span>
                      )}
                      {cell ? <CellContent cell={cell} /> : <span className="text-faint">—</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/llm-pipeline/SimulationMatrix.tsx
git commit -m "feat(docs): SimulationMatrix 컴포넌트 (격자)

10 종목 × 8 날짜 격자. 셀 = 분류 배경색 + 이모지 + 트리거/decision 배지.
weekend 재분석 = W 배지, daily_delta 신규 = ⚡, 결정론 미통과 = 회색.
셀 클릭 시 onCellClick(row, day) 콜백."
```

---

## Task 5: `SimulationModal` 컴포넌트

**Files:**
- Create: `web/src/pages/llm-pipeline/SimulationModal.tsx`

- [ ] **Step 1: Create modal component**

Create `web/src/pages/llm-pipeline/SimulationModal.tsx`:

```tsx
import { useEffect } from "react";
import { X } from "lucide-react";
import type { SimModal } from "../../data/llm-pipeline-simulation";

interface Props {
  open: boolean;
  modal: SimModal | null;
  onClose: () => void;
}

export function SimulationModal({ open, modal, onClose }: Props) {
  // ESC 키 닫기
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !modal) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
      onClick={onClose}
    >
      <div
        className="bg-paper border border-hairline rounded-2xl shadow-bento-hover max-w-3xl w-full max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between px-6 py-4 border-b border-hairline sticky top-0 bg-paper">
          <h3 className="text-subhead font-bold text-ink">{modal.title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="p-1 rounded hover:bg-stone-100 text-muted"
          >
            <X size={18} />
          </button>
        </header>

        <div className="px-6 py-5 grid grid-cols-1 md:grid-cols-2 gap-6">
          <section>
            <h4 className="caps text-faint mb-2">LLM 입력 (요약)</h4>
            <dl className="space-y-2 text-data">
              {modal.inputs.map((row) => (
                <div key={row.label}>
                  <dt className="text-data-xs text-faint">{row.label}</dt>
                  <dd className="text-ink num">{row.value}</dd>
                </div>
              ))}
            </dl>
          </section>

          <section>
            <h4 className="caps text-faint mb-2">LLM 출력</h4>
            <dl className="space-y-2 text-data">
              {modal.outputs.map((row) => (
                <div key={row.label}>
                  <dt className="text-data-xs text-faint">{row.label}</dt>
                  <dd className="text-ink num">{row.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>

        <div className="px-6 pb-5">
          <h4 className="caps text-faint mb-2">Reasoning</h4>
          <p className="text-data text-ink leading-relaxed">{modal.reasoning}</p>
        </div>

        <div className="px-6 pb-6">
          <h4 className="caps text-faint mb-2">이 결과의 영향</h4>
          <p className="text-data text-muted leading-relaxed">{modal.impact}</p>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/llm-pipeline/SimulationModal.tsx
git commit -m "feat(docs): SimulationModal 컴포넌트 (셀 클릭 시 dialog)

ESC + 백드롭 클릭 닫기. 2 컬럼 (입력/출력) + reasoning + 영향.
fixed + z-50 + max-w-3xl + max-h-[85vh] overflow-y-auto."
```

---

## Task 6: `LlmPipelinePage` 통합

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx`

- [ ] **Step 1: Add imports + state**

In `web/src/pages/LlmPipelinePage.tsx`, top of the file (after the existing `import { MermaidDiagram } from "../components/MermaidDiagram";`), add:

```tsx
import { useState } from "react";
import {
  SIMULATION_DAYS,
  SIMULATION_ROWS,
  type SimDay,
  type SimModal,
  type SimRow,
} from "../data/llm-pipeline-simulation";
import { SimulationMatrix } from "./llm-pipeline/SimulationMatrix";
import { SimulationModal } from "./llm-pipeline/SimulationModal";
```

In the `LlmPipelinePage` function body (start of `function LlmPipelinePage()`), add the modal state:

```tsx
  const [activeModal, setActiveModal] = useState<SimModal | null>(null);

  function handleCellClick(row: SimRow, day: SimDay) {
    const cell = row.cells[day.date];
    if (cell?.modal) setActiveModal(cell.modal);
  }
```

- [ ] **Step 2: Insert simulation section in the return JSX**

Locate the existing section block `{/* ② 단계별 카드 */}` (line ~429). After the closing `))}` of the STAGES.map (line ~432), insert a new section block:

```tsx
      {/* ③ 1주일 시뮬레이션 */}
      <section className="bento p-6 mb-4">
        <h3 className="text-subhead font-bold text-ink mb-3">
          1주일 시뮬레이션 — 10 종목이 어떻게 처리되나
        </h3>
        <p className="text-data-xs text-muted mb-4 leading-relaxed">
          토(W1) → 다음 토(W2) 8 일 동안 10 종목 각각이 weekend / daily_delta / evaluate_pivot 에서 어떻게 처리되는지.
          각 셀 클릭 시 LLM 입력 / 출력 / reasoning / 영향 상세.
        </p>
        <SimulationMatrix
          days={SIMULATION_DAYS}
          rows={SIMULATION_ROWS}
          onCellClick={handleCellClick}
        />
      </section>

      <SimulationModal
        open={activeModal != null}
        modal={activeModal}
        onClose={() => setActiveModal(null)}
      />
```

Renumber the subsequent sections (state diagram, matrix, glossary, FAQ) — change `③` → `④` etc. in their comments only. The JSX content stays the same.

- [ ] **Step 3: Update the header subtitle to mention weekend**

Locate the page header `<p>` near line 413:

```tsx
        <p className="text-data-xs text-muted mt-3 leading-relaxed">
          평일 매일 실행되는 LLM full-daily 작업의 4 단계 흐름, 결정론 로직, LLM 로직, 책 원전 정리.
          시스템 이해 + 향후 수정의 기반.
        </p>
```

Replace with:

```tsx
        <p className="text-data-xs text-muted mt-3 leading-relaxed">
          평일 4단계 (daily_delta → evaluate_pivot → entry_params → performance) 와
          주말 1단계 (weekend batch) 의 흐름, 결정론 로직, LLM 로직, 책 원전 정리.
          + 10 종목 1주일 시뮬레이션으로 처음 보는 사용자도 흐름 이해 가능.
        </p>
```

- [ ] **Step 4: Type-check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`

Expected: `CLEAN`.

- [ ] **Step 5: Manual smoke test**

If the dev server is running, open `http://localhost:5173/docs/llm-pipeline` and verify:
- 5 stage 카드 (weekend → daily_delta → evaluate → entry → performance) 가 위→아래로 표시
- 1주일 시뮬레이션 격자가 표시 (행 10개, 열 8개)
- 셀들이 분류 색 + 이모지로 표시, 클릭 가능한 셀에 hover:opacity 변화
- 클릭 시 모달 열림, 헤더 / 좌우 컬럼 / reasoning / 영향 표시
- ESC + 백드롭 클릭 → 모달 닫힘
- 결정론 미통과 행 (SYM_009/_010) 이 회색 + "결정론 미통과" 텍스트

(dev 서버가 없으면 type-check 만으로 OK 표시 후 사용자에게 수동 확인 권유)

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "feat(docs): LlmPipelinePage 에 1주일 시뮬레이션 섹션 + 모달 통합

stage 카드 다음에 SimulationMatrix 삽입. 셀 클릭 시 SimulationModal 열림.
페이지 서브타이틀 갱신 (주말 + 시뮬레이션 언급)."
```

---

## Self-Review Notes

**Spec coverage check (against `docs/superpowers/specs/2026-05-21-llm-pipeline-weekend-simulation-design.md`):**

| 스펙 항목 | 구현 task |
|---|---|
| STAGES 에 weekend (order=0) 추가 | Task 1 Step 1 |
| daily_delta 카드 설명 갱신 | Task 1 Step 2 |
| evaluate_pivot actions 갱신 (분류 미변경 명시) | Task 1 Step 3 |
| GLOSSARY 에 weekend 관련 5 항목 | Task 2 Step 1 |
| FAQ 에 weekend 관련 3 항목 | Task 2 Step 2 |
| 시뮬레이션 정적 데이터 (10 종목 × 8 일) | Task 3 |
| SimulationMatrix (격자 + 색/이모지) | Task 4 |
| SimulationModal (dialog + 입출력 + reasoning + 영향) | Task 5 |
| ESC / 백드롭 클릭 닫기 | Task 5 Step 1 |
| LlmPipelinePage 통합 (state + section 삽입) | Task 6 |
| 결정론 미통과 종목 회색 + 텍스트 | Task 3 Step 4 + Task 4 (notIncluded 분기) |
| 셀 호버 / 클릭 가능 표시 | Task 4 Step 1 (`cursor-pointer hover:opacity-80`) |

빠진 항목 없음.

**Type / 네이밍 일관성:**

- `SimDay`, `SimRow`, `SimCell`, `SimModal`, `SimModalRow`, `SimClassification`, `SimTrigger`, `SimDecision` 모두 Task 3 에서 정의 → Task 4/5/6 에서 import.
- `SIMULATION_DAYS`, `SIMULATION_ROWS` Task 3 export → Task 6 import.
- `handleCellClick(row, day)` 시그니처가 Task 4 의 `onCellClick: (row: SimRow, day: SimDay) => void` 와 일치.
- `cell.modal` 이 `SimModal | undefined` → `setActiveModal(cell.modal)` 호출 시 `?.modal` 가드로 안전.

**Risks:**

- `SimulationModal` 의 z-50 backdrop 이 다른 모달과 충돌할 가능성. 현재 페이지에 다른 모달 없음 → 안전.
- 시뮬레이션 데이터는 정적이라 향후 prompt 변경 시 reasoning 표현 drift 가능. 별도 follow-up 에서 정렬.
- `SimulationMatrix` 의 가로 스크롤 (`overflow-x-auto`) — 모바일에서 8 열은 좁아질 수 있음. 데스크탑 기준 설계 (사용자가 모바일에서 이 페이지 본다고 명시 안 함).
