# LLM 분석 안내 페이지 — 초보 친화 리팩토링 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `web/src/pages/LlmPipelinePage.tsx` 의 `StageCard` 5 개와 외부 섹션 (mermaid / matrix / glossary / FAQ) 을 주식 1~3년차 + 시스템 초보가 이해할 수 있게 친절화 + 전문가용 raw 정보는 targeted fold 로 보존. drift 차단을 위해 audit 데이터 source 를 직접 import.

**Architecture:** 카드별 `<details>` targeted fold (8 조건 / ZIP 13 / 9 패턴 / 13 risk / 18 entry_params 필드 / SQL 상세). audit `risk-flags.ts` / `base-patterns.ts` / `minervini.ts` / `zip-files.ts` 직접 import (drift 차단). 신규 source 는 audit 에 없는 정보만 (11 테이블 한 줄 설명, 18 entry_params 필드 풀이).

**Tech Stack:** React + TypeScript, Tailwind CSS, React Router, native `<details>` element (no React state needed), Mermaid (보존).

**Spec:** [`../specs/2026-05-29-llm-pipeline-page-beginner-rewrite-design.md`](../specs/2026-05-29-llm-pipeline-page-beginner-rewrite-design.md)

---

## ⚙️ Execution Notes

- **Frontend test infra**: 프로젝트는 backend 위주 pytest 운영. frontend 의 vitest/RTL 부재 — UI 회귀 검증은 `npx tsc --noEmit` (타입) + 수동 시각 검증 (페이지 진입). 각 task 마지막에 tsc 무결성 + git commit.
- **Drift 차단 원칙**: pipeline 페이지가 audit 데이터를 *복제* 하지 말 것. audit `web/src/data/llm-pipeline-audit/*.ts` 에 있는 것은 *import*. 본 plan 의 *신규 데이터 파일* 2개는 audit 에 없는 정보 (11 테이블 한 줄 설명, 18 entry_params 필드 풀이) 만.
- **사용자 지적 *"17 필드"* 는 stale** — 실제는 18 (`prompts/calculate_entry_params_v2_0.md` §10 validation 표 검증). 본 plan 은 18 로 정합화.
- **Commit per task** — 11 task = 11 commit. 각 task 종료 시 working tree 깨끗.
- **현재 branch = main**. 프로젝트 패턴은 main 직접 commit + push. 본 plan 도 동일 패턴.

---

## File Structure

### 신규 (Create)

| 파일 | 책임 |
|---|---|
| `web/src/data/llm-pipeline/tables.ts` | 11 테이블 한 줄 설명 + 컬럼 요약 |
| `web/src/data/llm-pipeline/entry-params-fields.ts` | 18 entry_params 필드 카테고리·설명 |
| `web/src/pages/llm-pipeline/ListFold.tsx` | "X 항목 모두 보기 ▼" 공통 fold 래퍼 |
| `web/src/pages/llm-pipeline/TableExplainerList.tsx` | 카드 안 입출력 테이블 *칩 + 1줄* 표시 |

### 수정 (Modify)

| 파일 | 변경 부분 |
|---|---|
| `web/src/pages/LlmPipelinePage.tsx` | `STAGES`, `TRIGGER_DECISION_MATRIX`, `GLOSSARY`, `FAQ`, `DIAGRAM_DATA_FLOW`, `DIAGRAM_STATE`, `StageCard`, `TriggerDecisionMatrix`, header 한 줄 요약, 안내 박스 미세 정련 |

### 비변경

- `web/src/pages/LlmPipelineAuditPage.tsx` + `web/src/data/llm-pipeline-audit/*` (드리프트 차단을 위해 import 만, 변경 없음).
- `prompts/*.md` / `kr_pipeline/common/thresholds.py` / `web/src/data/thresholds.generated.ts` (동작/임계 무관).

---

### Task 1: 11 테이블 한 줄 설명 데이터 파일

**Files:**
- Create: `web/src/data/llm-pipeline/tables.ts`

**근거 source**: `kr_pipeline/db/schema.sql` 의 `CREATE TABLE` 정의 + `docs/superpowers/specs/2026-05-29-llm-pipeline-page-beginner-rewrite-design.md` §6.

**대상 11 테이블** (StageCard 입출력에 등장):
`daily_indicators` · `weekly_indicators` · `daily_prices` · `index_daily` · `market_context_daily` · `corporate_actions` · `stocks` · `weekly_classification` · `trigger_evaluation_log` · `entry_params` · `signal_performance`.

- [ ] **Step 1: schema.sql 11 테이블 정의 확인**

```bash
grep -n "CREATE TABLE IF NOT EXISTS" kr_pipeline/db/schema.sql
```

각 테이블의 컬럼 정의를 fact source 로 사용. `pipeline_runs` / `weekly_prices` / `weekly_index` / `dart_corp_codes` 는 본 페이지 비대상이므로 제외.

- [ ] **Step 2: `web/src/data/llm-pipeline/tables.ts` 작성**

```ts
// 11 테이블 한 줄 설명 + 컬럼 요약 (StageCard 입출력에 등장하는 것만)
// 근거: kr_pipeline/db/schema.sql

export interface TableInfo {
  name: string;
  short: string;       // 한 줄 친절 설명 (카드 본문에 그대로 표시)
  details: string;     // fold 안 컬럼 요약 (2-3 문장, 핵심 컬럼 명시)
  pkey: string;        // primary key (engineering 정보, fold 안)
}

export const TABLES: Record<string, TableInfo> = {
  daily_indicators: {
    name: "daily_indicators",
    short: "종목별 매일 지표값 — SMA·RS·거래량 평균·각종 flag 등.",
    details:
      "종목 × 날짜별 모든 지표 한 행. 핵심 컬럼: close, sma_50/150/200, rs_rating, avg_volume_50d, volume_ratio_50d, pocket_pivot_flag, distribution_day_flag, minervini_pass (Trend Template 8조건 통과 여부). 매일 cron 으로 적재.",
    pkey: "(ticker, date)",
  },
  weekly_indicators: {
    name: "weekly_indicators",
    short: "종목별 주봉 지표 — 일봉으로부터 W-FRI 리샘플.",
    details:
      "종목 × 주별 지표. 일봉 daily_indicators 를 주봉으로 집계. 핵심 컬럼: weekly close, weekly volume, weekly RS, sma_10w (= 10주 이동평균).",
    pkey: "(ticker, week_end_date)",
  },
  daily_prices: {
    name: "daily_prices",
    short: "종목별 일봉 OHLCV 원시 — 모든 지표의 출발점.",
    details:
      "종목 × 날짜별 시·고·저·종가 + 거래량. 수정종가도 별도 컬럼. 핵심 컬럼: open, high, low, close, adj_close, volume.",
    pkey: "(ticker, date)",
  },
  index_daily: {
    name: "index_daily",
    short: "KOSPI / KOSDAQ 지수 일봉.",
    details:
      "지수 × 날짜별 OHLCV. KOSPI 코드 '1001', KOSDAQ '2001'. 시장 컨텍스트·종목 성과 비교의 기준.",
    pkey: "(index_code, date)",
  },
  market_context_daily: {
    name: "market_context_daily",
    short: "시장 전체 상태 (uptrend / correction / downtrend / rally_attempt).",
    details:
      "지수 × 날짜별 시장 진단. 핵심 컬럼: current_status (4-enum), distribution_day_count_last_25, last_follow_through_day, days_since_follow_through, pct_stocks_above_200d_ma. LLM 의 시장 컨텍스트 입력.",
    pkey: "(date, index_code)",
  },
  corporate_actions: {
    name: "corporate_actions",
    short: "기업 행위 — 액면분할·합병·배당 등.",
    details:
      "종목 × 날짜별 코퍼릿 이벤트 (e.g. 액면분할 1:5). 차트·지표가 분할 직후 왜곡되지 않도록 보정. DART API 로 수집.",
    pkey: "(ticker, event_date, action_type)",
  },
  stocks: {
    name: "stocks",
    short: "KRX 종목 마스터 — 이름·시장·섹터·상장폐지 여부.",
    details:
      "한국거래소의 모든 종목 식별 정보. 핵심 컬럼: ticker, name, market (KOSPI/KOSDAQ), sector, delisted_at (NULL = 상장 중).",
    pkey: "(ticker)",
  },
  weekly_classification: {
    name: "weekly_classification",
    short: "LLM 의 종목 정성 분류 결과 — entry / watch / ignore.",
    details:
      "종목 × 분류시각별 행. *append-only* = 이전 분류 보존, 새 분류는 새 행 추가. '현재 분류' = 가장 최근 행. 핵심 컬럼: classification (entry/watch/ignore), confidence, pattern, pivot_price, base_depth_pct, risk_flags, source (weekend/daily_delta), classified_at.",
    pkey: "(symbol, classified_at)",
  },
  trigger_evaluation_log: {
    name: "trigger_evaluation_log",
    short: "평일 매일 watch/entry 종목의 LLM 트리거 평가 결과.",
    details:
      "종목 × 평가시각별 행. 결정론 게이트가 감지한 트리거 (breakout/promotion/invalidation) 와 LLM 의 결정 (go_now/wait/abort) 기록. 분류는 변경 안 함 (append-only 로그).",
    pkey: "(symbol, evaluated_at)",
  },
  entry_params: {
    name: "entry_params",
    short: "실질 매수 시그널 — LLM 이 산출한 18 필드 매수 계획.",
    details:
      "go_now 결정된 종목의 entry_mode·pivot_price·trigger_price·stop_loss·target·position size·breakout 거래량 요건 등 18 필드 (자세한 풀이는 카드 안 fold). signal_at = 매수 시그널 발생 시각.",
    pkey: "(symbol, signal_at)",
  },
  signal_performance: {
    name: "signal_performance",
    short: "entry_params 시그널의 사후 성과 — 1주·2주·4주·8주 후 가격 + 시장 대비.",
    details:
      "시그널 × 시점별 추적. 핵심 컬럼: price_1w / price_2w / price_4w / price_8w + 같은 기간 KOSPI/KOSDAQ 변화. 8주 후 데이터 채워지면 사실상 추적 종료. 90일 cutoff.",
    pkey: "(symbol, signal_at)",
  },
};
```

