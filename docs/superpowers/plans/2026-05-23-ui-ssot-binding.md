# UI SSOT Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** UI 의 임계 텍스트를 `thresholds.generated.ts` 의 SSOT 상수 import + 보간으로 교체. SSOT 값 변경 시 `uv run python scripts/export_thresholds.py` 만으로 UI 자동 갱신 — drift 재발 완전 차단.

**Architecture:** 기존 SSOT-1 plan (commit `3df3e19`) 이 Python 측 SSOT + UI 자동 export (`web/src/data/thresholds.generated.ts`) 까지 완성. 본 plan 은 UI 가 실제로 *그 generated.ts 를 import 해서 사용* 하도록 교체 — SSOT-1 의 진정한 완성. 책 직접 인용 (cup 핸들 8-12% 등) 은 *변경 안 함* — SSOT 상수가 *있는* 임계만 보간.

**Tech Stack:** TypeScript, React, Vite

**Spec:** `docs/superpowers/specs/2026-05-22-book-audit-findings.md` SSOT-1 (commit `c2591e3`)

---

## Implementation Order

5 task. 카테고리별 묶음 — 각 task = 1 commit. 모두 독립.

| Task | 카테고리 | 파일 | 보간할 상수 |
|---|---|---|---|
| 1 | 시장 임계 | `HomePage.tsx` | distribution / FTD |
| 2 | 거래량 임계 | `InfoTooltip.tsx`, `ClassificationsPage.tsx` | breakout / PP lookback / distribution lookback |
| 3 | 게이트 | `LlmPipelinePage.tsx`, `llm-pipeline-simulation.ts` | gate (1.0×) |
| 4 | audit 데이터 | `audit/risk-flags.ts`, `audit/stages.ts` | breakout floor / gate |
| 5 | Minervini 상수 | `audit/minervini.ts` | C6 / C7 / C8 |

---

## File Structure

### 수정 (Modified, 모두 import 추가 + 텍스트 보간)

| Path | 변경 |
|---|---|
| `web/src/pages/HomePage.tsx` | distribution + FTD 툴팁 (Task 1) |
| `web/src/components/InfoTooltip.tsx` | breakout / PP 정의 (Task 2) |
| `web/src/pages/ClassificationsPage.tsx` | low_volume_breakout + unfavorable (Task 2) |
| `web/src/pages/LlmPipelinePage.tsx` | deterministic 게이트 설명 (Task 3) |
| `web/src/data/llm-pipeline-simulation.ts` | 시뮬레이션 게이트 텍스트 (Task 3) |
| `web/src/data/llm-pipeline-audit/risk-flags.ts` | breakout 임계 (Task 4) |
| `web/src/data/llm-pipeline-audit/stages.ts` | breakout / 게이트 (Task 4) |
| `web/src/data/llm-pipeline-audit/minervini.ts` | C6 / C7 / C8 임계 (Task 5) |

### Import 경로 참고

- `web/src/pages/*.tsx` → `../data/thresholds.generated`
- `web/src/components/*.tsx` → `../data/thresholds.generated`
- `web/src/data/llm-pipeline-simulation.ts` → `./thresholds.generated`
- `web/src/data/llm-pipeline-audit/*.ts` → `../thresholds.generated`

---

## 보간 패턴 (참고)

JSX 안의 텍스트:
```tsx
// Before
<div>최근 25일 중 5일 이상</div>

// After
import { MARKET_DISTRIBUTION_LOOKBACK_DAYS } from "../data/thresholds.generated";
...
<div>최근 {MARKET_DISTRIBUTION_LOOKBACK_DAYS}일 중 5일 이상</div>
```

일반 string property (객체 안):
```ts
// Before
deterministic: "... 게이트는 거래량 ≥ 1.0× ...",

// After
import { GATE_BREAKOUT_VOL_MULT } from "../data/thresholds.generated";
...
deterministic: `... 게이트는 거래량 ≥ ${GATE_BREAKOUT_VOL_MULT.toFixed(1)}× ...`,
```

소수 표시:
- `BREAKOUT_VOL_PREFERRED` (1.5) → `.toFixed(1)` 로 `1.5` 보장
- `C6_W52LOW_MULT` (1.25) → `.toFixed(2)` 로 `1.25` 보장
- 정수 (lookback days 등) → `.toString()` 또는 직접 보간

---

## Task 1: 시장 임계 — HomePage 툴팁

