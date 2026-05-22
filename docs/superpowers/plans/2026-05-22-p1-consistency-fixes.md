# P1 Consistency Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** UI 정합성 감사에서 식별된 INCONSISTENT 항목 7 개를 정정해 UI 가 표시하는 임계 / 정의가 코드 / 책과 일치하도록 만들기. 사용자 신뢰 + drift 재발 방지.

**Architecture:** 모두 *텍스트 사실 정정* 위주. UI 가 *능동적으로 잘못된 매수*를 만드는 건 아니지만, 표시 값이 실제 동작과 달라 사용자가 시스템을 잘못 이해함. P0-1 (breakout 1.5× 디폴트) 가 이미 UI 의 1.5× 와 자동 정렬됐으니 *나머지* INCONSISTENT 항목 처리. SSOT generated.ts 보간 활용은 옵션 (이 plan 은 단순 텍스트 정정).

**Tech Stack:** TypeScript, React, markdown prompts

**Spec:** `docs/superpowers/specs/2026-05-22-book-audit-findings.md` P1-1 ~ P1-7 (commit `c2591e3`)

---

## Implementation Order

P1 action 7 개는 모두 독립적. 의존성 거의 없음. 사용자 접점 (HomePage / InfoTooltip / ClassificationsPage / audit) 별로 묶지 않고 spec 의 P1-N 순서대로 task 1-7.

| Task | Action | 파일 | 영향 |
|---|---|---|---|
| 1 | P1-1 | `web/src/pages/HomePage.tsx:271` (FTD 툴팁) | 첫 화면 노출, 최고 |
| 2 | P1-2 | `web/src/components/InfoTooltip.tsx:119` (PP 정의) | 거래량 툴팁 |
| 3 | P1-3 | `web/src/pages/ClassificationsPage.tsx:89-90` (prior_uptrend 개념 혼동) | 분류 페이지 |
| 4 | P1-4 | `web/src/pages/ClassificationsPage.tsx:96` (unfavorable distribution window) | 분류 페이지 |
| 5 | P1-5 | `web/src/pages/HomePage.tsx:227` (distribution 툴팁 라벨) | 첫 화면 |
| 6 | P1-6 | `web/src/data/llm-pipeline-audit/stages.ts` (PP 책 인용에 50일선 추가) | audit 페이지 |
| 7 | P1-7 | `prompts/analyze_chart_v3.md:185` (faulty_pivot 정의 확장) | LLM prompt |

---

## File Structure

### 수정 (Modified)

| Path | What |
|---|---|
| `web/src/pages/HomePage.tsx:271` | FTD 툴팁 1.7%→1.4% / 4-7일→3-15일 (Task 1) |
| `web/src/pages/HomePage.tsx:227` | distribution 툴팁에 "시장 지수 기준" 라벨 (Task 5) |
| `web/src/components/InfoTooltip.tsx:119` | VOLUME_RATIO_HELP PP 정의 정정 (Task 2) |
| `web/src/pages/ClassificationsPage.tsx:89-90` | prior_uptrend_insufficient 텍스트 정정 (Task 3) |
| `web/src/pages/ClassificationsPage.tsx:96` | unfavorable_market_context 의 잘못된 "20일" 표기 제거 (Task 4) |
| `web/src/data/llm-pipeline-audit/stages.ts` | PP 책 인용에 50일선 조건 추가 (Task 6) |
| `prompts/analyze_chart_v3.md:185` | faulty_pivot 정의 확장 (Task 7) |

---

## Task 1: P1-1 — HomePage FTD 툴팁 정정

**Files:**
- Modify: `web/src/pages/HomePage.tsx:271`

코드 `follow_through.py:13-15` 의 실제 값: `FTD_PCT_THRESHOLD=1.4` (KOSPI / KOSDAQ 동일), `FTD_RALLY_WINDOW_MIN=3`, `FTD_RALLY_WINDOW_MAX=15`. UI 가 "1.7% / 4-7일" 로 표기 — 1.7% 는 1998-2002 옛 임계 (TLOND p.232-233), window 4-7 은 최적 범위지만 시스템은 3-15 모두 허용.

- [ ] **Step 1: Edit FTD tooltip**

Read `web/src/pages/HomePage.tsx` line 260-280 부근 먼저 확인. 기존 line 271:

```tsx
                    시장 바닥 후 4-7일째 +1.7% 이상 상승 + 거래량 증가한 첫 강세 신호.
```

변경:

```tsx
                    저점 후 3-15일째 (최적 4-7일) +1.4% 이상 상승 + 전일 대비 거래량 증가한 첫 강세 신호.
```

