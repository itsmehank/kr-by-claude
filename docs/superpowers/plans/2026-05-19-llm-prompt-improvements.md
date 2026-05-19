# LLM 분류 prompt 개선 (B 사이클) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `prompts/analyze_chart_v3.md` 의 reasoning 출력을 markdown 5섹션 + 1500자 + 친절한 톤으로 변경. 새 base 패턴 4개 (high_tight_flag / 3c_cheat / base_on_base / ascending_base) 추가. ClassificationsPage 가 reasoning 을 react-markdown 으로 렌더.

**Architecture:** Prompt 본문만 수정 + frontend 가 react-markdown 으로 렌더. DB schema / Pydantic / API router / backend store 코드 **변경 없음** — reasoning 컬럼은 여전히 TEXT string. 기존 자유 텍스트 reasoning 도 react-markdown 이 plain text 로 정상 렌더.

**Tech Stack:** Markdown (prompt), TypeScript, React 19, react-markdown, Tailwind, lucide-react.

**Spec:** `docs/superpowers/specs/2026-05-19-llm-prompt-improvements-design.md`

---

## ⚙️ Goal State

다음 모두 충족 시 종료:

1. 모든 task 체크박스 완료
2. `prompts/analyze_chart_v3.md` 에 새 패턴 4개 정의 + pivot_basis 표 확장 + enum 확장 + §6/§7 reasoning 가이드 재작성
3. `web/package.json` 에 react-markdown 의존성 등록
4. `ClassificationsPage.tsx` 의 reasoning 박스가 react-markdown 사용
5. `PATTERN_DESCRIPTIONS` 에 새 패턴 4개 한국어 tooltip
6. Frontend tsc 0 errors
7. Backend 회귀 — 영향 없음 (코드 변경 없음)
8. **사용자 수동 검증:**
   - 기존 reasoning (자유 텍스트) 깨지지 않고 정상 렌더
   - 신규 LLM 분류 실행 시 reasoning 이 markdown 5섹션 형식
9. `git status` clean

---

## 사전 조건

- HEAD: `8995f70` (spec commit) 또는 이후
- 기존 `ClassificationsPage` 정상 동작 (Tooltip 패턴 / RowDetails 의 reasoning 박스 등)
- npm 설치 가능 (web 디렉토리)

---

## Task 1: Prompt 본문 수정 — `prompts/analyze_chart_v3.md`

**File:**
- Modify: `prompts/analyze_chart_v3.md`

5개 변경 (모두 한 파일):
1. §4 본문에 새 패턴 4개 정의 추가
2. §4 의 pivot_basis 매핑 표 확장
3. §7 응답 schema 의 pattern enum 확장
4. §7 의 reasoning 가이드 재작성 (markdown 5섹션 + 자수 + 톤)
5. (선택) §6 의 연관 부분 보정

### Step 1: 파일 구조 파악

```bash
grep -n "^### \|^## " /Users/hank.es/git/personal/kr-by-claude/prompts/analyze_chart_v3.md | head -30
```

§4 (Pattern Recognition), §5 (Risk Flags), §6 (Stock-Level Distribution Check, three inviolable rules), §7 (응답 schema) 위치를 line 번호로 확인.

핵심 위치:
- §4 의 pivot_basis 매핑 표: 약 line 138 (`| pattern         | pivot_price ...`)
- §4 의 "Discipline rule" 줄 (line 105 근처) — 새 패턴 4개 추가 위치는 이 줄 직전
- §7 의 `"pattern": "flat_base | cup_with_handle | vcp | double_bottom | none"` 줄 (약 line 229)
- §7 의 `reasoning: max 500 characters` 줄 (약 line 245)

### Step 2: 새 패턴 4개 정의 추가 (§4)

§4 의 기존 4개 (flat_base / cup_with_handle / vcp / double_bottom) 정의 다음, "Discipline rule" 직전에 다음 4개 정의 삽입.

먼저 §4 의 마지막 패턴 정의 ~ Discipline rule 위치를 정확히 찾기:

```bash
grep -n "Discipline rule" /Users/hank.es/git/personal/kr-by-claude/prompts/analyze_chart_v3.md
```

그 line 직전에 다음 markdown 블록 삽입:

```markdown
**`high_tight_flag`** — A rare and powerful pattern. **Flagpole**: stock advances 100–120%+ in **4–8 weeks**. **Flag**: sideways consolidation of no more than 25% over **3–6 weeks**. Total duration 7–14 weeks. Difficult to interpret accurately — use only with high confidence. Risk_flag `narrow_base` does NOT apply to this pattern (the flag period is intentionally short by definition). Source: O'Neil HMM 'High Tight Flag' / Minervini Power Play.

**`3c_cheat`** — **Early entry pivot** in the **lower or middle third of a cup that has not yet completed** (Minervini's "3-C" or "cheat area"). Same cup-with-handle structure, but the buy point is earlier than the standard handle pivot. Lower volume requirement than standard breakout. In `reasoning`, explicitly note "3-C / cheat early entry within cup". Source: Minervini *Trade Like a Stock Market Wizard* ch.10 / *Think & Trade Like a Champion* ch.7.

**`base_on_base`** — First base breaks out and advances but is **unable to increase a normal 20–30%** because the general market begins another leg down. Stock builds a **second consolidation just on top of the previous base**. Strong signal during **latter stages of a bear market** — aggressive new leadership in the next bull phase. Second base typically 5–15 weeks. Source: O'Neil HMM 'Base on Top of a Base'.

**`ascending_base`** — **Three pullbacks of 10–20%**, each low point being **higher than the preceding one**. Forms over 9–16 weeks while the **general market is declining** — indicates a leadership stock relatively immune to market pressure. Source: O'Neil HMM 'Ascending Base'.

```

### Step 3: pivot_basis 매핑 표 확장 (§4)

기존 표 (약 line 138):

```
| pattern         | pivot_price                       | pivot_basis     |
|---|---|---|
| flat_base       | top of base                       | high_of_base    |
| cup_with_handle | top of handle                     | top_of_handle   |
| vcp             | top of final contraction          | top_of_contraction |
| double_bottom   | top of W middle peak              | middle_peak_of_w |
| none            | null                              | null            |
```

(실제 표 컬럼 구분자 / row 순서는 파일 그대로 보존하면서 4 row 추가.)

`double_bottom` row 다음, `none` row 직전에 4개 row 삽입:

```
| high_tight_flag | top of flag (highest point of consolidation)  | top_of_flag       |
| 3c_cheat        | high of cheat area (low/mid cup pivot)        | cheat_pivot       |
| base_on_base    | top of second (upper) base                    | top_of_upper_base |
| ascending_base  | top of third pullback peak                    | top_of_third_peak |
```

### Step 4: §7 응답 schema 의 pattern enum 확장

기존 줄 (약 line 229):

```
  "pattern": "flat_base | cup_with_handle | vcp | double_bottom | none",
```

변경 후:

```
  "pattern": "flat_base | cup_with_handle | vcp | double_bottom | high_tight_flag | 3c_cheat | base_on_base | ascending_base | none",
```

### Step 5: §7 의 pattern enum 검증 줄 확장

§7 의 "pattern: must be exactly one of: ..." 줄 (약 line 246):

기존:
```
- `pattern`: must be exactly one of: `flat_base`, `cup_with_handle`, `vcp`, `double_bottom`, `none`.
```

변경 후:
```
- `pattern`: must be exactly one of: `flat_base`, `cup_with_handle`, `vcp`, `double_bottom`, `high_tight_flag`, `3c_cheat`, `base_on_base`, `ascending_base`, `none`.
```

### Step 6: §7 의 reasoning 가이드 재작성

기존 (약 line 245):

```
- `reasoning`: max 500 characters. Concise, factual, references specific numbers when possible. Must mention market context status, base structure, pivot/breakout if applicable, and key flags. If pocket pivot entry, mark it explicitly.
```

전체를 다음 블록으로 교체:

````markdown
- `reasoning`: **max 1500 characters**. Written in **Korean** using **markdown** with **5 mandatory sections** in this exact order. Each section is a `**Heading**` (bold) followed by a paragraph (no `#` heading marks — only bold).

  Required section order and contents:

  ```
  **시장 컨텍스트**
  KOSPI/KOSDAQ 추세 단계 (confirmed_uptrend / under_pressure / correction 등),
  distribution day 카운트, follow-through day, 200d MA breadth 비율.
  한 줄 결론 — 종목 진입에 우호적/불리 평가.

  **Base 구조**
  식별한 base 패턴 + 형성 기간 + depth + pivot 가격.
  수치 인용 시 의미 부연 (예: "depth 8.5% — Minervini 안정 base 기준 15% 이내, 매물 소화 양호").
  RS Line 의 leadership 여부 (52w high 갱신 전후 시기).

  **진입 시그널**
  거래량 동반 돌파 / pocket pivot / breakout 발생 여부.
  없으면 "미확인" 으로 명시.
  거래량 비율 인용 시 책 기준 (O'Neil 1.5×) 과 비교.

  **핵심 위험**
  risk_flags 각각이 왜 발생했는지 + 그 의미 + 진입 시 대응
  (예: "late_stage_base — 3번째 base, 진입 시 손절 폭을 평소보다 좁히는 것이 안전").

  **결론**
  classification 결정 이유 + 향후 시나리오
  (예: "watch — 돌파 확인 시 entry 승격, 시장 약화 시 ignore 강등").
  ```

  Tone & style:
  - 친절하고 명료한 한국어. **투자 경험 1~3년차 개인투자자가 이해할 수 있게**.
  - 단순 수치만 적지 말고 **그 의미** 함께 (예: 'depth 8.5%' → 'depth 8.5% (15% 임계 이내, 안정적)').
  - Stage 2 / base count / pocket pivot 같은 전문 용어 사용 시 **한 줄 부연 설명**.
  - 결론만 적지 말고 **왜 그렇게 분류했는지 추론 과정** 명시.
  - 각 판단의 책 원전 (예: "Minervini Trend Template #5", "O'Neil HMM 'Cup with Handle'") 짧게 언급.
  - If pocket pivot entry, mark it explicitly in '진입 시그널'.
  - If 3-C / cheat early entry, mark it explicitly in '진입 시그널' or '결론'.
````

### Step 7: §6 의 inviolable rule 보정

§6 의 "Reasoning ↔ flags consistency" 규칙은 현행 유지하되, "reasoning" 이 markdown 임을 명시:

기존 (예시 — 정확 위치는 파일 확인):
```
2. **Reasoning ↔ flags consistency**: If your `reasoning` names a risk (e.g., "climax run", "wide-and-loose", "extended from MA", "market in correction"), the corresponding flag MUST appear in `risk_flags`.
```

변경 후 (한 줄 추가):
```
2. **Reasoning ↔ flags consistency**: If your `reasoning` (across all 5 markdown sections) names a risk (e.g., "climax run", "wide-and-loose", "extended from MA", "market in correction"), the corresponding flag MUST appear in `risk_flags`.
```

### Step 8: 변경 검증

```bash
cd /Users/hank.es/git/personal/kr-by-claude
grep -c "high_tight_flag\|3c_cheat\|base_on_base\|ascending_base" prompts/analyze_chart_v3.md
```

Expected: 8+ matches (각 패턴이 §4 정의 + §7 enum 2곳 + pivot_basis 표 등에 등장).

```bash
grep -c "1500\|markdown\|5 mandatory sections" prompts/analyze_chart_v3.md
```

Expected: 3+ matches (reasoning 가이드 키워드).

### Step 9: Commit

```bash
cd /Users/hank.es/git/personal/kr-by-claude
git add prompts/analyze_chart_v3.md
git commit -m "feat(prompt): 새 패턴 4개 + reasoning markdown 5섹션 + 1500자 + 친절 톤"
```

**NEVER add `Co-Authored-By: Claude` trailer.**

---

## Task 2: Frontend — react-markdown 의존성 + ClassificationsPage

**Files:**
- Modify: `web/package.json` (자동), `web/package-lock.json` (자동)
- Modify: `web/src/pages/ClassificationsPage.tsx`

### Step 1: react-markdown 설치

```bash
cd /Users/hank.es/git/personal/kr-by-claude/web
npm install react-markdown
```

설치 후 `package.json` 의 dependencies 에 `react-markdown` 추가 확인:

```bash
grep "react-markdown" package.json
```

Expected: `"react-markdown": "^9.x.x"` 또는 비슷 (가장 최신 호환 버전).

### Step 2: ClassificationsPage 의 import + 컴포넌트 변경

`web/src/pages/ClassificationsPage.tsx` 파일 상단의 import 블록에 ReactMarkdown 추가:

```tsx
import ReactMarkdown from "react-markdown";
```

(기존 import 들 다음 줄 또는 logical 위치.)

### Step 3: RowDetails 의 reasoning 박스 교체

`function RowDetails(...)` 안의 reasoning 박스 부분을 찾기:

```tsx
{row.reasoning && (
  <div>
    <div className="caps text-faint mb-1">Reasoning</div>
    <div className="text-data text-ink whitespace-pre-wrap bg-paper border border-hairline rounded-lg p-3 max-h-64 overflow-auto leading-relaxed">
      {row.reasoning}
    </div>
  </div>
)}
```

전체를 다음으로 교체:

```tsx
{row.reasoning && (
  <div>
    <div className="caps text-faint mb-1">Reasoning</div>
    <div className="text-data text-ink bg-paper border border-hairline rounded-lg p-3 max-h-96 overflow-auto leading-relaxed">
      <ReactMarkdown
        components={{
          p: ({ node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
          strong: ({ node, ...props }) => (
            <strong className="font-semibold text-ink block mt-3 first:mt-0" {...props} />
          ),
          ul: ({ node, ...props }) => <ul className="list-disc ml-5 my-1" {...props} />,
          ol: ({ node, ...props }) => <ol className="list-decimal ml-5 my-1" {...props} />,
          code: ({ node, ...props }) => (
            <code className="font-mono bg-cream px-1 rounded text-data-xs" {...props} />
          ),
        }}
      >
        {row.reasoning}
      </ReactMarkdown>
    </div>
  </div>
)}
```

핵심 변경:
- `whitespace-pre-wrap` 제거 (ReactMarkdown 이 단락 처리)
- `max-h-64` → `max-h-96` (1500자 대응)
- `<ReactMarkdown components={...}>` 래퍼 + 5개 element 스타일 매핑
- `strong` 을 `block + mt-3` 로 변환 → markdown `**heading**` 이 시각적으로 헤딩처럼 보임

### Step 4: PATTERN_DESCRIPTIONS 에 4개 추가

`web/src/pages/ClassificationsPage.tsx` 의 `PATTERN_DESCRIPTIONS` 상수 (약 line 52~63) 에 새 패턴 4개 추가.

기존 마지막 entry (`none`) 다음 + closing `}` 직전 위치에 추가:

```typescript
const PATTERN_DESCRIPTIONS: Record<string, string> = {
  flat_base:
    "5~7주 횡보 통합, depth ≤15% — Cup-with-handle 이후 자주 등장하는 2차 base (Box 형태).",
  cup_with_handle:
    "U자 컵 (12~33% 조정, 깊으면 50%까지) + cup 상반부에 형성된 짧은 손잡이 (8~12% pullback), 7주~수개월. O'Neil 의 가장 흔한 정통 패턴.",
  vcp:
    "Volatility Contraction Pattern — 변동성과 거래량이 단계적으로 줄어드는 통합 (Minervini).",
  double_bottom:
    "W 형태 이중 바닥. 두 번째 저점이 첫 저점을 살짝 undercut(shakeout). Buy point 는 W 중앙 peak (top of middle peak, 우측). 두 번째 바닥에서 매수는 너무 이름.",
  none:
    "Base 패턴 식별되지 않음.",
  high_tight_flag:
    "4~8주에 가격 100~120%+ 상승(깃대) 후 3~6주간 25% 이내 횡보(깃발) — 매우 강한 매수 신호 (드문 패턴, O'Neil HMM 'High Tight Flag' / Minervini Power Play).",
  "3c_cheat":
    "Cup이 완성되기 전 중·하반부에서 형성되는 cheat 영역의 early entry pivot (Minervini Trade Like a Stock Market Wizard ch.10 / Think & Trade Like a Champion ch.7).",
  base_on_base:
    "1차 base 돌파 후 20~30% 상승 못 하고 위쪽에 2차 base 형성. Bear market 막판 강세 신호 (O'Neil HMM 'Base on Top of a Base').",
  ascending_base:
    "3번의 10~20% pullback이 점점 더 높은 저점에서 발생. 시장 약세기에 강한 종목 (O'Neil HMM 'Ascending Base').",
};
```

**참고:** `3c_cheat` 는 JavaScript identifier 가 숫자로 시작 못 해서 따옴표 (`"3c_cheat":`) 필수.

### Step 5: tsc