**Files:**
- Modify: `web/src/pages/HomePage.tsx` (distribution 툴팁 line 227 / FTD 툴팁 line 271)

### Step 1: Add SSOT import

Read `web/src/pages/HomePage.tsx` 상단의 기존 import 들 확인 (대략 line 1-15). 마지막 import 다음에 추가:

```tsx
import {
  MARKET_DISTRIBUTION_PCT_THRESHOLD,
  MARKET_DISTRIBUTION_LOOKBACK_DAYS,
  FTD_PCT_THRESHOLD,
  FTD_RALLY_WINDOW_MIN_DAYS,
  FTD_RALLY_WINDOW_MAX_DAYS,
} from "../data/thresholds.generated";
```

### Step 2: Edit distribution tooltip

Edit `web/src/pages/HomePage.tsx` line 227-230 부근. 기존:

```tsx
                  <div>
                    시장 지수 기준 — 지수가 -0.2% 이상 하락 + 거래량 전일 대비 증가한 날. 기관 매도 신호. (종목 레벨 distribution 은 별도 정의: prompt §6.)
                    최근 25일 중 5일 이상이면 약세장 시사.
                  </div>
```

변경:

```tsx
                  <div>
                    시장 지수 기준 — 지수가 {MARKET_DISTRIBUTION_PCT_THRESHOLD.toFixed(1)}% 이상 하락 + 거래량 전일 대비 증가한 날. 기관 매도 신호. (종목 레벨 distribution 은 별도 정의: prompt §6.)
                    최근 {MARKET_DISTRIBUTION_LOOKBACK_DAYS}일 중 5일 이상이면 약세장 시사.
                  </div>
```

(`-0.2%` 가 `${MARKET_DISTRIBUTION_PCT_THRESHOLD.toFixed(1)}%` 로 → `-0.2%` 동일 출력.)

### Step 3: Edit FTD tooltip

Edit `web/src/pages/HomePage.tsx` line 271 부근. 기존:

```tsx
                    저점 후 3-15일째 (최적 4-7일) +1.4% 이상 상승 + 전일 대비 거래량 증가한 첫 강세 신호.
```

변경:

```tsx
                    저점 후 {FTD_RALLY_WINDOW_MIN_DAYS}-{FTD_RALLY_WINDOW_MAX_DAYS}일째 (최적 4-7일) +{FTD_PCT_THRESHOLD.KOSPI.toFixed(1)}% 이상 상승 + 전일 대비 거래량 증가한 첫 강세 신호.
```

(`3-15` → SSOT 보간. `4-7` 은 *책 최적 범위* 라 SSOT 상수 없음 — 그대로 둠. `1.4%` → SSOT 보간.)

### Step 4: tsc clean

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

### Step 5: Commit

```bash
git add web/src/pages/HomePage.tsx
git commit -m "feat(ui-ssot): HomePage 시장 임계 툴팁이 SSOT 보간 사용

distribution 툴팁 (-0.2% / 25일) + FTD 툴팁 (1.4% / 3-15일) 의 임계 값을
thresholds.generated 의 상수 보간으로 교체. SSOT 변경 시 export 스크립트
재실행만으로 UI 자동 갱신. drift 재발 차단.

책 표현 (FTD '최적 4-7일') 은 SSOT 상수 없음 → 그대로 유지."
```

---

## Task 2: 거래량 임계 — InfoTooltip + ClassificationsPage

**Files:**
- Modify: `web/src/components/InfoTooltip.tsx` (TRIGGER_TYPE_HELP line 68 / VOLUME_RATIO_HELP line 116-124)
- Modify: `web/src/pages/ClassificationsPage.tsx` (low_volume_breakout line 84 / unfavorable_market_context line 96)

### Step 1: Add SSOT import to InfoTooltip.tsx

Read `web/src/components/InfoTooltip.tsx` 상단 import 확인. 마지막 import 다음에 추가:

```tsx
import {
  GATE_BREAKOUT_VOL_MULT,
  BREAKOUT_VOL_FLOOR,
  BREAKOUT_VOL_PREFERRED,
  PP_DOWN_VOL_LOOKBACK_DAYS,
} from "../data/thresholds.generated";
```

### Step 2: Edit TRIGGER_TYPE_HELP (line 68)

Edit `web/src/components/InfoTooltip.tsx` line 68 부근. 기존:

```tsx
        — 종가가 pivot 가격을 돌파 + 거래량이 50일 평균 이상 (게이트 통과 = ≥ 1.0×). 매수 확정 (entry_params) 은 LLM 이 책 표준 1.5× 선호치 / 1.4× 허용 하한을 적용.
```

변경 (3 곳 보간):

```tsx
        — 종가가 pivot 가격을 돌파 + 거래량이 50일 평균 이상 (게이트 통과 = ≥ {GATE_BREAKOUT_VOL_MULT.toFixed(1)}×). 매수 확정 (entry_params) 은 LLM 이 책 표준 {BREAKOUT_VOL_PREFERRED.toFixed(1)}× 선호치 / {BREAKOUT_VOL_FLOOR.toFixed(1)}× 허용 하한을 적용.
```

### Step 3: Edit VOLUME_RATIO_HELP (line 116-124)

Edit `web/src/components/InfoTooltip.tsx` 의 `VOLUME_RATIO_HELP` 안 `1.50×` (line 116 부근) + PP 정의 (line 121-124). 기존:

```tsx
      <li>
        <span className="num font-semibold">1.50×</span> 이상 — breakout 의 거래량 요건.
      </li>
      <li>
        <span className="num font-semibold">2.00×</span> 이상 — 강한 매수세 (institutional buying).
      </li>
      <li>
        <span className="font-semibold">Pocket pivot</span> — avg 배수 무관. 상승일 거래량이 직전 10거래일 중 하락일 최대 거래량을 초과 + 종가가 50일 이동평균 위 (Morales &amp; Kacher TLOND Ch.5 p.132-133).
      </li>
```

변경 (1.50× 와 10거래일 보간; 2.00× 는 책/SSOT 무관한 단순 표시라 *그대로*):

```tsx
      <li>
        <span className="num font-semibold">{BREAKOUT_VOL_PREFERRED.toFixed(2)}×</span> 이상 — breakout 의 거래량 요건.
      </li>
      <li>
        <span className="num font-semibold">2.00×</span> 이상 — 강한 매수세 (institutional buying).
      </li>
      <li>
        <span className="font-semibold">Pocket pivot</span> — avg 배수 무관. 상승일 거래량이 직전 {PP_DOWN_VOL_LOOKBACK_DAYS}거래일 중 하락일 최대 거래량을 초과 + 종가가 50일 이동평균 위 (Morales &amp; Kacher TLOND Ch.5 p.132-133).
      </li>
```

(`.toFixed(2)` → `1.50` 보장. `2.00×` 은 *임의 분류 기준* 으로 SSOT 무관, 그대로.)

### Step 4: Add SSOT import to ClassificationsPage.tsx

Read `web/src/pages/ClassificationsPage.tsx` 상단 import 확인. 마지막 import 다음에 추가:

```tsx
import {
  BREAKOUT_VOL_PREFERRED,
  MARKET_DISTRIBUTION_LOOKBACK_DAYS,
} from "../data/thresholds.generated";
```

### Step 5: Edit RISK_FLAG_DESCRIPTIONS (low_volume_breakout + unfavorable_market_context)

기존 `RISK_FLAG_DESCRIPTIONS` 객체는 *모듈 top-level 상수* — `const RISK_FLAG_DESCRIPTIONS: Record<string, string> = { ... }`. 객체 안의 string 도 template literal 로 보간 가능.

Edit `web/src/pages/ClassificationsPage.tsx`. 기존 `low_volume_breakout` (line 84):

```tsx
  low_volume_breakout:
    "돌파 거래량이 50일 평균의 1.5배 미만 (O'Neil: 50% above average 가 최소).",
```

변경:

```tsx
  low_volume_breakout:
    `돌파 거래량이 50일 평균의 ${BREAKOUT_VOL_PREFERRED.toFixed(1)}배 미만 (O'Neil: 50% above average 가 최소).`,
```

기존 `unfavorable_market_context` (line 96):

```tsx
  unfavorable_market_context:
    "시장 downtrend/correction 또는 distribution day 5개 이상 (25 sessions). O'Neil HMMS Ch.9 의 표준.",
```

변경:

```tsx
  unfavorable_market_context:
    `시장 downtrend/correction 또는 distribution day 5개 이상 (${MARKET_DISTRIBUTION_LOOKBACK_DAYS} sessions). O'Neil HMMS Ch.9 의 표준.`,
```

### Step 6: tsc clean

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

### Step 7: Commit

```bash
git add web/src/components/InfoTooltip.tsx web/src/pages/ClassificationsPage.tsx
git commit -m "feat(ui-ssot): InfoTooltip + ClassificationsPage 거래량 임계 SSOT 보간

InfoTooltip TRIGGER_TYPE_HELP (1.0× / 1.5× / 1.4×) + VOLUME_RATIO_HELP
(1.5× / 10거래일) + ClassificationsPage low_volume_breakout (1.5×) /
unfavorable_market_context (25 sessions) 임계 값을 thresholds.generated
보간으로 교체.

2.00× (강한 매수세 분류 기준) 은 임의 분류 / SSOT 무관 → 그대로."
```

---

## Task 3: 게이트 — LlmPipelinePage + simulation.ts

**Files:**
- Modify: `web/src/pages/LlmPipelinePage.tsx` (line 84 부근 deterministic property)
- Modify: `web/src/data/llm-pipeline-simulation.ts` (line 93, 267 게이트 텍스트)

### Step 1: Add SSOT import to LlmPipelinePage.tsx

Read `web/src/pages/LlmPipelinePage.tsx` 상단 import 확인. 추가:

```tsx
import { GATE_BREAKOUT_VOL_MULT } from "../data/thresholds.generated";
```

### Step 2: Edit deterministic property (line 84)

Edit `web/src/pages/LlmPipelinePage.tsx` line 84 부근의 deterministic property. 기존:

```tsx
    deterministic:
      "결정론 트리거 게이트 (compute/trigger_gate.py): close < stop_loss 또는 close < sma_50 → invalidation. entry 종목: close > pivot AND volume >= avg_volume_50d (1.0×, 게이트는 거래량 죽지 않은 정도만 확인 — 1.4~1.5× 표준 / pocket pivot 예외 판정은 LLM 에 위임) → breakout. watch 종목: close >= pivot × 0.95 AND volume >= avg → promotion (책 근거 없음, 시스템 staging 트리거 — go_now 발생 금지, close > pivot 도달은 별도 breakout 트리거가 처리).",
```

변경 (1.0× 만 보간; 0.95 / 1.4 / 1.5 는 *책 표준 / 별도 임계* 라 보간 안 함 — 단순 게이트 임계만):

```tsx
    deterministic:
      `결정론 트리거 게이트 (compute/trigger_gate.py): close < stop_loss 또는 close < sma_50 → invalidation. entry 종목: close > pivot AND volume >= avg_volume_50d (${GATE_BREAKOUT_VOL_MULT.toFixed(1)}×, 게이트는 거래량 죽지 않은 정도만 확인 — 1.4~1.5× 표준 / pocket pivot 예외 판정은 LLM 에 위임) → breakout. watch 종목: close >= pivot × 0.95 AND volume >= avg → promotion (책 근거 없음, 시스템 staging 트리거 — go_now 발생 금지, close > pivot 도달은 별도 breakout 트리거가 처리).`,
```

(string `"..."` → backtick template literal `` `...` `` 로 변경.)

### Step 3: Add SSOT import to simulation.ts

Read `web/src/data/llm-pipeline-simulation.ts` 상단 import 확인. 추가:

```ts
import { GATE_BREAKOUT_VOL_MULT } from "./thresholds.generated";
```

### Step 4: Edit simulation 2 위치 (line 93, 267)

Edit `web/src/data/llm-pipeline-simulation.ts` line 93 부근. 기존:

```ts
            { label: "결정론 게이트", value: "close > pivot AND volume ≥ avg (1.0×) → breakout (정밀 1.5× 선호치는 LLM)" },
```

변경:

```ts
            { label: "결정론 게이트", value: `close > pivot AND volume ≥ avg (${GATE_BREAKOUT_VOL_MULT.toFixed(1)}×) → breakout (정밀 1.5× 선호치는 LLM)` },
```

(`"..."` → `` `...` ``)

Line 267 부근. 기존:

```ts
          impact: "evaluate_pivot 의 entry 게이트. close > pivot + volume ≥ avg (1.0×) 시 breakout 트리거 (매수 확정 1.5× 는 LLM).",
```

변경:

```ts
          impact: `evaluate_pivot 의 entry 게이트. close > pivot + volume ≥ avg (${GATE_BREAKOUT_VOL_MULT.toFixed(1)}×) 시 breakout 트리거 (매수 확정 1.5× 는 LLM).`,
```

### Step 5: tsc clean

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

### Step 6: Commit

```bash
git add web/src/pages/LlmPipelinePage.tsx web/src/data/llm-pipeline-simulation.ts
git commit -m "feat(ui-ssot): 게이트 1.0× 텍스트 SSOT 보간

LlmPipelinePage deterministic 설명 + simulation.ts 의 게이트 메시지 2곳
의 1.0× 값을 GATE_BREAKOUT_VOL_MULT 보간으로 교체. SSOT 변경 시 자동 갱신.

1.4× / 1.5× (책 표준 / 선호치) 는 게이트와 별개 컨텍스트라 그대로 유지."
```

---

## Task 4: audit 정적 데이터 — risk-flags.ts + stages.ts

**Files:**
- Modify: `web/src/data/llm-pipeline-audit/risk-flags.ts` (line 29 low_volume_breakout 정의)
- Modify: `web/src/data/llm-pipeline-audit/stages.ts` (line 184 trigger 별 결정 규칙)

### Step 1: Add SSOT import to risk-flags.ts

Read `web/src/data/llm-pipeline-audit/risk-flags.ts` 상단. import 추가:

```ts
import { BREAKOUT_VOL_FLOOR } from "../thresholds.generated";
```

### Step 2: Edit low_volume_breakout definition (line 29)

기존:

```ts
    id: "low_volume_breakout",
    definition:
      "Breakout volume < 1.4× the 50-day average (O'Neil: 40-50% above normal at minimum)",
  },