- [ ] **Step 3: tsc 무결성 확인**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -5
```

기대: 출력 없음 (0 error).

- [ ] **Step 4: Commit**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
git add web/src/data/llm-pipeline/tables.ts
git commit -m "feat(llm-pipeline data): 11 테이블 한 줄 설명 + 컬럼 요약 source

StageCard 입출력에 등장하는 11 테이블 (daily_indicators/weekly_indicators/
daily_prices/index_daily/market_context_daily/corporate_actions/stocks/
weekly_classification/trigger_evaluation_log/entry_params/signal_performance)
의 한 줄 친절 설명 + fold 안 컬럼 요약 + primary key. 근거: schema.sql.
초보 친화 페이지 리팩토링의 첫 데이터 source."
```

---

### Task 2: 18 entry_params 필드 풀이 데이터 파일

**Files:**
- Create: `web/src/data/llm-pipeline/entry-params-fields.ts`

**근거 source**: `prompts/calculate_entry_params_v2_0.md` §10 validation 표 (line ~470-490).

- [ ] **Step 1: validation 표 정확 확인**

```bash
sed -n '/^## 10/,/^## 11/p' prompts/calculate_entry_params_v2_0.md | grep -E "^\| \`"
```

기대: 18 행 출력 (entry_mode, pivot_price, trigger_price, current_price, stop_loss_price, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, suggested_weight_pct, expected_target_price, expected_target_pct, pattern_basis, entry_window_days, max_chase_pct_from_pivot, breakout_volume_requirement, observed_breakout_volume_ratio, notes, known_warnings, other_warnings).

만약 행 수가 다르면 plan stop — spec 의 *18* 수치 재검토.

- [ ] **Step 2: `web/src/data/llm-pipeline/entry-params-fields.ts` 작성**

```ts
// entry_params 18 필드 풀이 — 카테고리별 그룹화
// 근거: prompts/calculate_entry_params_v2_0.md §10 validation 표
// 사용자 지적 "17 필드" 는 stale — 실제 18 필드.

export interface EntryParamField {
  name: string;
  category: "entry" | "stop" | "target" | "sizing" | "guard" | "meta";
  what: string;       // 한 줄 친절 설명 (이 필드가 무엇인지)
  constraint: string; // validation 룰 요약 (전문가 참고)
}

export const ENTRY_PARAMS_FIELDS: EntryParamField[] = [
  // Entry 진입 (4)
  { name: "entry_mode", category: "entry", what: "표준 돌파 매수(pivot_breakout) 또는 포켓 피벗(pocket_pivot) 중 하나.", constraint: "exactly one of: pivot_breakout, pocket_pivot" },
  { name: "pivot_price", category: "entry", what: "책에서 권하는 매수 기준가 — base 의 핵심 돌파선.", constraint: "> 0" },
  { name: "trigger_price", category: "entry", what: "실제 매수가 활성화되는 정확한 가격 — pivot 보다 약간 위 (1.001×).", constraint: "> pivot_price; ≤ pivot_price × 1.005" },
  { name: "current_price", category: "entry", what: "시그널 발생 시점의 종가 — pivot 까지 거리 비교용.", constraint: "> 0" },

  // Stop 손절 (3)
  { name: "stop_loss_price", category: "stop", what: "손절선 절대 가격 — 이 가격 닿으면 즉시 매도.", constraint: "> 0; strictly < pivot_price × 0.999" },
  { name: "stop_loss_pct_from_pivot", category: "stop", what: "pivot 대비 손절 % — O'Neil 의 7-8% 룰 적용.", constraint: "standard: −10.0 ~ −5.0%; pocket_pivot: −8.0 ~ −4.0%" },
  { name: "stop_loss_pct_from_current_price", category: "stop", what: "현재가 대비 손절 % — 추격 매수 위험 평가용.", constraint: "−15.0 ~ −3.0%" },

  // Target 목표 (2)
  { name: "expected_target_price", category: "target", what: "1차 목표가 — 부분 익절 후보 가격.", constraint: "strictly > pivot_price × 1.001" },
  { name: "expected_target_pct", category: "target", what: "pivot 대비 목표 % — O'Neil 20-30% 1차 익절 룰 적용.", constraint: "15.0 ~ 50.0%" },

  // Sizing 포지션 (1)
  { name: "suggested_weight_pct", category: "sizing", what: "포트폴리오 내 권장 비중 % — Minervini 의 거래당 1-3% 위험 룰 적용.", constraint: "3.0 ~ 25.0%" },

  // Guard 매수 가드 (3)
  { name: "pattern_basis", category: "guard", what: "이 매수가 어떤 base 패턴에 기반했는지 (flat_base / cup_with_handle / vcp / double_bottom / 3c_cheat).", constraint: "exactly one of: flat_base, cup_with_handle, vcp, double_bottom, 3c_cheat" },
  { name: "entry_window_days", category: "guard", what: "트리거 발생 후 며칠 안에 진입해야 유효한가 (1~5 일).", constraint: "integer, 1 ~ 5" },
  { name: "max_chase_pct_from_pivot", category: "guard", what: "pivot 위로 최대 몇 %까지 추격 매수 허용 (O'Neil: ≤5%).", constraint: "0.0 ~ 5.0%" },

  // Volume 거래량 (2)
  { name: "breakout_volume_requirement", category: "guard", what: "돌파일 거래량 요건 (1.4× / 1.5× 50일평균 / pocket pivot signature).", constraint: "exactly one of: ge_1.3x_50day_avg, ge_1.4x_50day_avg, ge_1.5x_50day_avg, pocket_pivot_signature" },
  { name: "observed_breakout_volume_ratio", category: "guard", what: "실제 관측된 거래량 비율 — null 또는 0.0-20.0× 사이.", constraint: "null OR 0.0 ~ 20.0" },

  // Meta 메타 (3)
  { name: "notes", category: "meta", what: "사람이 읽는 매수 노트 — entry_mode, 손절 기준, 사이징, 경고 등 종합 설명.", constraint: "50~600 글자, 필수 항목 (entry_mode, stop binding rule, sizing tier, both stop_pct, warnings) 모두 언급" },
  { name: "known_warnings", category: "meta", what: "정의된 경고 코드 목록 (whitelist 16종) — 예: 'breakout_volume_below_preferred_50pct'.", constraint: "array from §8.1 whitelist (16 codes); no duplicates" },
  { name: "other_warnings", category: "meta", what: "정의 외 자유 텍스트 경고 — LLM 의 추가 관찰 사항.", constraint: "array of free-text strings; each 5~200 chars" },
];

export const FIELD_CATEGORIES: Record<EntryParamField["category"], { label: string; emoji: string }> = {
  entry: { label: "진입 가격", emoji: "🎯" },
  stop: { label: "손절", emoji: "🛑" },
  target: { label: "목표가", emoji: "🏁" },
  sizing: { label: "포지션 사이즈", emoji: "📏" },
  guard: { label: "매수 가드", emoji: "🛡️" },
  meta: { label: "기록·경고", emoji: "📝" },
};
```

- [ ] **Step 3: tsc 무결성 + commit**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -3
cd /Users/hank.es/git/personal/kr-by-claude
git add web/src/data/llm-pipeline/entry-params-fields.ts
git commit -m "feat(llm-pipeline data): 18 entry_params 필드 풀이 source

calculate_entry_params_v2_0.md §10 validation 표 기반 18 필드의 카테고리·친절
설명·constraint. 6 카테고리 (entry/stop/target/sizing/guard/meta) 로 그룹화.
사용자 지적 '17 필드' 는 stale — 본 source 가 실제 18 로 정합화."
```

---

### Task 3: 공통 컴포넌트 — `ListFold` + `TableExplainerList`

**Files:**
- Create: `web/src/pages/llm-pipeline/ListFold.tsx`
- Create: `web/src/pages/llm-pipeline/TableExplainerList.tsx`

- [ ] **Step 1: `ListFold.tsx` 작성**

```tsx
import type { ReactNode } from "react";

interface Props {
  label: string;       // 예: "Trend Template 8 조건 모두 보기"
  count?: number;       // 옵션 — 라벨 옆 카운트 chip
  variant?: "default" | "subtle"; // subtle = 더 작은 톤
  children: ReactNode;
}

/**
 * 'X 항목 모두 보기 ▼' 공통 fold 래퍼.
 * 기존 안내 박스의 <details> 패턴을 카드 내부용으로 축소.
 */
export function ListFold({ label, count, variant = "default", children }: Props) {
  const summaryBg = variant === "subtle"
    ? "bg-cream hover:bg-tint-stone"
    : "bg-tint-stone hover:bg-cream";
  return (
    <details className="mt-2 group">
      <summary className={`cursor-pointer select-none px-3 py-2 ${summaryBg} border border-hairline rounded-lg text-data-xs text-ink font-semibold transition-colors list-none flex items-center justify-between`}>
        <span>
          {label}
          {count != null && (
            <span className="ml-2 num text-faint font-normal">({count})</span>
          )}
        </span>
        <span className="text-faint font-normal group-open:hidden">▼</span>
        <span className="text-faint font-normal hidden group-open:inline">▲</span>
      </summary>
      <div className="mt-2 px-3 py-3 bg-cream border border-hairline rounded-lg text-data-xs text-muted leading-relaxed">
        {children}
      </div>
    </details>
  );
}
```

- [ ] **Step 2: `TableExplainerList.tsx` 작성**

```tsx
import { TABLES } from "../../data/llm-pipeline/tables";
import { ListFold } from "./ListFold";

interface Props {
  names: string[];     // 표시할 테이블 이름들 (예: ["daily_indicators", "stocks"])
  label: string;       // 예: "입력 테이블" or "출력 테이블"
}

/**
 * 카드 안 입출력 테이블을 '칩 + 한 줄 친절 설명' 으로 표시.
 * 각 테이블은 ListFold (subtle) 로 컬럼 상세 확장 가능.
 */