- [ ] **Step 2: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/HomePage.tsx
git commit -m "fix(p1-1): HomePage FTD 툴팁 임계 정정

1.7% / 4-7일 → 1.4% / 3-15일 (최적 4-7일). 1.7% 는 TLOND p.232-233 의
1998-2002 옛 임계 — 시스템 코드 (follow_through.py:13 FTD_PCT_THRESHOLD=1.4)
와 일치시킴. window 도 코드 (3-15일) 와 일치, 책 최적 4-7 부연."
```

---

## Task 2: P1-2 — InfoTooltip VOLUME_RATIO_HELP PP 정의 정정

**Files:**
- Modify: `web/src/components/InfoTooltip.tsx` (VOLUME_RATIO_HELP PP 라인)

기존 line 119 의 "2.00× 이상 — 강한 매수세 / pocket pivot 후보" 가 PP 를 "2.0×avg 임계" 처럼 시사. 책 / 코드의 PP 정의는 *avg 배수가 아니라* 직전 10일 down-day 최대 거래량 초과 + SMA-50 위 (TLOND Ch.5 p.132-133).

- [ ] **Step 1: Edit VOLUME_RATIO_HELP**

Read `web/src/components/InfoTooltip.tsx` line 110-130 부근 먼저 확인. 기존 line 117-120:

```tsx
      <li>
        <span className="num font-semibold">2.00×</span> 이상 — 강한 매수세 / pocket pivot 후보.
      </li>
```

변경 (PP 항목을 강한 매수세와 분리, PP 의 정확한 정의 표시):

```tsx
      <li>
        <span className="num font-semibold">2.00×</span> 이상 — 강한 매수세 (institutional buying).
      </li>
      <li>
        <span className="font-semibold">Pocket pivot</span> — avg 배수 무관. 상승일 거래량이 직전 10거래일 중 하락일 최대 거래량을 초과 + 종가가 50일 이동평균 위 (Morales & Kacher TLOND Ch.5 p.132-133).
      </li>
```

- [ ] **Step 2: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 3: Commit**

```bash
git add web/src/components/InfoTooltip.tsx
git commit -m "fix(p1-2): InfoTooltip VOLUME_RATIO_HELP PP 정의 정정

2.00× 라인이 PP 를 'avg 2.0× 후보' 처럼 시사 — 책 (TLOND p.132-133) /
코드 (volume.py:31-60) 의 PP 정의는 avg 배수 아니라 직전 10일 down 최대
거래량 초과 + 50일선 위. 두 신호를 분리 명시. 50일선 조건 노출도 함께
(이전엔 UI 어디에도 안 보임 — UI_MISSING)."
```

---

## Task 3: P1-3 — ClassificationsPage prior_uptrend 텍스트

**Files:**
- Modify: `web/src/pages/ClassificationsPage.tsx:89-90`

UI 가 `prior_uptrend_insufficient` 를 "52주 저점 25% 미만 상승" 으로 기술 — 이는 *C6* (close ≥ w52_low × 1.25) 개념. prompt §5 의 `prior_uptrend_insufficient` 실제 정의는 "Less than 20% run from prior base before current consolidation".

- [ ] **Step 1: Edit prior_uptrend_insufficient description**

Read `web/src/pages/ClassificationsPage.tsx` line 85-95 부근 먼저 확인. 기존 line 89-90 부근:

```tsx
  prior_uptrend_insufficient:
    "52주 저점 대비 25% 미만 상승 — Minervini Trend Template #5 위반 (Stage 2 진입 부족).",
```

변경:

```tsx
  prior_uptrend_insufficient:
    "직전 base 대비 20% 미만 상승 — flat_base 패턴의 prior uptrend 요건 미달 (prompt §5). C6 (52주 저점 ×1.25) 와 다른 개념.",
```

- [ ] **Step 2: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/ClassificationsPage.tsx
git commit -m "fix(p1-3): ClassificationsPage prior_uptrend_insufficient 정의 정정

기존 '52주 저점 25%' 는 C6 (Trend Template) 와 개념 혼동.
prompt §5 의 실제 정의 = '직전 base 대비 20% 상승 부족' (flat_base 요건).
C6 와 다른 개념임을 명시."
```

---

## Task 4: P1-4 — ClassificationsPage unfavorable distribution window

**Files:**
- Modify: `web/src/pages/ClassificationsPage.tsx:96`

기존 텍스트가 "IBD/Dr.K 표준은 20일" 부연 — *주* 임계는 25 sessions (정확) 이지만 "20일" 은 잘못된 보조 정보. Kacher (Dr. K) / IBD 의 distribution day 카운트 표준은 25 sessions 이지 20일 아님.