```

변경 (1.4× 만 보간; "40-50% above normal" 은 *책 인용* 으로 그대로):

```ts
    id: "low_volume_breakout",
    definition:
      `Breakout volume < ${BREAKOUT_VOL_FLOOR.toFixed(1)}× the 50-day average (O'Neil: 40-50% above normal at minimum)`,
  },
```

### Step 3: Add SSOT import to stages.ts

Read `web/src/data/llm-pipeline-audit/stages.ts` 상단. import 추가:

```ts
import {
  GATE_BREAKOUT_VOL_MULT,
  BREAKOUT_VOL_FLOOR,
} from "../thresholds.generated";
```

### Step 4: Edit stages.ts trigger 규칙 (line 184)

Read `web/src/data/llm-pipeline-audit/stages.ts` line 180-205 부근. 기존 trigger 별 결정 규칙 안에 `1.4×` (line 184) + 책 인용 안에 1.0× / 1.4× 표현.

line 184 의 결정 규칙 부분. 기존:

```ts
Trigger 별 결정 규칙:
- breakout: go_now/wait/abort (1.4× / 일중 상단 / distribution / SMA-21 가드)
- invalidation: abort/wait (SMA-50 이탈 + SMA-21 보조)
- promotion: go_now 발생 안 함 (staging 신호)`,
```

변경 (`1.4×` 만 보간):

이 텍스트는 `promptSummary: \`...\`` 같은 backtick string 안에 이미 있을 것. 그 안에 보간 가능. 단 *문맥 전체* 가 backtick literal 인지 확인 — 만약 일반 string `"..."` 이면 backtick 으로 변환 필요.

기존이 backtick 이면:
```ts
- breakout: go_now/wait/abort (${BREAKOUT_VOL_FLOOR.toFixed(1)}× / 일중 상단 / distribution / SMA-21 가드)
```

또 line 198-205 부근 책 인용 안의 `1.4×` / `1.0×` 도 변경 — 다만 *그 인용 자체가 우리 한국어 요약* 일 때만. *영어 영어 원문* 안은 그대로 유지.

예시 — `koreanSummary: "...코드는 LLM prompt 에서 정밀 판정 (1.4×), 게이트는 1.0× 로 사전 배제 최소화..."` 부분. 기존:

```ts
        koreanSummary:
          "돌파일 거래량 평균 대비 40-50% 이상. 코드는 LLM prompt 에서 정밀 판정 (1.4×), 게이트는 1.0× 로 사전 배제 최소화 (§9 변경 이력).",
```

변경:

```ts
        koreanSummary:
          `돌파일 거래량 평균 대비 40-50% 이상. 코드는 LLM prompt 에서 정밀 판정 (${BREAKOUT_VOL_FLOOR.toFixed(1)}×), 게이트는 ${GATE_BREAKOUT_VOL_MULT.toFixed(1)}× 로 사전 배제 최소화 (§9 변경 이력).`,
```

(`"..."` → `` `...` `` + 두 보간.)