export function TableExplainerList({ names, label }: Props) {
  return (
    <div>
      <div className="caps text-faint mb-2">{label}</div>
      <ul className="space-y-2">
        {names.map((name) => {
          const t = TABLES[name];
          if (!t) {
            return (
              <li key={name} className="text-data-xs text-faint">
                <span className="num bg-tint-stone text-muted px-2 py-0.5 rounded">{name}</span>
                {" "}(설명 없음 — tables.ts 추가 필요)
              </li>
            );
          }
          return (
            <li key={name} className="text-data-xs">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="num bg-tint-stone text-muted px-2 py-0.5 rounded shrink-0">
                  {t.name}
                </span>
                <span className="text-data text-ink">{t.short}</span>
              </div>
              <ListFold
                label="컬럼 상세 보기"
                variant="subtle"
              >
                <div className="space-y-1">
                  <div>{t.details}</div>
                  <div className="text-faint">
                    Primary key: <span className="num">{t.pkey}</span>
                  </div>
                </div>
              </ListFold>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: tsc 무결성 + commit**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -3
cd /Users/hank.es/git/personal/kr-by-claude
git add web/src/pages/llm-pipeline/ListFold.tsx web/src/pages/llm-pipeline/TableExplainerList.tsx
git commit -m "feat(llm-pipeline): 공통 컴포넌트 ListFold + TableExplainerList

ListFold: 'X 항목 모두 보기 ▼' 공통 fold 래퍼. variant 'subtle' (카드 내부용)
지원. native <details> 사용 (React state 불요).

TableExplainerList: 카드 안 입출력 테이블을 '칩 + 한 줄 친절 설명' + 컬럼
상세 fold 로 표시. tables.ts 의 11 테이블 정의 import."
```

---

### Task 4: `StageCard` 컴포넌트 재설계

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx` (`StageCard` 함수 + 관련 칩 컴포넌트)

기존 `StageCard` 가 5개 단계 모두 동일 JSX 로 렌더링 → 본 task 에서 *fold 다수 + 친절 본문* 구조로 재설계. **데이터 구조 (`PipelineStage` interface) 도 fold 콘텐츠를 담을 수 있게 확장**.

- [ ] **Step 1: `PipelineStage` interface 확장**

`web/src/pages/LlmPipelinePage.tsx` 의 기존 interface 를 다음으로 교체:

```ts
import { TABLES } from "../data/llm-pipeline/tables";
import { ENTRY_PARAMS_FIELDS, FIELD_CATEGORIES } from "../data/llm-pipeline/entry-params-fields";
import { CONDITIONS as TT_CONDITIONS } from "../data/llm-pipeline-audit/minervini"; // verify import name in Step 2
import { BASE_PATTERNS } from "../data/llm-pipeline-audit/base-patterns";
import { RISK_FLAGS } from "../data/llm-pipeline-audit/risk-flags";
import { ZIP_FILES } from "../data/llm-pipeline-audit/zip-files";
import { ListFold } from "./llm-pipeline/ListFold";
import { TableExplainerList } from "./llm-pipeline/TableExplainerList";

interface PipelineStage {
  id: string;
  order: number;
  label: string;
  // 친절 본문 (한 단락) — 이 단계가 무엇을 왜 하는가
  intro: string;
  // 결정론 룰 친절 풀이
  deterministicSummary: string;
  deterministicDetail?: string; // fold 안 SQL/정확 조건
  // LLM 로직 친절 풀이
  llmSummary: string | null;     // null = 이 단계 LLM 미사용
  llmShowsLists?: {
    eightConditions?: boolean;  // Trend Template 8 조건 fold
    nineBasePatterns?: boolean;
    thirteenRiskFlags?: boolean;
    thirteenZipFiles?: boolean;
    eighteenFields?: boolean;
  };
  decisions?: string[];
  // 결과 액션
  actionSummary: string;
  actionDetail?: string;        // fold 안 SQL INSERT/UPSERT/digest 상세
  // 입출력 테이블
  inputs: string[];
  outputs: string[];
  // 책 근거 + 코드 참조 (기존 유지)
  sources: string[];
  codeRef: string;
}
```

- [ ] **Step 2: audit minervini.ts 의 export 이름 확인 후 조정**

```bash
grep -n "^export const\|^export interface" web/src/data/llm-pipeline-audit/minervini.ts
```

기대 출력 확인 후 Step 1 의 `import { CONDITIONS as TT_CONDITIONS }` 부분을 실제 export 이름과 일치시킴. 예를 들어 audit 가 `export const MINERVINI_CONDITIONS` 라면 그 이름으로 import.

- [ ] **Step 3: `StageCard` 컴포넌트 재작성**

기존 `StageCard` 함수 전체를 다음으로 교체:

```tsx
function StageCard({ stage }: { stage: PipelineStage }) {
  return (
    <section className="bento p-6 mb-4">
      {/* 헤더 */}
      <div className="flex items-center gap-3 mb-3">
        <span className="num text-data-xs text-faint shrink-0">{stage.order}</span>
        <span className="num text-data-xs bg-tint-violet text-accent px-2 py-0.5 rounded shrink-0">
          {stage.id}
        </span>
        <h3 className="text-subhead font-bold text-ink flex-1">{stage.label}</h3>
      </div>

      {/* 친절 본문 */}
      <p className="text-data text-muted mb-5 leading-relaxed">{stage.intro}</p>

      {/* 입출력 테이블 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
        <TableExplainerList names={stage.inputs} label="📥 입력 테이블" />
        <TableExplainerList names={stage.outputs} label="📤 출력 테이블" />
      </div>

      {/* 결정론 룰 */}
      <div className="mb-5">
        <div className="caps text-faint mb-1">⚙️ 결정론 룰</div>
        <p className="text-data text-ink leading-relaxed">{stage.deterministicSummary}</p>
        {stage.deterministicDetail && (
          <ListFold label="결정론 룰 SQL·상세 보기">
            <div className="whitespace-pre-wrap">{stage.deterministicDetail}</div>
          </ListFold>
        )}
        {stage.llmShowsLists?.eightConditions && (
          <ListFold label="Trend Template 8 조건 모두 보기" count={TT_CONDITIONS.length}>
            <ol className="space-y-2 list-decimal list-inside">
              {TT_CONDITIONS.map((c) => (
                <li key={c.id ?? c.label}>
                  <span className="text-ink font-semibold">{c.label}</span>
                  {c.description && <span className="text-muted"> — {c.description}</span>}
                </li>
              ))}
            </ol>
          </ListFold>
        )}
      </div>

      {/* AI (LLM) 로직 */}
      <div className="mb-5">
        <div className="caps text-faint mb-1">🧠 AI (LLM) 로직</div>
        {stage.llmSummary == null ? (
          <p className="text-data text-faint">이 단계는 AI 호출 없음 (순수 계산).</p>
        ) : (
          <>
            <p className="text-data text-ink leading-relaxed">{stage.llmSummary}</p>
            {stage.decisions && (
              <div className="flex flex-wrap gap-1 mt-2">
                {stage.decisions.map((d) => <DecisionChip key={d} value={d} />)}
              </div>
            )}
            {stage.llmShowsLists?.thirteenZipFiles && (
              <ListFold label="AI 가 받는 자료 — ZIP 13 파일 모두 보기" count={ZIP_FILES.length}>
                <ol className="space-y-2 list-decimal list-inside">
                  {ZIP_FILES.map((z) => (
                    <li key={z.num}>
                      <span className="num text-ink font-semibold">{z.filename}</span>
                      <span className="text-muted"> — {z.content}</span>
                    </li>
                  ))}
                </ol>
              </ListFold>
            )}
            {stage.llmShowsLists?.nineBasePatterns && (
              <ListFold label="AI 가 식별하는 9 base 패턴 모두 보기" count={BASE_PATTERNS.length}>
                <ul className="space-y-2">
                  {BASE_PATTERNS.map((p) => (
                    <li key={p.id}>
                      <span className="num text-ink font-semibold">{p.id}</span>
                      <span className="text-muted"> — {p.definition}</span>
                    </li>
                  ))}
                </ul>
              </ListFold>
            )}
            {stage.llmShowsLists?.thirteenRiskFlags && (
              <ListFold label="AI 가 사용하는 13 risk flag 모두 보기" count={RISK_FLAGS.length}>
                <ul className="space-y-2">
                  {RISK_FLAGS.map((r) => (
                    <li key={r.id}>
                      <span className="num text-ink font-semibold">{r.id}</span>
                      <span className="text-muted"> — {r.definition}</span>
                    </li>
                  ))}
                </ul>
              </ListFold>
            )}
            {stage.llmShowsLists?.eighteenFields && (
              <ListFold label="AI 가 채우는 매수 계획 18 필드 모두 보기" count={ENTRY_PARAMS_FIELDS.length}>
                <div className="space-y-3">
                  {(Object.keys(FIELD_CATEGORIES) as (keyof typeof FIELD_CATEGORIES)[]).map((cat) => {
                    const fields = ENTRY_PARAMS_FIELDS.filter((f) => f.category === cat);
                    if (fields.length === 0) return null;
                    return (
                      <div key={cat}>
                        <div className="text-ink font-semibold mb-1">
                          {FIELD_CATEGORIES[cat].emoji} {FIELD_CATEGORIES[cat].label} ({fields.length})
                        </div>
                        <ul className="space-y-1 pl-4">
                          {fields.map((f) => (
                            <li key={f.name}>
                              <span className="num text-ink">{f.name}</span>
                              <span className="text-muted"> — {f.what}</span>
                              <div className="text-faint text-data-xs ml-3">제약: {f.constraint}</div>
                            </li>
                          ))}
                        </ul>
                      </div>
                    );
                  })}
                </div>
              </ListFold>
            )}
          </>
        )}
      </div>

      {/* 결과 액션 */}
      <div className="mb-5">
        <div className="caps text-faint mb-1">✅ 결과 액션</div>
        <p className="text-data text-ink leading-relaxed">{stage.actionSummary}</p>
        {stage.actionDetail && (
          <ListFold label="SQL INSERT / 엔지니어링 상세 보기">
            <div className="whitespace-pre-wrap">{stage.actionDetail}</div>
          </ListFold>
        )}
      </div>

      {/* 책 근거 + 코드 참조 (기존 유지) */}
      {stage.sources.length > 0 && (
        <div className="mb-4">
          <div className="caps text-faint mb-1">📖 책 근거</div>
          <div className="flex flex-wrap gap-3">
            {stage.sources.map((s) => <SourceChip key={s} src={s} />)}
          </div>
        </div>
      )}

      <div className="pt-3 border-t border-hairline">
        <div className="caps text-faint mb-1">💻 코드 참조</div>
        <code className="num text-data-xs bg-cream px-2 py-1 rounded">{stage.codeRef}</code>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: tsc 무결성**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -5
```

기대: 0 error. 만약 `TT_CONDITIONS.label` / `BASE_PATTERNS[].id` / `RISK_FLAGS[].id` 타입 미일치하면 Step 2 의 import 이름·필드명 재확인 후 수정.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "refactor(StageCard): fold 다수 + 친절 본문 구조로 재설계

PipelineStage interface 확장 (intro/deterministicSummary/llmSummary/
actionSummary 등 친절 본문 + llmShowsLists 로 fold 카드별 활성화).
StageCard 가 native <details> targeted fold 다수 표시: 입출력 테이블 칩
+1줄 (TableExplainerList) / Trend Template 8 조건 / ZIP 13 / 9 base 패턴
/ 13 risk flag / 18 필드 / SQL 상세 — 모두 audit 데이터 source 직접 import
로 drift 차단. STAGES 데이터 자체는 다음 task 에서 친절 본문으로 재작성."
```

---

### Task 5: `STAGES` 데이터 친절 본문으로 재작성

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx` (`STAGES` 배열)

기존 `STAGES` 의 jargon-heavy summary/targets/deterministic/llm/actions 를 친절 본문 + (옵션) detail fold 콘텐츠로 분할. 5 stage 모두.

- [ ] **Step 1: 기존 `STAGES` 배열을 다음으로 교체**

```ts
const STAGES: PipelineStage[] = [
  // ─── Stage 0: 주말 batch ─────────────────────────────
  {
    id: "weekend",
    order: 0,
    label: "주말 batch — 매주 토 03:20 자동 전체 재분류",
    intro:
      "한 주에 한 번, 토요일 새벽 3시 20분에 자동 실행됩니다. 결정론 1차 필터를 통과한 *모든* 한국 종목을 AI(LLM)가 차트와 함께 재분석해서 entry / watch / ignore 중 하나로 분류합니다. 분류 결과는 weekly_classification 테이블에 새 행으로 쌓입니다 (이전 분류는 그대로 보존).",
    inputs: ["daily_indicators", "weekly_indicators", "market_context_daily", "corporate_actions", "stocks"],
    outputs: ["weekly_classification"],
    deterministicSummary:
      "AI 호출 전 1차 필터로 'Minervini Trend Template 8 조건' 을 통과한 종목만 선별합니다 (= minervini_pass 컬럼이 TRUE). 상장폐지된 종목 (stocks.delisted_at) 은 자동 제외.",
    deterministicDetail:
      "직전 금요일자 daily_indicators 행을 기준으로 minervini_pass=TRUE AND stocks.delisted_at IS NULL 조건의 종목 전체를 풀로 만듭니다. cron 시각은 토 03:20 KST.",
    llmSummary:
      "각 종목별로 13 개의 파일이 든 ZIP 묶음 (차트 PNG·일/주봉 OHLCV·시장 컨텍스트·corporate actions·minervini 진단 등) 을 만들어 AI 에게 보내고, analyze_chart_v3.md prompt 의 지시를 따라 'base 패턴 + risk flag + 분류' 를 받습니다. AI 는 9 종 base 패턴과 13 종 risk flag 만 사용하도록 제약돼 있습니다.",
    llmShowsLists: {
      eightConditions: true,
      thirteenZipFiles: true,
      nineBasePatterns: true,
      thirteenRiskFlags: true,
    },
    decisions: ["entry", "watch", "ignore"],
    actionSummary:
      "분류 결과를 weekly_classification 테이블에 *새 행* 으로 추가합니다 (이전 분류는 지우지 않고 누적). 같은 종목·같은 시각의 중복은 자동 무시. 분석이 끝나면 entry/watch/ignore 카운트를 Slack 으로 요약 알림 (digest).",
    actionDetail:
      "SQL 패턴: INSERT INTO weekly_classification (...) VALUES (...) ON CONFLICT (symbol, classified_at) DO NOTHING. '현재 분류' 를 조회할 땐 DISTINCT ON (symbol) ORDER BY classified_at DESC. 즉 append-only 설계 — UPDATE 하지 않고 새 행을 쌓고, 최신 행이 '현재 상태'.",
    sources: [
      "Minervini Trend Template (8 conditions)",
      "O'Neil HMM base patterns",
    ],
    codeRef: "kr_pipeline/llm_runner/weekend.py + modes.py:run_weekend",
  },

  // ─── Stage 1: 신규 후보 분류 ──────────────────────────
  {
    id: "daily_delta",
    order: 1,
    label: "신규 후보 분류 — 평일 매일 새 종목만",
    intro:
      "평일 매일 20:00 자동 실행됩니다. weekend 와 같은 AI prompt + 같은 ZIP 구조를 쓰지만, 대상이 다릅니다 — 결정론 필터를 *오늘 새로 통과한* 종목만. 즉 다음 주 토 weekend 까지 기다리지 않고 신규 후보를 즉시 분류해서 watch/entry 풀에 합류시키는 *빠른 반응* 단계입니다.",
    inputs: ["daily_indicators", "daily_prices", "weekly_indicators", "market_context_daily"],
    outputs: ["weekly_classification"],
    deterministicSummary:
      "1차 필터는 동일 — Trend Template 8 조건 통과 (minervini_pass=TRUE). 추가로 *신규성* 조건: 최근 7일 안에 분류된 적이 없는 종목만 (이미 weekend 나 다른 daily_delta 에서 분류된 종목은 제외).",
    deterministicDetail:
      "daily_indicators 의 오늘 행 기준 minervini_pass=TRUE + NOT EXISTS (SELECT 1 FROM weekly_classification WHERE symbol = ticker AND classified_at >= today - INTERVAL '7 days'). 7일 cool-down 으로 같은 종목 반복 분석 방지.",
    llmSummary:
      "weekend 와 정확히 같은 prompt (analyze_chart_v3.md) + 같은 ZIP 13 파일. 차이는 source 컬럼 ('daily_delta' vs 'weekend') 과 입력 풀의 신규성 필터.",
    llmShowsLists: {
      thirteenZipFiles: true,
      nineBasePatterns: true,
      thirteenRiskFlags: true,
    },
    decisions: ["entry", "watch", "ignore"],
    actionSummary:
      "weekly_classification 에 새 행으로 INSERT (source='daily_delta'). watch/entry 분류된 종목은 다음 평일부터 evaluate_pivot 의 평가 대상. ignore 분류된 종목은 7일 후 다시 신규 후보로 재진입 가능.",
    actionDetail:
      "INSERT INTO weekly_classification (..., source='daily_delta') VALUES (...) ON CONFLICT (symbol, classified_at) DO NOTHING. weekend 와 동일한 append-only.",
    sources: ["Minervini Trend Template", "O'Neil HMM 'How to Read Charts Like a Pro'"],
    codeRef: "kr_pipeline/llm_runner/daily_delta.py",
  },

  // ─── Stage 2: 평일 트리거 평가 ────────────────────────
  {
    id: "evaluate_pivot",
    order: 2,
    label: "평일 트리거 평가 — watch/entry 종목의 오늘 행동 점검",
    intro:
      "이미 watch 또는 entry 로 분류된 활성 종목들의 오늘 가격·거래량을 매일 점검합니다. 종가가 pivot 을 돌파했는지, 손절선을 깼는지, 50일 이동평균에서 이탈했는지 등을 *결정론 게이트* 가 먼저 검사해 이벤트 유형 (breakout / promotion / invalidation) 을 결정합니다. 이벤트가 잡힌 종목만 AI 에게 '진짜 신호인가 가짜 신호인가' 묻습니다.",
    inputs: ["weekly_classification", "daily_indicators"],
    outputs: ["trigger_evaluation_log"],
    deterministicSummary:
      `세 가지 트리거를 결정론 룰로 잡습니다 — ① 종가 > pivot AND 거래량 ≥ 평균 (${GATE_BREAKOUT_VOL_MULT.toFixed(1)}×) → breakout (돌파), ② 종가 ≥ pivot × 0.95 → promotion (돌파 직전 staging), ③ 종가 < 손절선 또는 종가 < SMA-50 → invalidation (base 무효화). 거래량 기준은 게이트의 1.0× = '거래량이 죽지 않은 정도만' 확인이고, 책 표준 1.4~1.5× 와 pocket pivot 예외는 AI 가 판단합니다.`,
    deterministicDetail:
      "compute/trigger_gate.py 의 룰: pivot_price IS NULL 인 종목은 skip. close < stop_loss OR close < sma_50 → invalidation 우선 적용. 그 외 close > pivot AND volume >= avg_volume_50d × GATE_BREAKOUT_VOL_MULT → breakout. promotion 은 watch 분류 종목에만, close >= pivot × 0.95 AND volume >= avg 일 때.",
    llmSummary:
      "evaluate_pivot_trigger_v1.md prompt — 게이트가 잡은 트리거 유형을 입력으로 받고 'go_now (지금 사라) / wait (기다려) / abort (가짜·무효)' 중 하나를 결정. *중요*: 이 단계는 분류 자체를 바꾸지 않습니다. abort 가 나와도 분류는 그대로 유지 — 다음 토 weekend 에서 AI 가 다시 보고 분류를 ignore 로 강등해야 비로소 강등.",
    decisions: ["go_now", "wait", "abort"],
    actionSummary:
      "결과를 trigger_evaluation_log 에 새 행으로 기록 (분류는 변경 안 함). decision='go_now' + trigger_type='breakout' 인 종목은 다음 단계 (entry_params) 가 자동으로 매수 계획을 작성합니다. promotion 트리거에서는 go_now 가 *나오지 않도록* prompt 와 코드 양쪽에 안전장치가 있습니다 (실질 매수는 종가가 pivot 위로 올라간 진짜 breakout 으로만).",
    actionDetail:
      "INSERT INTO trigger_evaluation_log (symbol, evaluated_at, trigger_type, decision, ...) VALUES (...). entry_params 다음 단계의 SQL 은 WHERE decision='go_now' AND trigger_type='breakout' 으로 staging 신호 분리.",
    sources: [
      "O'Neil HMM ch.2 Volume Percent Change (1.5× breakout)",
      "Minervini buy/sell rules",
    ],
    codeRef: "kr_pipeline/llm_runner/evaluate_pivot.py + compute/trigger_gate.py",
  },

  // ─── Stage 3: 매수 계획 ───────────────────────────────
  {
    id: "entry_params",
    order: 3,
    label: "매수 계획 (entry_params) — go_now 종목의 실제 매수 파라미터",
    intro:
      "evaluate_pivot 에서 go_now 결정을 받은 *진짜 매수 시그널* 종목에 대해 AI 가 18 개 필드의 매수 계획을 작성합니다. 진입 가격·손절선·목표가·포지션 사이즈·돌파 거래량 요건 등 매수에 필요한 모든 숫자를 한 행으로 정리. 이게 시스템의 *최종 산출물* 입니다 — 사용자는 entry_params 행을 보고 실제 매수 여부를 결정.",
    inputs: ["trigger_evaluation_log", "daily_indicators", "weekly_classification"],
    outputs: ["entry_params"],
    deterministicSummary:
      "오늘자 trigger_evaluation_log 에서 decision='go_now' AND trigger_type='breakout' 행만 추출 (promotion·invalidation·abort 는 entry_params 진입 차단).",
    deterministicDetail:
      "SELECT FROM trigger_evaluation_log WHERE evaluated_at::date = today AND decision='go_now' AND trigger_type='breakout'. 이 조건이 'watch staging' 이 매수로 새지 않게 막는 안전장치.",
    llmSummary:
      "calculate_entry_params_v2_0.md prompt — 18 필드를 책 룰 (O'Neil 7-8% 손절, Minervini 1-3% 거래당 위험, 5% chase 제한 등) 에 맞춰 계산. entry_mode 가 pivot_breakout 인지 pocket_pivot 인지에 따라 손절·사이징 룰이 다릅니다.",
    llmShowsLists: {
      eighteenFields: true,
    },
    actionSummary:
      "entry_params 테이블에 새 행으로 INSERT (PK: symbol + signal_at). 이 행이 곧 '활성 매수 시그널'. performance 단계가 자동으로 이 시그널의 1주·2주·4주·8주 후 가격을 추적합니다.",
    actionDetail:
      "INSERT INTO entry_params (symbol, signal_at, entry_mode, pivot_price, ..., notes, known_warnings, other_warnings) VALUES (...). PK 충돌 (같은 종목·같은 시각) 은 거의 없으나 안전장치로 ON CONFLICT DO NOTHING.",
    sources: ["Minervini risk management (1-3% per trade)", "O'Neil HMM 'Buy at the Buy Point'"],
    codeRef: "kr_pipeline/llm_runner/entry_params.py",
  },

  // ─── Stage 4: 성과 추적 ───────────────────────────────
  {
    id: "performance",
    order: 4,
    label: "성과 추적 — 시그널의 1주/2주/4주/8주 후 수익률",
    intro:
      "AI 호출 없는 순수 계산 단계입니다. 최근 90일 안에 발생한 매수 시그널 (entry_params) 들의 1주·2주·4주·8주 후 가격을 daily_prices 에서 조회해 수익률을 계산. 같은 기간의 시장 (KOSPI 또는 KOSDAQ) 수익률도 함께 기록해 *시장 대비 알파* 도 측정. 8주 데이터가 모두 채워지면 추적이 사실상 끝납니다.",
    inputs: ["entry_params", "daily_prices", "index_daily"],
    outputs: ["signal_performance"],
    deterministicSummary:
      "entry_params 의 signal_at 가 최근 90일 안인 행에 대해 +7 / +14 / +28 / +56 일 후 종가를 조회. 90일 cutoff 는 8주 추적 + 안전 마진.",
    deterministicDetail:
      "SELECT FROM entry_params WHERE signal_at >= today - 90 days. 각 행에 대해 daily_prices 에서 +7d/+14d/+28d/+56d close 조회. 같은 시점의 index_daily (해당 시장의 지수) 종가도 조회해 시장 대비 차이 계산.",
    llmSummary: null,
    actionSummary:
      "signal_performance 테이블에 (symbol, signal_at) 키로 UPSERT. 같은 종목의 여러 시그널은 signal_at 별로 독립 추적 — 같은 종목이 한 달 사이 두 번 entry_params 를 받았다면 두 시그널 각각 추적.",
    actionDetail:
      "INSERT INTO signal_performance (symbol, signal_at, price_1w, price_2w, price_4w, price_8w, market_return_1w, ...) VALUES (...) ON CONFLICT (symbol, signal_at) DO UPDATE SET ... — 점진적으로 데이터가 채워지므로 UPSERT.",
    sources: [],
    codeRef: "kr_pipeline/llm_runner/performance.py",
  },
];
```

- [ ] **Step 2: tsc 무결성**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -5
```

기대: 0 error. 만약 audit data 의 export 이름·필드명 미일치하면 Task 4 Step 2 결과로 가서 import 이름 조정.

- [ ] **Step 3: 시각 검증**

```bash
cd web && npm run dev
```

브라우저에서 `/docs/llm-pipeline` 진입 → 5 카드 모두 친절 본문 + fold 정상 펼침 + 데이터 정상 표시 확인. Mermaid / matrix / glossary / FAQ 는 다음 task 에서 갱신 — 지금은 *기존* 콘텐츠로 그대로 보임.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "feat(STAGES): 5 stage 친절 본문으로 재작성

각 stage 의 intro / deterministicSummary / llmSummary / actionSummary 를
주식 1~3년차 초보 청자 (analyze_chart_v3.md:305 정합) 가 이해할 수 있게
친절화. SQL/엔지니어링 상세는 *Detail* 필드로 분리해 fold 안에서만 노출.
weekend 카드에 8조건/ZIP13/9패턴/13risk 4개 fold 활성화. entry_params
카드에 18필드 fold 활성화. 사용자 지적 3 케이스 (결정론 필터 / ZIP 13 /
weekly_classification INSERT) 모두 fold 펼치지 않고도 의미 잡힘."
```

---

### Task 6: `TRIGGER_DECISION_MATRIX` 친절 논조 재작성

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx` (`TRIGGER_DECISION_MATRIX` 상수 + `TriggerDecisionMatrix` 컴포넌트 소개 단락)

- [ ] **Step 1: `TRIGGER_DECISION_MATRIX` 상수 교체**

```ts
const TRIGGER_DECISION_MATRIX: Record<string, Record<string, MatrixCell | null>> = {
  breakout: {
    go_now: {
      meaning: "종가가 pivot 을 돌파하고 거래량도 살아있음. AI 가 '진짜 돌파' 로 확인.",
      next: "→ 매수 계획 (entry_params) 자동 생성. 사용자가 행을 보고 실제 매수 결정.",
    },
    wait: {
      meaning: "돌파했지만 AI 가 보류 — 약한 신호 (예: 거래량이 1.4× 미만, base 가 약간 wide) 일 가능성.",
      next: "→ 매수 계획 생성 안 됨. 다음 평일에 재평가. entry 분류는 그대로 유지.",
    },
    abort: {
      meaning: "돌파처럼 보였으나 AI 가 가짜로 판정 — 예: 다음날 즉시 되돌림 우려 / 시장 약세 중복.",
      next: "→ 매수 계획 안 만듦. 분류 자체는 entry 유지. 다음 토 weekend 의 재분석이 base 무효 판단 시 비로소 ignore 강등.",
    },
  },
  promotion: {
    go_now: null,  // 시스템 안전장치 — promotion 에서 go_now 발생 금지
    wait: {
      meaning: "watch 종목이 pivot 의 95% 까지 도달 — 돌파 직전 staging 상태. 거래량은 평균 이상. close 는 아직 pivot 미만이라 매수 신호 아님.",
      next: "→ 다음 평일에 게이트가 다시 평가. 종가가 pivot 위로 올라가면 별도 breakout 트리거로 처리.",
    },
    abort: {
      meaning: "base 가 깨질 조짐 — SMA-50 이탈, distribution day 누적 등. AI 가 위험 신호로 판단.",
      next: "→ watch 분류 유지 (분류 변경 안 함). 다음 토 weekend 에서 ignore 로 강등될 후보.",
    },
  },
  invalidation: {
    go_now: null,
    wait: null,
    abort: {
      meaning: "base 가 무효화 — 종가가 손절선 또는 SMA-50 아래로 이탈. AI 호출 없이 결정론으로 abort 확정.",
      next: "→ 분류는 entry/watch 그대로 유지하지만, 다음 weekend 또는 daily_delta 재분류 까지 평가 사이클에서 사실상 제외.",
    },
  },
};
```

- [ ] **Step 2: `TriggerDecisionMatrix` 컴포넌트 소개 단락 친절화**

기존 컴포넌트 본문의 소개 `<p>` 를 다음으로 교체:

```tsx
<p className="text-data-xs text-muted mb-4 leading-relaxed">
  evaluate_pivot 단계에서 무슨 일이 일어나는지 한눈에 보는 표입니다.
  세로축은 결정론 게이트가 잡은 *오늘의 이벤트* — <span className="num text-ink">breakout</span> (돌파),{" "}
  <span className="num text-ink">promotion</span> (돌파 직전 staging),{" "}
  <span className="num text-ink">invalidation</span> (base 무효화).
  가로축은 그 이벤트에 대해 AI 가 내린 결정 — <span className="num text-ink">go_now</span> (지금 사라),{" "}
  <span className="num text-ink">wait</span> (기다려),{" "}
  <span className="num text-ink">abort</span> (가짜·무효).
  9 칸 중 *적용 안 됨* 4 칸은 시스템 안전장치 (promotion·invalidation 에서 매수 시그널 직행 차단).
</p>
```

- [ ] **Step 3: tsc + commit**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -3
cd /Users/hank.es/git/personal/kr-by-claude
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "refactor(TriggerDecisionMatrix): 셀 본문 친절 논조 + 일상어 풀이

매트릭스 6 jargon (breakout/promotion/invalidation × go_now/wait/abort) 를
한 줄 의미 + 결과 행동으로 재작성. 9 칸 중 4 빈 칸이 *시스템 안전장치*
임을 소개 단락에서 명시 (promotion·invalidation 에서 go_now 차단)."
```

---

### Task 7: Mermaid 다이어그램 친절화 — `DIAGRAM_DATA_FLOW` + `DIAGRAM_STATE`

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx`

- [ ] **Step 1: `DIAGRAM_DATA_FLOW` 노드명 한국어 친절화**

```ts
const DIAGRAM_DATA_FLOW = `graph LR
    W["주말 batch<br/>(토 03:20)<br/>결정론 통과 전체 재분류"] -->|새 행 추가| B[("분류 결과 테이블<br/>weekly_classification<br/>watch / entry / ignore")]
    A["평일 신규 분류<br/>(daily_delta)<br/>오늘 새로 통과한 종목만"] -->|새 행 추가| B
    B -->|매일 활성 종목 선별<br/>(최신 분류만)| C{"평일 트리거 평가<br/>(결정론 게이트)"}
    C -->|돌파 / 직전 staging<br/>/ base 무효| D["AI 평가"]
    D -->|go_now / wait / abort| E[("트리거 평가 로그<br/>trigger_evaluation_log")]
    E -->|go_now + 진짜 돌파<br/>(staging 차단 안전장치)| F["매수 계획 작성<br/>(AI 호출)"]
    F --> G[("매수 계획 테이블<br/>entry_params<br/>18 필드 매수 시그널")]
    G -->|매일 자동| H["성과 추적<br/>1주·2주·4주·8주 후"]
    H --> I[("성과 테이블<br/>signal_performance")]
`;
```

- [ ] **Step 2: `DIAGRAM_STATE` 노드명·라벨 친절화**

```ts
const DIAGRAM_STATE = `stateDiagram-v2
    [*] --> 후보전: 결정론 8조건 통과
    후보전 --> Watch: 주말/평일 AI 분류 → watch
    후보전 --> Entry: 주말/평일 AI 분류 → entry
    후보전 --> Ignore: 주말/평일 AI 분류 → ignore
    Watch --> Watch: 평일 평가 wait/abort (분류 유지)
    Watch --> Entry: 다음 주말 재분석 시 승격
    Entry --> Entry: 평일 평가 wait/abort (분류 유지)
    Entry --> 매수계획: 진짜 돌파 + go_now
    Entry --> Ignore: 다음 주말 재분석 시 강등
    매수계획 --> 성과추적: 자동 시작
    성과추적 --> [*]: 시그널 발생 90일 후 종료
    Ignore --> [*]: 7일 후 다시 신규 후보 가능
`;
```

- [ ] **Step 3: 개요 / 상태 섹션의 소개 단락 — "이 그림 읽는 법" 추가**

기존 *"개요 — 4 단계 데이터 흐름"* 섹션 본문 교체:

```tsx
<section className="bento p-6 mb-4">
  <h3 className="text-subhead font-bold text-ink mb-3">개요 — 자동 흐름 한눈에</h3>
  <p className="text-data-xs text-muted mb-3 leading-relaxed">
    한 종목이 새로 결정론 8조건을 통과한 순간부터 *매수 시그널 생성 + 8주 성과 추적* 까지의 자동 흐름.
    평일 20:00 cron 이 4 단계를 순차 실행 (신규 분류 → 평일 평가 → 매수 계획 → 성과 추적), 매주 토 03:20 에는 전체 재분류 (weekend batch) 가 한 번 더.
  </p>
  <details className="mb-3">
    <summary className="cursor-pointer text-data-xs text-ink font-semibold select-none list-none">
      <span className="group-open:hidden">📖 이 그림 읽는 법 ▼</span>
      <span className="hidden group-open:inline">📖 이 그림 읽는 법 ▲</span>
    </summary>
    <div className="mt-2 text-data-xs text-muted leading-relaxed">
      <ul className="list-disc list-inside space-y-1">
        <li>**둥근 사각형** 은 *처리 단계* (cron 또는 AI 호출). 화살표 라벨은 *조건/트리거*.</li>
        <li>**원통형** 은 *데이터 테이블* (DB 에 저장되는 결과).</li>
        <li>**다이아몬드** 는 *결정론 게이트* (코드 룰로 분기).</li>
        <li>전체 흐름은 왼쪽 → 오른쪽. 같은 테이블에 여러 단계가 행을 추가할 수 있음 (예: 분류 테이블 ← 주말 + 평일).</li>
      </ul>
    </div>
  </details>
  <MermaidDiagram chart={DIAGRAM_DATA_FLOW} idPrefix="flow" />
</section>
```

기존 *"종목 상태 전이도"* 섹션 본문도 같은 패턴으로 교체:

```tsx
<section className="bento p-6 mb-4">
  <h3 className="text-subhead font-bold text-ink mb-3">종목 상태 전이도</h3>
  <p className="text-data-xs text-muted mb-3 leading-relaxed">
    한 종목이 시스템 안에서 *어떤 상태* (분류) 로 시작해 어떻게 변하는지. 분류 자체는 잘 안 바뀌고
    (평일 평가는 분류 변경 안 함), *매수 계획 테이블 (entry_params) 에 행이 생기는 순간* 이 실질
    매수 시그널 활성을 의미합니다.
  </p>
  <details className="mb-3">
    <summary className="cursor-pointer text-data-xs text-ink font-semibold select-none list-none">
      <span className="group-open:hidden">📖 이 그림 읽는 법 ▼</span>
      <span className="hidden group-open:inline">📖 이 그림 읽는 법 ▲</span>
    </summary>
    <div className="mt-2 text-data-xs text-muted leading-relaxed">
      <ul className="list-disc list-inside space-y-1">
        <li>각 박스는 *상태* (분류 또는 활성). 화살표 라벨은 *전이 조건* (어떤 사건으로 상태가 바뀌나).</li>
        <li>Self-loop (자기로 돌아가는 화살표) 는 *상태 유지* — 예: Entry → Entry (평일 평가에서 wait/abort 나와도 entry 분류 유지).</li>
        <li>[*] 는 시스템 진입/종료 — 결정론 8조건 통과 시 진입, 90일 후 (성과 추적 종료) 또는 7일 후 (Ignore 재진입 가능) 종료.</li>
      </ul>
    </div>
  </details>
  <MermaidDiagram chart={DIAGRAM_STATE} idPrefix="state" />
</section>
```

- [ ] **Step 4: tsc + 시각 검증 + commit**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -3
# 브라우저에서 mermaid 정상 렌더 확인
cd /Users/hank.es/git/personal/kr-by-claude
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "refactor(mermaid): 두 다이어그램 노드명 한국어 친절화 + 그림 읽는 법

DIAGRAM_DATA_FLOW: 영문 테이블명/단계명을 한국어 친절 라벨로 (weekly_class
ification → '분류 결과 테이블', trigger_evaluation_log → '트리거 평가 로그'
등). 영문 원명은 부제로 병기.

DIAGRAM_STATE: 상태명 일부 한국어화 (후보전 / 매수계획 / 성과추적). 라벨도
친절체.

개요·상태 섹션에 '이 그림 읽는 법' fold 추가 — 둥근사각형/원통형/다이아몬드의
의미·self-loop·[*] 시작·종료 설명."
```

---

### Task 8: `GLOSSARY` 30+ 용어로 확장

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx` (`GLOSSARY` 상수)

기존 12 → 30+ 종. 테이블/SQL 은 카드 fold 소관이라 제외, *주식·책·시스템 일반* 용어 중심.

- [ ] **Step 1: `GLOSSARY` 상수 교체**

```ts
const GLOSSARY: { term: string; meaning: string }[] = [
  // ─── 분류·시그널 차원 (현 분류 ↔ 활성 매수 시그널 구분) ───
  { term: "classification", meaning: "AI 의 종목 정성 분류 — entry / watch / ignore 중 하나. weekly_classification.classification 컬럼. 자주 안 바뀜 (주 1회 weekend 또는 평일 신규 분류 시에만)." },
  { term: "signal (매수 시그널)", meaning: "entry_params 테이블의 새 행 — 실질 매수 활성 여부. classification 과 별개 차원 — 분류는 'AI 가 보기에 좋은 종목인가', 시그널은 '지금 이 가격에 사도 되나'." },
  { term: "현재 분류", meaning: "weekly_classification 의 한 종목의 가장 최근 행. SQL: DISTINCT ON (symbol) ORDER BY classified_at DESC. UPDATE 하지 않고 새 행 누적." },
  { term: "분류 변경", meaning: "weekly_classification 에 새 행이 추가되어 '현재 분류' 가 바뀌는 것. weekend 또는 daily_delta 만 변경 가능. 평일 트리거 평가 (evaluate_pivot) 는 분류 변경 안 함." },

  // ─── 책 용어 — 패턴·매수 기준 ───
  { term: "Trend Template (8조건)", meaning: "Minervini *TLSMW Ch.5* 의 강세 종목 식별 8 기준. 가격이 SMA-50/150/200 위, SMA 정렬, 200일선 상승 추세, 52주 고점 25% 이내, 52주 저점 25% 이상, RS Rating ≥70 등. 시스템의 1차 결정론 필터." },
  { term: "RS Rating", meaning: "Relative Strength Rating (상대 강도). 전체 종목 대비 가격 상승률의 백분위 (0-99). 70 이상이 책 기준 (Minervini), 80+ 가 O'Neil 선호. 같은 종목 풀 안에서의 *상대* 측정." },
  { term: "base (베이스)", meaning: "주가가 옆으로 정리되는 구간 — 컵·평평한 박스·VCP·이중바닥 등 9 종. 돌파 전의 매수 준비 단계." },
  { term: "pivot (피벗)", meaning: "책에서 권하는 *정확한 매수 기준가*. 패턴별로 다르게 정의 — cup_with_handle 은 손잡이 고점, flat_base 는 범위 상단 등." },
  { term: "breakout (돌파)", meaning: "종가가 pivot 위로 올라간 사건. 거래량 동반이면 진짜 돌파, 아니면 가짜 돌파 가능성." },
  { term: "pocket pivot (포켓 피벗)", meaning: "Morales/Kacher *TLOND Ch.5* 의 *조기 매수 신호*. base 안에서 거래량이 직전 10일 중 하락일 최대 거래량을 초과 + 종가가 SMA-50 위. 표준 pivot 돌파 *전* 의 매수 기회." },
  { term: "3c_cheat (cheat 진입)", meaning: "Minervini *TLSMW Ch.10* 의 *cup 형성 중 조기 매수 지점* — cup 아랫쪽 1/3 또는 가운데 1/3 의 small pause. 표준 handle 보다 일찍 진입." },
  { term: "VCP (Volatility Contraction Pattern)", meaning: "Minervini 의 핵심 패턴 — 연속된 *수축* (각 수축이 직전의 약 절반) + 거래량 동반 수축, 2-6 회 (보통 2-4)." },

  // ─── 시장 컨텍스트 용어 ───
  { term: "distribution day", meaning: "*기관 매도일* — 시장 지수 종가 ≥0.2% 하락 + 거래량이 전일보다 증가. 25 세션 내 5+ 누적이면 시장 약세 경고. 시장 distribution 과 종목 distribution 은 별개 (종목은 -0.2% + 1.0× 50일평균)." },
  { term: "follow-through day (FTD)", meaning: "조정 끝 강세 전환 확인 신호 — 저점 후 3-15일째 (최적 4-7일) 의 시장 지수가 +1.4% 이상 상승 + 전일 대비 거래량 증가. confirmed_uptrend 진입의 필수 조건." },
  { term: "confirmed_uptrend / correction / downtrend / rally_attempt", meaning: "시장 4-enum 상태. market_context_daily.current_status. uptrend = 매수 적기, correction/downtrend = 매수 자제, rally_attempt = FTD 대기." },
  { term: "Stage 2", meaning: "Minervini 의 종목 사이클 4 단계 중 *기관 누적 + 상승* 구간. 매수 적기. Stage 1=base, Stage 3=배포/정점, Stage 4=하락." },

  // ─── 트리거 / 결정 / 사이징 ───
  { term: "trigger (트리거)", meaning: "결정론 게이트가 감지한 *오늘의 이벤트* — breakout / promotion / invalidation 셋 중 하나." },
  { term: "decision (AI 결정)", meaning: "evaluate_pivot 의 LLM 응답 — go_now (지금 사라) / wait (기다려) / abort (가짜·무효) 셋 중 하나. 트리거 + 결정 9 조합 매트릭스." },
  { term: "go_now / wait / abort", meaning: "AI 의 트리거 대응 결정 3종. go_now 만이 매수 계획 생성으로 연결. 단 promotion·invalidation 에선 go_now 차단 (안전장치)." },
  { term: "entry / watch / ignore", meaning: "AI 의 분류 3종. entry = 매수 적합, watch = 베이스 형성 중 (돌파 대기), ignore = 부적합 (pattern·market·risk 사유)." },
  { term: "stop loss (손절선)", meaning: "이 가격 아래로 종가가 떨어지면 즉시 매도하는 안전 장치. O'Neil 룰: pivot 대비 -7~-8% 절대 한계 / Minervini 룰: 기대 수익의 절반." },
  { term: "risk-reward (RR)", meaning: "기대 수익 ÷ 손실 한도 비율. 예: 손절 -5%, 목표 +20% → RR = 4.0. 일반적으로 ≥3.0 권장." },

  // ─── 시스템 용어 ───
  { term: "결정론 게이트 (deterministic gate)", meaning: "AI 호출 *전* 의 코드 룰 1차 필터. 단순 SQL/계산으로 종목을 거름. AI 호출 비용을 줄이고 잡음 차단." },
  { term: "prompt", meaning: "AI 에게 주는 지시문 (markdown 파일). 본 시스템은 3 prompt 사용 — analyze_chart_v3 (분류), evaluate_pivot_trigger (트리거 평가), calculate_entry_params (매수 계획)." },
  { term: "ZIP 13 파일", meaning: "AI 가 종목 1건 분석 시 받는 자료 묶음 — 차트 PNG, 일/주봉 CSV, 시장 컨텍스트, corporate actions, minervini 진단 등 13 개 파일." },
  { term: "weekend batch", meaning: "토 03:20 cron 으로 실행되는 *전체 재분류* — 결정론 통과한 모든 종목을 AI 가 다시 평가. weekly_classification 에 source='weekend' 로 행 추가." },
  { term: "daily_delta", meaning: "평일 매일 *신규 후보만* AI 분류 — 최근 7일 안에 분류된 적 없는 새 종목. weekly_classification 에 source='daily_delta' 로 행 추가." },
  { term: "신규 종목 (7일 cool-down)", meaning: "결정론 통과 + 최근 7일 안에 분류 이력 없음. daily_delta 의 대상 조건. 같은 종목 반복 분석 방지 + ignore 후 재진입 허용." },
  { term: "append-only (추가만)", meaning: "DB 에 UPDATE 하지 않고 새 행만 추가하는 설계. 분류 이력 보존 + 시점별 추적 가능. '현재 상태' 는 가장 최근 행으로 조회." },
  { term: "cron", meaning: "정해진 시각에 자동 실행되는 작업 스케줄러 (Linux 표준). 본 시스템은 평일 20:00 (LLM 4 단계) + 토 03:20 (weekend) + 19:30 (데이터 적재) 등." },
  { term: "dry-run", meaning: "AI 호출은 mock 응답으로 대체 + DB INSERT 도 skip. 코드 흐름 검증용 read-only 모드." },
  { term: "Slack digest", meaning: "weekend batch 완료 후 entry/watch/ignore 카운트를 Slack 채널에 요약 알림. 사용자에게 *오늘 무슨 일이 있었나* 한눈에 보고." },
  { term: "OHLCV", meaning: "Open / High / Low / Close / Volume — 시·고·저·종가 + 거래량. 일봉/주봉 데이터의 표준 5 필드." },
  { term: "SMA (이동평균)", meaning: "Simple Moving Average — N일 평균 종가. SMA-50 / SMA-150 / SMA-200 이 Trend Template 의 핵심 지표." },
];
```

- [ ] **Step 2: tsc + commit**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -3
cd /Users/hank.es/git/personal/kr-by-claude
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "feat(GLOSSARY): 12 → 34 용어로 확장 — 주식·책·시스템 용어 풀이

테이블/SQL 은 카드 fold 소관이라 제외, 주식·책·시스템 일반 용어 중심.
카테고리: 분류·시그널 차원(4), 책 용어 패턴·매수기준(8), 시장 컨텍스트(4),
트리거·결정·사이징(6), 시스템(11). 사용자가 본문에서 마주칠 jargon
대부분을 한 화면에서 빠르게 찾아볼 수 있게 함."
```

---

### Task 9: `FAQ` 답변 친절화

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx` (`FAQ` 상수)

질문 7개는 보존, 답변만 친절화 (jargon 제거 + 일상어 풀이).

- [ ] **Step 1: `FAQ` 상수 답변 재작성**

```ts
const FAQ: { q: string; a: string }[] = [
  {
    q: "Watch 가 evaluate_pivot 의 LLM 결정으로 자동 entry 로 승격되지 않는 이유?",
    a:
      "평일 트리거 평가 단계 (evaluate_pivot) 의 prompt 가 *분류 변경 금지* 정책을 명시합니다 — classification 은 매주 토 weekend 또는 평일 신규 분류 (daily_delta) 에서만 변경. promotion 트리거는 '돌파 직전 staging' 일 뿐 매수 신호가 아니며 (prompt §3.3), go_now 가 발생하지 않도록 코드 안전장치도 적용 (entry_params 자동 수집은 trigger_type='breakout' 인 행만). watch 종목이 실제 매수로 가려면 다음 평일 종가가 pivot 위로 올라가는 *진짜 돌파* 가 별도로 발생해야 합니다.",
  },
  {
    q: "Pivot 이 없는 watch 종목은 어떻게 되나?",
    a:
      "evaluate_pivot 의 결정론 게이트가 pivot_price 가 NULL 인 종목을 skip — 매일 평가 사이클에서 빠집니다. 다음 토 weekend 또는 daily_delta 가 그 종목을 재분류해서 pivot 을 새로 부여할 때까지 정지 상태로 대기.",
  },
  {
    q: "daily_delta 와 weekend batch 의 차이?",
    a:
      "두 단계는 *같은 prompt (analyze_chart_v3.md) + 같은 ZIP 13 파일* 을 씁니다. 차이는 대상 풀: daily_delta = 신규 (최근 7일 안에 분류된 적 없는 결정론 통과 종목), weekend = 결정론 통과 전체 (이미 분류된 종목도 재분석). daily_delta 는 평일 매일 20:00 (LLM 4 단계의 첫 단계), weekend 는 토 03:20 (주 1회 전체 결산).",
  },
  {
    q: "dry-run 모드는 DB 에 영향이 있나?",
    a:
      "전혀 없습니다 — mock LLM 응답을 받아 응답 파싱·검증까지는 진행하지만, DB 저장 직전에 가드가 INSERT 를 skip 합니다. weekly_classification / trigger_evaluation_log / entry_params 어느 테이블도 변하지 않습니다.",
  },
  {
    q: "weekend 와 daily_delta 가 같은 prompt 라면 둘 다 필요한가?",
    a:
      "시점이 다릅니다. weekend = 매주 한 번 *전체 결산* (모든 결정론 통과 종목 재분류 → 이전 분류와 다를 수 있음, 예: entry → ignore). daily_delta = 평일에 *새로 결정론 통과한 종목만* 즉시 분류 (7일을 기다리지 않고 조기 포착). 결과적으로 모든 결정론 통과 종목은 주 1회 weekend 로 재분석되고, 그 사이 신규는 daily_delta 로 즉시 합류.",
  },
  {
    q: "evaluate_pivot 의 abort 가 종목 분류를 ignore 로 바꾸나?",
    a:
      "아니요. evaluate_pivot 은 trigger_evaluation_log 에 한 행 기록할 뿐, weekly_classification 의 분류는 그대로 둡니다. abort 가 매일 누적되어도 분류는 여전히 entry/watch. 다음 토 weekend 의 AI 가 *재분석* 후 base 가 깨졌다고 판단하면 비로소 ignore 로 재분류.",
  },
  {
    q: "한 종목이 한 주에 여러 번 분류될 수 있나?",
    a:
      "가능합니다. 예: 토 weekend 에 분류 (entry 재분석). 다만 그다음 평일 daily_delta 는 같은 종목을 다시 분류하지 못합니다 (최근 7일 안에 분류 이력이 있어 '신규' 조건 미충족). 다음 주 토 weekend 에서 또 재분석되어 새 행 추가. 결국 한 종목은 weekend 마다 *주 1회 재분석* 되고, daily_delta 는 *진짜 신규* 만 받습니다.",
  },
];
```

- [ ] **Step 2: tsc + commit**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -3
cd /Users/hank.es/git/personal/kr-by-claude
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "refactor(FAQ): 7 답변 친절화 — jargon 제거 + 일상어 풀이

질문 7개는 보존 (정확한 의문점이 잘 잡혀 있음). 답변에서 SQL/엔지니어링
표현 제거, 한국어 풀이로 교체. 예: 'evaluate_pivot 의 prompt 가 명시적
으로 분류 재평가 금지' → '평일 트리거 평가 단계의 prompt 가 분류 변경
금지 정책을 명시'. 평일/주말 사이클 차이, dry-run 영향, abort 의미
등이 본 답변만 읽고도 잡힘."
```

---

### Task 10: Header 한 줄 요약 + 안내 박스 미세 정련

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx` (header `<p>` + 안내 박스 내용)

- [ ] **Step 1: header 한 줄 요약 친절화**

기존:
```tsx
<p className="text-data-xs text-muted mt-3 leading-relaxed">
  평일 4단계 (daily_delta → evaluate_pivot → entry_params → performance) 와
  주말 1단계 (weekend batch) 의 흐름, 결정론 로직, LLM 로직, 책 원전 정리.
  + 10 종목 1주일 시뮬레이션으로 처음 보는 사용자도 흐름 이해 가능.
</p>
```

→ 교체:
```tsx
<p className="text-data text-muted mt-3 leading-relaxed">
  이 시스템이 매일·매주 한국 주식을 어떻게 자동 분류하고 매수 시그널까지
  만드는지 단계별로 보여줍니다. 결정론 1차 필터 → AI 분류 → 평일 트리거
  평가 → 매수 계획 → 사후 성과 추적 의 5 단계 흐름과 책 원전 (Minervini /
  O'Neil) 근거. 가상 10 종목이 한 주 동안 어떻게 처리되는지 시뮬레이션도 함께.
</p>
```

- [ ] **Step 2: 안내 박스 본문 미세 정련**

기존 안내 박스의 *"무엇을 볼 수 있나요?"* 첫 항목 (5 단계 파이프라인 설명) 의 *결정론 1차 필터* 가 *Trend Template 8 조건* 임을 한 줄 더 명시:

기존:
```tsx
<li><span className="text-ink">5 단계 파이프라인</span> — 결정론 1차 필터 → AI 분류 → 매수 조건 평가 → 매수 파라미터 산출 → 사후 성과 측정.</li>
```

→ 교체:
```tsx
<li><span className="text-ink">5 단계 파이프라인</span> — 결정론 1차 필터 (Minervini Trend Template 8 조건) → AI 분류 → 평일 트리거 평가 → 매수 계획 작성 → 사후 성과 추적.</li>
```

- [ ] **Step 3: tsc + commit**

```bash
cd web && npx tsc --noEmit 2>&1 | tail -3
cd /Users/hank.es/git/personal/kr-by-claude
git add web/src/pages/LlmPipelinePage.tsx
git commit -m "polish: header 한 줄 요약 + 안내 박스 미세 정련

header 의 영문 단계명 (daily_delta/evaluate_pivot/entry_params/performance)
나열을 한국어 친절 흐름으로 교체. 안내 박스의 5 단계 항목에 '결정론 1차
필터 = Trend Template 8 조건' 명시. 사용자가 페이지 진입 직후 첫 화면에서
혼란 없이 흐름을 잡을 수 있게."
```

---

### Task 11: 최종 검증 — tsc 전수 + 사용자 1차 검증 케이스 통독 확인

**Files:** 변경 없음 (verification only).

- [ ] **Step 1: TypeScript 전수 검증**

```bash
cd web && npx tsc --noEmit
```

기대: 출력 0 (0 error / 0 warning).

- [ ] **Step 2: 빌드 검증**

```bash
cd web && npm run build 2>&1 | tail -10
```

기대: `dist/` 디렉토리 생성 + error 0.

- [ ] **Step 3: 페이지 진입·통독 (수동)**

```bash
cd web && npm run dev
```

브라우저 `/docs/llm-pipeline` 진입 후 다음을 *순차 통독* — fold 펼치지 않고도 의미가 잡혀야 합니다 (사용자 1차 검증 케이스):

- **케이스 1**: weekend 카드의 *결정론 룰* 단락 — *"AI 호출 전 1차 필터로 'Minervini Trend Template 8 조건' 을 통과한 종목만 선별"* 으로 옛 *"minervini_pass (Trend Template 8조건)"* 의미 잡힘.
- **케이스 2**: weekend 카드의 *AI (LLM) 로직* 단락 — *"각 종목별로 13 개의 파일이 든 ZIP 묶음 (차트 PNG·일/주봉 OHLCV·시장 컨텍스트·corporate actions·minervini 진단 등) 을 만들어 AI 에게 보내고..."* 로 옛 *"ZIP 13개 파일"* 의미 잡힘.
- **케이스 3**: weekend 카드의 *결과 액션* 단락 — *"분류 결과를 weekly_classification 테이블에 새 행으로 추가합니다 (이전 분류는 지우지 않고 누적). 같은 종목·같은 시각의 중복은 자동 무시."* 로 옛 *"INSERT (source='weekend'). ON CONFLICT (...) DO NOTHING"* 의미 잡힘.

- [ ] **Step 4: fold 동작 시각 검증**

5 카드 각각에서 다음 fold 가 클릭으로 펼쳐지는지 + 콘텐츠가 정상 표시되는지 확인:

- weekend: 결정론 룰 SQL ▼ / Trend Template 8 조건 ▼ / ZIP 13 ▼ / 9 base 패턴 ▼ / 13 risk flag ▼ / SQL INSERT 상세 ▼
- daily_delta: ZIP 13 ▼ / 9 base 패턴 ▼ / 13 risk flag ▼
- evaluate_pivot: 결정론 룰 SQL ▼ / SQL INSERT 상세 ▼
- entry_params: 18 필드 ▼
- performance: 결정론 SQL ▼ / SQL INSERT 상세 ▼

각 카드 안 *입력/출력 테이블 칩* 클릭 시 컬럼 상세 fold 펼침 확인.

mermaid 다이어그램 2종 (개요 + 상태) 의 *이 그림 읽는 법* fold 도 클릭으로 펼침.

- [ ] **Step 5: drift 차단 검증**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
echo "=== pipeline 페이지가 audit 데이터 직접 import 하는지 확인 ==="
grep -E "from \"\.\./data/llm-pipeline-audit" web/src/pages/LlmPipelinePage.tsx
```

기대 출력 (최소): `BASE_PATTERNS`, `RISK_FLAGS`, `ZIP_FILES`, 그리고 `minervini.ts` 의 8 조건 export. 즉 audit 데이터를 *복제하지 않고 직접 import*.

- [ ] **Step 6: PROJECT_ROADMAP.md 의 *"audit 메타 동기화"* 항목과 동일 가족 — 본 작업 완료 사실 한 줄 추가**

`docs/PROJECT_ROADMAP.md` 의 §3 (원안 외 진화 항목) 또는 §4 (운영 상태) 에 본 작업의 산출 (LLM 분석 안내 페이지 초보 친화 리팩토링 — 2026-05-29) 한 줄 기록.

```bash
# §3 표의 마지막 행 (방법론 인프라) 다음에 한 행 추가
# 예: | **LLM 분석 안내 페이지 초보 친화 리팩토링** | 2026-05-29 | 페이지 jargon 밀도 진단·해소 (StageCard 친절 본문 + targeted folds + 30+ glossary + drift-차단 audit 데이터 직접 import) | `web/src/pages/LlmPipelinePage.tsx` + `web/src/data/llm-pipeline/` |
```

수동 편집 후:
```bash
git add docs/PROJECT_ROADMAP.md
git commit -m "docs(roadmap): LLM 분석 안내 페이지 초보 친화 리팩토링 완료 기록 (2026-05-29)"
```

- [ ] **Step 7: push (사용자 승인 후)**

```bash
git log --oneline origin/main..HEAD
# 11 task 커밋 (또는 그 이상) 확인 후 사용자 승인 시 push
git push origin main
```

---

## Self-Review (plan 작성자)

### 1. Spec coverage

| Spec § | 다루는 task |
|---|---|
| §1 배경/목적 | Task 1-10 전체가 jargon 밀도 해소 |
| §2 청자 (1~3년차) | Task 5, 6, 8, 9, 10 의 친절 본문 톤 |
| §3 Scope 포함 | Task 1-10 모두 |
| §3 Scope 제외 (simulation 모달) | 비대상 — plan 에 포함 없음 ✅ |
| §4 책임 분리 / drift 차단 | Task 4 import + Task 11 Step 5 검증 |
| §5 페이지 구조 (8 섹션) | header (T10), 안내박스 (T10), 개요 mermaid (T7), StageCards (T4-5), 시뮬레이션 (비변경), 상태 mermaid (T7), TriggerDecisionMatrix (T6), Glossary (T8), FAQ (T9) |
| §5.1 카드 내부 구조 | Task 4 (component) + Task 5 (data) |
| §5.2 fold 구현 | Task 3 (ListFold component) |
| §6 콘텐츠 카탈로그 | 11종 표 ↔ Task 1-9 매핑 |
| §7 Component 설계 | Task 3 (ListFold/TableExplainerList), Task 4 (StageCard) |
| §8 데이터 import 패턴 | Task 4 Step 1 |
| §9 친절화 톤 가이드 | Task 5, 6, 8, 9 모두 |
| §10 검증 기준 | Task 11 |
| §11 파일 list | File Structure 섹션 + Task 별 명시 |
| §12 비범위 | 명시 |

**Gap**: 없음. 모든 spec 요구가 task 에 매핑됨.

### 2. Placeholder scan

- "TBD"/"TODO" 없음 ✅
- "적절히" / "필요시" 등 vague 표현 없음 ✅
- Task 별 코드 블록 완비 (Task 1-2 의 데이터 source 본문, Task 3 의 컴포넌트, Task 4-5 의 StageCard 본문, Task 6-9 의 콘텐츠) ✅
- "Task N 와 유사" 표현 없음 (반복 코드는 모두 명시) ✅

### 3. Type / 이름 일관성

- `PipelineStage` interface 의 `llmShowsLists` 5 boolean (`eightConditions` / `nineBasePatterns` / `thirteenRiskFlags` / `thirteenZipFiles` / `eighteenFields`) — Task 4 Step 1 정의 ↔ Task 5 의 사용 ↔ Task 4 Step 3 의 conditional 렌더링 모두 동일 이름 ✅
- audit data 의 export 이름 (`CONDITIONS` vs `MINERVINI_CONDITIONS`) — Task 4 Step 2 에서 *실제 grep* 으로 확인 후 조정하도록 명시 ✅
- `TableInfo` / `EntryParamField` interface 의 필드명 일관 ✅
- File path 모두 절대/상대 경로 정확 ✅

### 4. 인지된 의존성 / 순서

- Task 1, 2 (data sources) → Task 3 (component depends on data) → Task 4 (StageCard depends on components + data) → Task 5 (STAGES depends on Task 4 interface) → Task 6-10 (independent) → Task 11 (verification)
- Task 4 Step 2 의 *audit 의 minervini.ts export 이름 검증* 이 unresolved 면 Task 5 까지 멈출 수 있음 — Step 2 자체가 명시적 guard 역할.

### 5. 알려진 위험

- **Mermaid 다이어그램의 한글 노드명** (Task 7) — 일부 Mermaid 버전이 따옴표 안 한글을 잘 처리하나 *간혹 자동 wrap 이 어색* 가능. Step 4 의 시각 검증으로 발견 시 영문 부제 병기로 완화 가능 (이미 spec 에 영문 원명 부제로 둠).
- **audit data 의 export 이름·필드 구조 미스매치** — Task 4 Step 2 가 명시적 검증 단계로 잡음.
- **현재 main branch 직접 commit pattern** — 본 plan 도 그대로. branch 옵션을 원하면 Task 1 이전에 branch 생성 추가 가능.