- [ ] **Step 1: Edit unfavorable_market_context description**

Read `web/src/pages/ClassificationsPage.tsx` line 93-100 부근 먼저 확인. 기존 line 96:

```tsx
  unfavorable_market_context:
    "시장 downtrend/correction 또는 distribution day 5개 이상 (25 sessions; O'Neil 의 '4~5주' 중 느슨한 쪽, IBD/Dr.K 표준은 20일).",
```

변경 (잘못된 "20일" 부연 제거, 정확한 정보만):

```tsx
  unfavorable_market_context:
    "시장 downtrend/correction 또는 distribution day 5개 이상 (25 sessions). O'Neil HMMS Ch.9 의 표준.",
```

- [ ] **Step 2: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/ClassificationsPage.tsx
git commit -m "fix(p1-4): ClassificationsPage unfavorable_market_context 잘못된 부연 제거

기존 'IBD/Dr.K 표준은 20일' 부연이 잘못 — Kacher/IBD 의 distribution day
표준은 25 sessions (O'Neil HMMS Ch.9). 코드 / prompt 도 모두 25 sessions.
20일 부연 제거 + O'Neil HMMS Ch.9 출처 명시."
```

---

## Task 5: P1-5 — HomePage distribution 툴팁 라벨

**Files:**
- Modify: `web/src/pages/HomePage.tsx:227`

표본 검증에서 발견: HomePage 의 distribution 툴팁은 *시장 지수* 정의 (`-0.2% + 전일 거래량 초과`). P0-2 후 코드의 *종목* distribution 정의 (1.0×avg) 와 다름. 사용자가 어느 정의인지 혼동 — 시장 vs 종목 분리 라벨 필요.

- [ ] **Step 1: Edit distribution tooltip**

Read `web/src/pages/HomePage.tsx` line 220-240 부근 먼저 확인. 기존 line 227:

```tsx
                    지수가 -0.2% 이상 하락 + 거래량 전일 대비 증가한 날. 기관 매도 신호.
```

변경 (시장 레벨 명시):

```tsx
                    시장 지수 기준 — 지수가 -0.2% 이상 하락 + 거래량 전일 대비 증가한 날. 기관 매도 신호. (종목 레벨 distribution 은 별도 정의: prompt §6.)
```

- [ ] **Step 2: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/HomePage.tsx
git commit -m "fix(p1-5): HomePage distribution 툴팁 라벨 — 시장 지수 명시

기존 툴팁이 distribution day 정의를 보여주나 *시장* vs *종목* 구분 없음.
P0-2 후 종목 레벨 distribution 정의 (close ≤-0.2% + vol > 1.0×avg) 와
시장 레벨 (지수 ≤-0.2% + 전일 거래량 초과) 이 별개 개념. 라벨 추가로
사용자 혼동 방지."
```

---

## Task 6: P1-6 — audit stages.ts PP 책 인용에 50일선 조건 추가

**Files:**
- Modify: `web/src/data/llm-pipeline-audit/stages.ts` (entry_params stage 의 PP 책 인용)

PP 의 핵심 필수 조건 "close > SMA-50" 이 UI 어디에도 안 보임 (UI_MISSING). Task 2 에서 InfoTooltip 의 VOLUME_RATIO_HELP 에 추가했지만, audit 페이지의 PP 책 인용 도 보강해 *다중 노출*.

- [ ] **Step 1: Edit PP BookCitation in stages.ts**

Read `web/src/data/llm-pipeline-audit/stages.ts` line 285-300 부근 먼저 확인. PP 책 인용은 entry_params stage 의 BookCitation 배열에 있음 (Morales & Kacher TLOND Ch.5 인용).

현재 (line 289-292 부근):
```ts
        englishQuote:
          "A pocket pivot is an early entry signal that occurs within a base, before the standard pivot point breakout.",
        koreanSummary: "Pocket pivot entry 패턴.",
      },
```

변경 (영문 인용 확장 + 한국어 요약 보강):

```ts
        englishQuote:
          "A pocket pivot is an early entry signal that occurs within a base, before the standard pivot point breakout. Pocket pivots should only be bought when they occur above the 50-day moving average.",
        koreanSummary:
          "Pocket pivot entry 패턴. 필수 조건: 종가가 50일 이동평균 위 (2008 폭락 직후 같은 매우 드문 예외 제외, TLOND p.132). 거래량은 직전 10거래일 중 하락일 최대 거래량 초과.",
      },
```

- [ ] **Step 2: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 3: Commit**

```bash
git add web/src/data/llm-pipeline-audit/stages.ts
git commit -m "fix(p1-6): audit stages.ts PP 책 인용에 50일선 필수 조건 추가

PP 의 '종가 > 50일선' 필수 조건이 UI 어디에도 안 보였음 (TLOND p.132
'pocket pivots should only be bought when they occur above the 50-day
moving average'). 영문 인용 확장 + 한국어 요약에 50일선 + 직전 10일
down 최대 초과 두 조건 명시."
```

---

## Task 7: P1-7 — prompt §5 faulty_pivot 정의 확장

**Files:**
- Modify: `prompts/analyze_chart_v3.md:185` (§5 risk_flags 표의 `faulty_pivot` 행)

UI (`ClassificationsPage.tsx:81-82`) 는 `faulty_pivot` 을 "wedging handle, handle 이 base 하반부, V자 즉시 신고가, 거래량 없는 돌파 등" 으로 풍부히 정의. prompt §5 는 "prior resistance failed 2+ times" 단일 사유만. LLM 은 prompt 만 봐서 V자/무거래량 돌파를 faulty_pivot 으로 못 잡음.

**P0-4 와 중복 회피**: P0-4 가 cup_with_handle 의 핸들 품질 (wedging / 8-12% / 10-week) 을 §4 cup 정의에 *직접* 추가했으므로, faulty_pivot 은 *pivot 위치/형태 결함 — V자 즉시 신고가, 거래량 없는 돌파* 중심으로 확장 (핸들 품질은 이미 cup 정의에 있음).

- [ ] **Step 1: Edit faulty_pivot definition**

Read `prompts/analyze_chart_v3.md` line 180-200 부근 먼저 확인. 기존 line 185:

```markdown
| `faulty_pivot` | Pivot is at a prior resistance level that has failed 2+ times |
```

변경:

```markdown
| `faulty_pivot` | Pivot is at a prior resistance level that has failed 2+ times, OR the pivot sits atop a structurally faulty base feature — e.g. an immediate V-shaped new high without any pullback, or a breakout that lacks volume confirmation. (Handle-specific faults — wedging handle, lower-half handle, depth >12% — are covered in §4 cup_with_handle handle quality block.) |
```

- [ ] **Step 2: Verify build**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 3: Commit**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "fix(p1-7): prompt §5 faulty_pivot 정의 확장 — V자 즉시 신고가 / 무거래량 돌파

기존엔 'prior resistance 2+회 실패' 단일 사유. UI (ClassificationsPage:81)
가 이미 풍부히 정의 (wedging / 하반부핸들 / V자 즉시 신고가 / 거래량 없는
돌파) — LLM 은 그 정의 못 봄. prompt 에 V자 즉시 신고가 + 무거래량 돌파
추가. 핸들 품질 (wedging / 8-12% / 10-week) 은 P0-4 에서 §4 cup 정의에
이미 추가됐으므로 중복 회피 — cross-reference 만."
```

---

## Self-Review

**1. Spec coverage**: spec P1-1 ~ P1-7 매핑:
- ✅ P1-1 HomePage FTD 1.7→1.4 / 4-7→3-15 → Task 1
- ✅ P1-2 InfoTooltip PP 정의 → Task 2
- ✅ P1-3 ClassificationsPage prior_uptrend → Task 3
- ✅ P1-4 ClassificationsPage distribution window → Task 4
- ✅ P1-5 HomePage distribution 라벨 → Task 5
- ✅ P1-6 PP 50일선 UI 노출 → Task 6 (audit stages.ts) + Task 2 (InfoTooltip 보조)
- ✅ P1-7 prompt faulty_pivot → Task 7

**2. Placeholder scan**: 모든 step 에 정확 코드 + 명령. "TODO" / "appropriate" 없음. ✅

**3. Type consistency**:
- Task 7 의 cross-reference (§4 cup_with_handle handle quality block) 가 P0-4 (commit `d0db045`) 의 실제 §4 추가와 일치 ✅
- 모든 task 가 P1 spec 의 변경 의도와 일치 ✅

**4. 제외 항목**:
- **SSOT 인프라 활용** (UI 가 `thresholds.generated.ts` 의 임계를 *직접 보간*) 은 이 plan 의 scope 외. 미래 enhancement.
  - 예: Task 1 의 FTD 1.4% 를 `import { FTD_PCT_THRESHOLD } from "../data/thresholds.generated"; ... ${FTD_PCT_THRESHOLD.KOSPI}%` 형태로. 이 plan 은 *텍스트 사실 정정* 만.
- **`web/src/pages/llm-pipeline-audit/PatternCards.tsx` 같은 추가 위치에 PP 50일선 노출** — Task 6 의 audit stages.ts + Task 2 의 InfoTooltip 으로 *두 곳* 노출 충분.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-p1-consistency-fixes.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