영어 원문 `englishQuote` 안의 `40 to 50%` 는 *책 그대로* — 변경 안 함.

### Step 5: tsc clean

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

### Step 6: Commit

```bash
git add web/src/data/llm-pipeline-audit/risk-flags.ts web/src/data/llm-pipeline-audit/stages.ts
git commit -m "feat(ui-ssot): audit 데이터의 breakout/gate 임계 SSOT 보간

risk-flags.ts 의 low_volume_breakout 정의 (1.4×) + stages.ts 의 trigger
결정 규칙 + 한국어 책 인용 요약 (1.4× / 1.0×) 을 SSOT 보간으로 교체.

영어 원문 (englishQuote 의 '40 to 50%') 은 책 그대로 — 변경 안 함."
```

---

## Task 5: Minervini Trend Template — minervini.ts

**Files:**
- Modify: `web/src/data/llm-pipeline-audit/minervini.ts` (C6 line 62-67 / C7 line 69-74 / C8 line 77-83)

### Step 1: Add SSOT import

Read `web/src/data/llm-pipeline-audit/minervini.ts` 상단. import 추가:

```ts
import {
  C6_W52LOW_MULT,
  C7_W52HIGH_MULT,
  C8_RS_RATING_MIN,
} from "../thresholds.generated";
```

### Step 2: Edit C6 entry (line 62-67)

기존:

```ts
  {
    num: 6,
    korean: "close ≥ w52_low × 1.25",
    threshold: "1.25×",
    codeRef: "minervini.py:38",
    englishOriginal:
      "Price ≥ 52w-low × 1.25 (TTLC Ch.6 — 최신작) / × 1.30 (TLSMW Ch.5)",
    note: "두 저작 간 버전 차이 — TTLC Ch.6 (+25%) 와 TLSMW Ch.5 (+30%) 모두 책 근거. 우리는 최신작 채택.",
  },
```

변경 (`1.25` 보간 — 두 위치: `korean` 과 `threshold`. `englishOriginal` 의 `1.25` 는 *책 출처 명시* 라 보간 가능; `1.30` 은 다른 책의 값 → 그대로):

```ts
  {
    num: 6,
    korean: `close ≥ w52_low × ${C6_W52LOW_MULT.toFixed(2)}`,
    threshold: `${C6_W52LOW_MULT.toFixed(2)}×`,
    codeRef: "minervini.py:38",
    englishOriginal:
      `Price ≥ 52w-low × ${C6_W52LOW_MULT.toFixed(2)} (TTLC Ch.6 — 최신작) / × 1.30 (TLSMW Ch.5)`,
    note: "두 저작 간 버전 차이 — TTLC Ch.6 (+25%) 와 TLSMW Ch.5 (+30%) 모두 책 근거. 우리는 최신작 채택.",
  },
```

(string `"..."` → backtick `` `...` ``)

`note` 의 `+25%` 는 *책 표현* (퍼센트 표기) 이라 그대로 — 또는 SSOT 보간으로 `+${((C6_W52LOW_MULT-1)*100).toFixed(0)}%` 도 가능. 단순함 우선 — *그대로* 둠.

### Step 3: Edit C7 entry (line 69-74)

기존:

```ts
  {
    num: 7,
    korean: "close ≥ w52_high × 0.75",
    threshold: "0.75×",
    codeRef: "minervini.py:40",
    englishOriginal: "Price ≥ 52w-high × 0.75 (within 25% of 52w high)",
  },
```

변경:

```ts
  {
    num: 7,
    korean: `close ≥ w52_high × ${C7_W52HIGH_MULT.toFixed(2)}`,
    threshold: `${C7_W52HIGH_MULT.toFixed(2)}×`,
    codeRef: "minervini.py:40",
    englishOriginal: `Price ≥ 52w-high × ${C7_W52HIGH_MULT.toFixed(2)} (within 25% of 52w high)`,
  },
```

### Step 4: Edit C8 entry (line 77-83)

기존:

```ts
  {
    num: 8,
    korean: "rs_rating ≥ 70",
    threshold: "70",
    codeRef: "store.py:91 (SQL UPDATE SET)",
    englishOriginal: "RS Rating ≥ 70",
    note: "RS Rating 개념은 O'Neil HMMS, 임계 70은 Minervini TLSMW Ch.5 — c1-c7 과 함께 minervini_pass 의 8 번째 조건.",
  },
```

