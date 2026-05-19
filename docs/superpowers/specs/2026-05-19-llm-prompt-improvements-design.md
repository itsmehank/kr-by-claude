# LLM 분류 prompt 개선 (B 사이클) Design

**Goal:** `prompts/analyze_chart_v3.md` 의 reasoning 출력 형식을 markdown 5섹션 구조로 + 자수 1500자 + 친절한 톤으로 변경. 새 base 패턴 4개 (high_tight_flag / 3c_cheat / base_on_base / ascending_base) 추가. Frontend 가 reasoning 을 markdown 으로 렌더.

**Scope:** prompt 본문 재작성 + frontend reasoning 렌더 + PATTERN_DESCRIPTIONS 확장. **DB schema / Pydantic / API router / backend store 코드 변경 없음** (`reasoning` 은 여전히 TEXT string).

**Single source of truth:** `prompts/analyze_chart_v3.md`. Frontend dict (PATTERN_DESCRIPTIONS) 와 일관 유지.

---

## 1. Prompt 변경 — `prompts/analyze_chart_v3.md`

### 1-1. §4 (Pattern Recognition) — 새 패턴 4개 추가

기존 4개 (`flat_base / cup_with_handle / vcp / double_bottom`) + 신규 4개:

| 패턴 | 영문 정의 (prompt 본문) | 한국어 요약 (frontend tooltip) |
|---|---|---|
| `high_tight_flag` | A rare and powerful pattern. **Flagpole**: stock advances 100-120%+ in **4-8 weeks**. **Flag**: sideways consolidation of no more than 25% over **3-6 weeks**. Total duration 7-14 weeks. Hard to interpret — use only with high confidence. (O'Neil HMM 'High Tight Flag' / Minervini Power Play) | 4~8주에 가격 100~120%+ 상승(깃대) 후 3~6주간 25% 이내 횡보(깃발) — 매우 강한 매수 신호 (드문 패턴, O'Neil HMM 'High Tight Flag' / Minervini Power Play). |
| `3c_cheat` | **Early entry pivot** in the **lower or middle third of a cup that has not yet completed**. Minervini's "3-C" or "cheat area" — same cup-with-handle structure, but the buy point is earlier than the standard handle pivot. Lower volume requirement (vs standard breakout). (Minervini *Trade Like a Stock Market Wizard* ch.10 / *Think & Trade Like a Champion* ch.7) | Cup이 완성되기 전 중·하반부에서 형성되는 cheat 영역의 early entry pivot (Minervini Trade Like a Stock Market Wizard ch.10 / Think & Trade Like a Champion ch.7). |
| `base_on_base` | First base breaks out and advances but is **unable to increase a normal 20-30%** because the general market begins another leg down. Stock builds a **second consolidation just on top of the previous base**. Strong signal during **latter stages of a bear market** — aggressive new leadership in the next bull phase. Second base typically 5-15 weeks. (O'Neil HMM 'Base on Top of a Base') | 1차 base 돌파 후 20~30% 상승 못 하고 위쪽에 2차 base 형성. Bear market 막판 강세 신호 (O'Neil HMM 'Base on Top of a Base'). |
| `ascending_base` | **Three pullbacks of 10-20%**, each low point being **higher than the preceding one**. Forms over 9-16 weeks while the **general market is declining** — indicates a leadership stock relatively immune to market pressure. (O'Neil HMM 'Ascending Base') | 3번의 10~20% pullback이 점점 더 높은 저점에서 발생. 시장 약세기에 강한 종목 (O'Neil HMM 'Ascending Base'). |

**§4 본문 추가 위치:** 기존 패턴 정의 다음, "Discipline rule" 줄 직전.

### 1-2. §4 의 pivot_basis 매핑 (현 line 138 표 확장)

```
| pattern         | pivot_price                       | pivot_basis              |
|-----------------|-----------------------------------|--------------------------|
| flat_base       | top of base (high of consolidation) | high_of_base           |
| cup_with_handle | top of handle                       | top_of_handle          |
| vcp             | top of final contraction            | top_of_contraction     |
| double_bottom   | top of W middle peak                | middle_peak_of_w       |
| high_tight_flag | top of flag (highest point of consolidation) | top_of_flag    |
| 3c_cheat        | high of cheat area (low/mid cup pivot)        | cheat_pivot    |
| base_on_base    | top of second (upper) base                    | top_of_upper_base |
| ascending_base  | top of third pullback peak                    | top_of_third_peak |
| none            | null                                | null                     |
```