```bash
cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

만약 react-markdown 의 타입 에러가 나면 (예: `components` prop 의 children/node 타입), 해당 위치만 보정. 일반적으로 react-markdown v9+ 는 TypeScript 지원 잘 됨.

### Step 6: Commit

```bash
cd /Users/hank.es/git/personal/kr-by-claude
git add web/package.json web/package-lock.json web/src/pages/ClassificationsPage.tsx
git commit -m "feat(classifications): reasoning 박스 react-markdown 렌더 + 새 패턴 4개 tooltip"
```

---

## Task 3: Goal State 검증

- [ ] **Step 1: Frontend tsc**

```bash
cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 2: Backend 회귀 (영향 없음 확인)**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
uv run pytest 2>&1 | tail -3
```

Expected: 기존 passed 그대로. 신규 failure 없음 (prompt + frontend 변경만이라 backend 무관).

- [ ] **Step 3: 기존 reasoning 호환성 확인 (브라우저)**

```bash
pkill -f "uvicorn api.main" 2>/dev/null; sleep 1
cd /Users/hank.es/git/personal/kr-by-claude
uv run uvicorn api.main:app --port 8000 --log-level warning > /tmp/uvicorn.log 2>&1 &
sleep 3
```

`http://localhost:5173/classifications` 진입 → 기존 65 row 중 아무거나 expand → reasoning 박스가 plain text 단락으로 정상 렌더 (markdown 헤딩 없는 옛 분류).

- [ ] **Step 4: 신규 분류로 markdown 형식 검증 (사용자 수동)**

`/runner` → "LLM 주말 분류" → **"테스트 (N개만 실제 호출)"** → limit=2 또는 3 정도로 실행.

종료 후 `/classifications` 에서 새 분류 row expand:

1. Reasoning 박스에 5개 **굵게** 헤딩 (시장 컨텍스트 / Base 구조 / 진입 시그널 / 핵심 위험 / 결론) 표시
2. 각 헤딩 아래 친절한 한국어 설명 (수치 + 의미)
3. 자수가 이전보다 풍부 (~1000~1500자)
4. 책 원전 언급 (Minervini / O'Neil)
5. (운 좋으면) 새 패턴 4개 중 하나 (high_tight_flag / 3c_cheat / base_on_base / ascending_base) 출현 — pattern 텍스트 hover 시 tooltip 정상

- [ ] **Step 5: git status**

```bash
git status
```

Expected: clean working tree (untracked `.claude/` 제외).

---

## Self-Review

✅ **Spec coverage**:
- 1-1. §4 패턴 4개 추가 → Task 1 Step 2
- 1-2. pivot_basis 매핑 표 확장 → Task 1 Step 3
- 1-3. §7 응답 schema enum 확장 → Task 1 Step 4 + Step 5
- 1-4. §6/§7 reasoning 가이드 재작성 → Task 1 Step 6 + Step 7
- 2-1. react-markdown 의존성 추가 → Task 2 Step 1
- 2-2. ClassificationsPage reasoning 박스 markdown 렌더 → Task 2 Step 2-3
- 2-3. PATTERN_DESCRIPTIONS 4개 추가 → Task 2 Step 4
- 3. 기존 데이터 호환 → Task 3 Step 3 (수동 검증)
- 4. 파일 변경 요약 — 명시
- 5. Testing → Task 3
- 6. Out of scope — spec 의 6번 그대로 (LLM evaluation, risk_flag, backfill 등 명시적 제외)

✅ **Placeholder scan**: TBD/TODO 없음. 모든 변경 코드 + 명령 + 기대 출력 명시.

✅ **Type consistency**:
- 새 패턴 4개 이름 — 모든 위치 일관 (`high_tight_flag`, `3c_cheat`, `base_on_base`, `ascending_base`) — Task 1 Step 2/3/4/5 + Task 2 Step 4
- `3c_cheat` 따옴표 표기 — Task 2 Step 4 에 명시
- pivot_basis 새 값들 — VARCHAR(30) 컬럼 한도 내 (`top_of_upper_base` 17자 등) ✓
- react-markdown 의 components prop 타입 — Task 2 Step 3 의 code 예시 그대로

⚠️ **알려진 한계**:
- LLM 이 매번 markdown 5섹션 헤딩 형식을 100% 따른다는 보장 없음 (90~95% 추정). 일부 케이스에서 헤딩 누락 가능 — react-markdown 이 plain text 도 렌더하므로 깨지지 않음.
- 새 패턴 4개의 출현은 드물 수 있음 — 특히 `high_tight_flag` (100%+ 상승 + 횡보) 와 `ascending_base` (시장 약세기). 검증 시 출현 안 할 수 있음.
- `react-markdown` v9 의 components prop 시그니처가 자주 바뀜 — tsc 에러 시 그 시점 버전 docs 확인.