변경 (`70` 보간 — `korean` / `threshold` / `englishOriginal`. `note` 의 `70` 도 일관성 위해 보간 권장):

```ts
  {
    num: 8,
    korean: `rs_rating ≥ ${C8_RS_RATING_MIN}`,
    threshold: `${C8_RS_RATING_MIN}`,
    codeRef: "store.py:91 (SQL UPDATE SET)",
    englishOriginal: `RS Rating ≥ ${C8_RS_RATING_MIN}`,
    note: `RS Rating 개념은 O'Neil HMMS, 임계 ${C8_RS_RATING_MIN}은 Minervini TLSMW Ch.5 — c1-c7 과 함께 minervini_pass 의 8 번째 조건.`,
  },
```

### Step 5: Check MINERVINI_PASS_FORMULA

Read `web/src/data/llm-pipeline-audit/minervini.ts` 상단 (대략 line 10-25 부근). `MINERVINI_PASS_FORMULA` template literal 안에 `rs_rating >= 70` 표현이 있을 것 — 그것도 SSOT 보간:

기존:

```ts
export const MINERVINI_PASS_FORMULA = `
minervini_pass = (
    minervini_c1 IS TRUE AND minervini_c2 IS TRUE AND
    minervini_c3 IS TRUE AND minervini_c4 IS TRUE AND
    minervini_c5 IS TRUE AND minervini_c6 IS TRUE AND
    minervini_c7 IS TRUE AND (rs_rating >= 70)
)
`.trim();
```

변경:

```ts
export const MINERVINI_PASS_FORMULA = `
minervini_pass = (
    minervini_c1 IS TRUE AND minervini_c2 IS TRUE AND
    minervini_c3 IS TRUE AND minervini_c4 IS TRUE AND
    minervini_c5 IS TRUE AND minervini_c6 IS TRUE AND
    minervini_c7 IS TRUE AND (rs_rating >= ${C8_RS_RATING_MIN})
)
`.trim();
```

### Step 6: tsc clean

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

### Step 7: Commit

```bash
git add web/src/data/llm-pipeline-audit/minervini.ts
git commit -m "feat(ui-ssot): audit minervini.ts C6/C7/C8 임계 + PASS_FORMULA SSOT 보간

C6 (1.25) / C7 (0.75) / C8 (70) 임계와 MINERVINI_PASS_FORMULA 의
rs_rating >= 70 표현을 thresholds.generated 보간으로 교체. SSOT 변경 시
audit 페이지 자동 갱신.

note 의 '+25%' 등 책 표현 (퍼센트 표기) 은 그대로."
```

---

## Self-Review

**1. Spec coverage**: 본 plan 의 5 task 가 *기존 SSOT-1 plan* (commit `3df3e19`) 의 미완성 부분 (UI 측 실제 import) 을 완료.

대상 위치별 매핑:
- A (시장 임계): Task 1 ✅
- B (거래량 임계): Task 2 ✅
- C (게이트 설명): Task 3 ✅
- D (audit 데이터): Task 4 ✅
- E (Minervini constants): Task 5 ✅

**2. Placeholder scan**: 모든 step 에 정확 코드 + 명령. ✅

**3. Type consistency**:
- `BREAKOUT_VOL_PREFERRED.toFixed(2)` (1.50× 형태) vs `BREAKOUT_VOL_PREFERRED.toFixed(1)` (1.5× 형태) — 각 위치 *기존 표시 형식*에 맞춰 다름. 일관성 유지.
- `C6_W52LOW_MULT.toFixed(2)` (1.25) / `C7_W52HIGH_MULT.toFixed(2)` (0.75) — 소수 2 자리.
- `C8_RS_RATING_MIN` (정수 70) — `.toFixed()` 불필요, 직접 보간.
- `MARKET_DISTRIBUTION_PCT_THRESHOLD.toFixed(1)` (-0.2) — 음수 표시 유지.
- `FTD_PCT_THRESHOLD.KOSPI.toFixed(1)` — dict 의 KOSPI 키 접근.

**4. 제외**:
- *책 인용* (영어 원문 / 책 표준 표현 "40-50%" / "+25%" / "최적 4-7일" 등) — 책 출처 의미 유지를 위해 보간 안 함.
- 임의 분류 기준 ("2.00× 강한 매수세") — 책/SSOT 무관, 그대로.
- 동작 변화 0 — 모든 SSOT 상수가 현재 UI 표시값과 동일.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-23-ui-ssot-binding.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