### 1-3. §7 응답 schema — pattern enum 확장

기존:
```
"pattern": "flat_base | cup_with_handle | vcp | double_bottom | none"
```

변경:
```
"pattern": "flat_base | cup_with_handle | vcp | double_bottom | high_tight_flag | 3c_cheat | base_on_base | ascending_base | none"
```

### 1-4. §6 / §7 — reasoning 작성 가이드 재작성

#### 기존 (§7):
> `reasoning`: max 500 characters. Concise, factual, references specific numbers when possible. Must mention market context status, base structure, pivot/breakout if applicable, and key flags. If pocket pivot entry, mark it explicitly.

#### 변경 후:

> `reasoning`: **max 1500 characters**. Written in **markdown** with **5 mandatory sections** in this exact order, each as a `**Heading**` followed by a paragraph:
>
> ```
> **시장 컨텍스트**
> KOSPI/KOSDAQ 추세 단계, distribution day 카운트, follow-through day, 200d MA breadth.
> 한 줄 결론 — "종목 진입에 우호적/불리".
>
> **Base 구조**
> 식별한 base 패턴 + 형성 기간 + depth + pivot 가격. 수치 인용 시 의미 부연
> (예: "depth 8.5% — Minervini 안정 base 기준 15% 이내, 매물 소화 양호").
> RS Line leadership 여부 (52w high 갱신).
>
> **진입 시그널**
> 거래량 동반 돌파 / pocket pivot / breakout 발생 여부. 없으면 "미확인".
> 거래량 비율을 책 기준 (O'Neil 1.5×) 과 비교.
>
> **핵심 위험**
> risk_flags 각각이 왜 발생했는지 + 그 의미 + 진입 시 대응
> (예: "late_stage_base — 3번째 base, 진입 시 손절 폭 좁히기").
>
> **결론**
> classification 결정 이유 + 향후 시나리오
> (예: "watch — 돌파 확인 시 entry 승격, 시장 약화 시 ignore 강등").
> ```
>
> **Tone & style:**
> - 친절하고 명료한 한국어. **투자 경험 1~3년차 개인투자자가 이해할 수 있게**.
> - 단순 수치만 적지 말고 **그 의미** 함께 (예: 'depth 8.5%' → 'depth 8.5% (15% 임계 이내)').
> - Stage 2 / base count / pocket pivot 같은 전문 용어 사용 시 **한 줄 부연**.
> - 결론만 적지 말고 **왜 그렇게 분류했는지 추론 과정** 명시.
> - 각 판단의 책 원전 (Minervini ch.N / O'Neil HMM 'XXX') 짧게 언급.
> - If pocket pivot entry, mark it explicitly in '진입 시그널'.

### 1-5. §6 의 기존 "분류 시 reasoning 일관성 규칙" 보정

기존 규칙:
> 2. **Reasoning ↔ flags consistency**: If your `reasoning` names a risk ... the corresponding flag MUST appear in `risk_flags`.

→ 그대로 유지 (markdown 안에서도 동일).

---

## 2. Frontend — `web/src/pages/ClassificationsPage.tsx`

### 2-1. Reasoning 렌더 — react-markdown

#### 의존성

```bash
cd web && npm install react-markdown
```

(약 60KB minified, 표준 markdown 렌더러.)

#### 컴포넌트 변경

기존:
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

변경 후:
```tsx
import ReactMarkdown from "react-markdown";

{row.reasoning && (
  <div>
    <div className="caps text-faint mb-1">Reasoning</div>
    <div className="text-data text-ink bg-paper border border-hairline rounded-lg p-3 max-h-96 overflow-auto leading-relaxed">
      <ReactMarkdown
        components={{
          p: ({ node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
          strong: ({ node, ...props }) => <strong className="font-semibold text-ink block mt-3 first:mt-0" {...props} />,
          ul: ({ node, ...props }) => <ul className="list-disc ml-5 my-1" {...props} />,
          ol: ({ node, ...props }) => <ol className="list-decimal ml-5 my-1" {...props} />,
          code: ({ node, ...props }) => <code className="font-mono bg-cream px-1 rounded text-data-xs" {...props} />,
        }}
      >
        {row.reasoning}
      </ReactMarkdown>
    </div>
  </div>
)}
```

**핵심 디자인 결정:**
- `strong` (= `**heading**`) 을 `block + mt-3` 로 변환 → 자동으로 헤딩처럼 보임 (현재 prompt 가 `**시장 컨텍스트**` 같은 형태 출력)
- `p` 는 `mb-2` 로 단락 구분
- max-h: 64 → **96** (1500자 대응)
- `whitespace-pre-wrap` 제거 — react-markdown 이 단락 처리

**기존 행 (자유 텍스트, 헤딩 없는 reasoning) 도 정상 렌더** — react-markdown 이 plain text 를 그대로 단락으로 처리.

### 2-2. PATTERN_DESCRIPTIONS 확장 (4개 추가)

기존 5개 + 신규 4개:

```typescript
const PATTERN_DESCRIPTIONS: Record<string, string> = {
  flat_base: "...",          // 기존
  cup_with_handle: "...",    // 기존
  vcp: "...",                // 기존
  double_bottom: "...",      // 기존
  none: "...",               // 기존

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

**`3c_cheat` 의 키:** TypeScript object literal 에서 숫자로 시작하는 키는 따옴표 필수 → `"3c_cheat"` 표기.

---

## 3. 기존 데이터 호환

- **기존 65건의 reasoning** (자유 텍스트, 헤딩 없음): react-markdown 이 plain text 그대로 단락으로 렌더. **깨지지 않음.**
- **새 분류부터 5섹션 markdown** 적용.

---

## 4. 파일 변경 요약

| 파일 | 변경 |
|---|---|
| `prompts/analyze_chart_v3.md` | §4 패턴 4개 추가 + pivot_basis 표 확장 + §6/§7 reasoning 가이드 재작성 |
| `web/package.json` + `web/package-lock.json` | `react-markdown` 의존성 추가 |
| `web/src/pages/ClassificationsPage.tsx` | reasoning 박스 ReactMarkdown 적용 + PATTERN_DESCRIPTIONS 4개 추가 |

(DB / Pydantic / API router / Backend 코드 변경 **없음**.)

---

## 5. Testing

### Backend

- prompt 자체는 직접 unit test 안 함 (codebase 패턴).
- 신규 패턴 enum 추가는 prompt 안의 텍스트라 별도 test 없음.

### Frontend

- `tsc --noEmit` 0 errors

### 사용자 수동 검증 (Goal State 일부)

1. **기존 reasoning (자유 텍스트) 호환:** `/classifications` 진입 → 기존 65건의 row expand → reasoning 박스가 깨지지 않고 plain text 단락으로 정상 표시.
2. **신규 분류 markdown 형식:** `/runner` → "LLM 주말 분류" → "테스트 (N개만)" → 3 종목 실행 → 새 reasoning 이 5섹션 markdown 형식 (헤딩 + 본문) 으로 표시.
3. **새 패턴 출현:** LLM 이 신규 4 패턴 중 하나를 분류하면 PATTERN_DESCRIPTIONS tooltip 정상 표시 (pattern 텍스트 hover).
4. **자수 1500:** 신규 reasoning 이 이전보다 풍부 (수치 + 의미 부연 + 추론 과정 + 책 원전).

---

## 6. Out of scope

- **LLM evaluation suite** (golden set 비교 / 자동 검증) — 미래 작업
- **새 risk_flag 추가** — 이번 검토에서 제안 없음
- **기존 reasoning backfill** (자유 텍스트 → markdown 변환) — 의미 추출 불가능, 신규부터 적용
- **`pattern_pivot` 매핑 backend 검증** — prompt 안 표만 변경, code 변경 없음 (DB 의 pivot_basis 는 LLM 자유 텍스트)
- **`pivot_basis` 컬럼 enum 화** — VARCHAR(30) 그대로

---

## Architecture summary

```
prompts/analyze_chart_v3.md  (수정)
  + §4 pattern 4개 (high_tight_flag / 3c_cheat / base_on_base / ascending_base)
  + §4 pivot_basis 매핑 표 확장
  + §6/§7 reasoning 가이드 (markdown 5섹션 + 자수 1500 + 친절 톤)
        │
        ▼ (LLM 호출 시)
weekly_classification.reasoning (TEXT, 컬럼 변경 없음)
        │
        ▼ (API 변경 없음)
GET /api/classifications → reasoning string 그대로
        │
        ▼
ClassificationsPage 의 reasoning 박스
  + react-markdown 으로 렌더 (heading → block strong, paragraph spacing)
  + 기존 자유 텍스트는 plain text 로 정상 표시
  + PATTERN_DESCRIPTIONS 9개 (기존 5 + 신규 4)
```
