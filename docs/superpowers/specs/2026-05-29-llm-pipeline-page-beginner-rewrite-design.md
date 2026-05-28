# LLM 분석 안내 페이지 — 초보 친화 리팩토링 (Design Spec)

- **상태**: Design
- **작성일**: 2026-05-29
- **범위**: `web/src/pages/LlmPipelinePage.tsx` + 데이터 파일들. audit 페이지 미수정.
- **다음 단계**: 이 spec → `writing-plans` → 구현.

## 1. 배경 및 목적

`LlmPipelinePage.tsx` 의 `StageCard` 5 개에 *초보가 모를* jargon 이 다수 (사용자 지적 3 사례 + audit 결과 진단 3 항 — `2026-05-28 P0/P1/SSOT chain` 직후 확인). 핵심 증상:

- **데이터 모델의 침묵**: 11 테이블이 *한 줄 설명 없이* 칩으로만 등장.
- **목록 약속 후 미공개**: *"8 조건/13 ZIP/9 base 패턴/13 risk flag/17 필드"* 의 숫자만 던지고 실제 목록 미공개.
- **SQL/엔지니어링 누출**: `ON CONFLICT DO NOTHING`, `DISTINCT ON`, `PK: ...` 가 사용자 콘텐츠에 직접 노출.

**목적**: 페이지를 *주식 1~3년차 + 시스템 초보* 가 한 화면에서 *전체 흐름과 의미* 를 이해하도록 친절화. 전문가용 raw 정보는 fold-out 으로 보존하여 *전문가도 1 click 으로 도달*. drift 차단을 위해 audit 데이터 source 를 직접 import.

## 2. 청자 (Audience)

- **기본**: 주식 1~3년차 개인투자자 (`prompts/analyze_chart_v3.md:305` 의 암묵적 청자와 일치 — *"투자 경험 1~3년차 개인투자자가 이해할 수 있게"*).
- **풀이 대상**: 책 용어 (Trend Template, pivot, pocket pivot, distribution day, base pattern 등) + 시스템 jargon (테이블 이름, prompt, decision, SQL 등).
- **풀이 비대상 (안다 가정)**: OHLCV, 이동평균(SMA), 거래량 평균 같은 *기본 주식 지식*.

## 3. Scope

### 포함
- `LlmPipelinePage.tsx` 의 `StageCard` 5 개 전수 친절화 + targeted fold 다수 도입.
- 외부 섹션 풀 친절화:
  - mermaid 다이어그램 2 개 (개요·상태) — 노드명 한국어 친절화.
  - `TriggerDecisionMatrix` 3×3 셀 — 친절 논조 재작성 + 일상어 비유.
  - `Glossary` — 주식·책 용어 30+ 종으로 확장 (테이블·SQL 은 카드 fold 소관, 여기엔 제외).
  - `FAQ` 7 답변 친절화 (질문은 보존).
- 카드 fold 의 데이터 source 단일화 — 기존 `web/src/data/llm-pipeline-audit/*.ts` 를 import (drift 차단).

### 제외 (별도 사이클)
- 시뮬레이션 **모달 콘텐츠** 재작성 (시뮬레이션 매트릭스 자체는 보존, 외곽 텍스트만 친절화).
- audit 페이지 변경 (이미 line-by-line 권위 source).
- 신규 페이지·라우트.
- prompt 또는 임계 상수 변경.

## 4. 책임 분리 (Page boundary)

- **pipeline 페이지** (본 spec) — *"어떻게 동작하나"* 친절한 산문 + 자기완결 fold.
- **audit 페이지** — *"왜 그렇게 했나, 책 어느 줄?"* 권위 source. 변경 없음.
- **drift 차단**: pipeline fold 콘텐츠는 **기존 audit 데이터 source 를 직접 import** — `web/src/data/llm-pipeline-audit/risk-flags.ts`, `base-patterns.ts`, `stages.ts`, `minervini.ts` 등. 어느 한 곳을 고쳐도 양 페이지 자동 동기화. 본 작업으로 새 데이터 source 를 만들지 않으며, *기존 source 에 없는 새 정보* (예: 11 테이블 한 줄 설명, 17 필드 풀이) 는 신규 source 파일 1~2 개로 분리해 동일한 import 패턴.

## 5. 페이지 구조 (Architecture)

8 섹션 구조 보존. 각 섹션의 변경 범위:

| § | 섹션 | 변경 |
|---|---|---|
| 1 | Header (제목 + 한 줄 요약) | 한 줄 요약 친절화 (jargon 제거) |
| 2 | `<details>` 안내 박스 | 보존, 미세 정련 |
| 3 | 개요 (4단계 mermaid) | mermaid 노드명 한국어 친절화 + "이 그림 읽는 법" 한 단락 |
| 4 | `StageCard` × 5 | **핵심 영역** — 본문 친절화 + targeted fold 다수 |
| 5 | 1주일 시뮬레이션 매트릭스 | 외곽 안내 텍스트만 친절화 (모달은 비범위) |
| 6 | 상태 전이도 (mermaid) | 노드명 한국어 친절화 + 라벨 친절화 |
| 7 | TriggerDecisionMatrix (3×3) | 셀 본문 친절 논조 재작성, 일상어 비유 |
| 8 | Glossary | 12 → 30+ 용어 (주식·책 전용) |
| 9 | FAQ | 답변 친절화 (질문 보존) |

### 5.1 StageCard 내부 구조 (재설계)

```
┌─ § order / id  | label ─────────────────────────────┐
│                                                       │
│ 친절한 산문 한 단락 — 이 단계가 무엇을 왜 하는가         │
│                                                       │
│ 📦 입력 N 테이블                                       │
│   - daily_indicators (한 줄 설명) [▼ 자세히]            │
│   - weekly_indicators (한 줄 설명) [▼]                  │
│   - ... (테이블별 1줄 설명을 카드에서 직접 보임)         │
│                                                       │
│ 📦 출력 M 테이블                                       │
│   - weekly_classification (한 줄 설명) [▼ 컬럼 상세]    │
│                                                       │
│ ⚙️  결정론 룰 한 단락 + 핵심 1-2 조건 친절 풀이          │
│   [▼ 전체 SQL/조건 보기]                                │
│   [▼ Trend Template 8 조건 모두 보기] (해당 카드만)     │
│                                                       │
│ 🧠 AI (LLM) 로직 한 단락                               │
│   [▼ ZIP 13 파일 — AI 가 받는 자료] (해당 카드만)       │
│   [▼ 9 base 패턴] (해당 카드만)                         │
│   [▼ 13 risk flag] (해당 카드만)                        │
│   [▼ 17 매수 계획 필드] (entry_params 카드만)            │
│   AI 의 결정: [entry / watch / ignore] chips            │
│                                                       │
│ ✅ 결과 액션 한 단락 — 친절한 풀이                       │
│   [▼ SQL INSERT 상세]                                  │
│                                                       │
│ 📖 책 근거 chips (유지)                                 │
│ 💻 코드 참조 (유지)                                     │
└───────────────────────────────────────────────────────┘
```

각 fold 는 *해당 카드에서 의미 있는 경우에만* 표시 (예: 17 필드 fold 는 `entry_params` 카드에만).

### 5.2 fold 구현

표준 `<details>` HTML 요소 + Tailwind. 이미 본 페이지 안내 박스에 정착된 패턴 재사용:

```tsx
<details className="group">
  <summary className="cursor-pointer ... bg-tint-stone hover:bg-cream">
    Trend Template 8 조건 모두 보기
    <span className="group-open:hidden">▼</span>
    <span className="hidden group-open:inline">▲</span>
  </summary>
  <div className="mt-2 px-4 py-3 bg-cream border border-hairline rounded-lg">
    {/* fold 내용 — import 된 audit 데이터 사용 */}
  </div>
</details>
```

## 6. 새로 도입될 / 확장될 콘텐츠 카탈로그

각 항목의 *권위 source* 와 *추가 위치*:

| 콘텐츠 | 권위 source | 추가 위치 |
|---|---|---|
| **테이블 11종 한 줄 설명 + 컬럼 상세** | `kr_pipeline/db/schema.sql` (각 `CREATE TABLE` 의 주석 + 컬럼) | 신규 `web/src/data/llm-pipeline/tables.ts` (코드와 분리, 단일 source) |
| **Trend Template 8 조건** | `kr_pipeline/indicators/compute/minervini.py` + `kr_pipeline/common/thresholds.py:34-51` (C3_SMA200_LOOKBACK_DAYS=22, C6_W52LOW_MULT=1.25, C7_W52HIGH_MULT=0.75, C8_RS_RATING_MIN=70) | audit `minervini.ts` import |
| **ZIP 13 파일** | `kr_pipeline/llm_runner/` 의 payload 빌더 (실측으로 13 파일 정확 식별) | 신규 `web/src/data/llm-pipeline/zip-files.ts` 또는 audit `zip-files.ts` 재사용 검토 |
| **9 base 패턴** | `prompts/analyze_chart_v3.md:86-91, 111-117` | audit `base-patterns.ts` import |
| **13 risk flag** | `prompts/analyze_chart_v3.md:183-194` 표 | audit `risk-flags.ts` import |
| **17 entry_params 필드** | `prompts/calculate_entry_params_v2_0.md` §10 validation 표 + builder schema | 신규 `web/src/data/llm-pipeline/entry-params-fields.ts` |
| **주식·책 용어 30+ 종 glossary 확장** | 코드 무관, 본 작업에서 큐레이션 | `LlmPipelinePage.tsx` 내 `GLOSSARY` 상수 확장 |
| **mermaid 노드명 한국어** | 본 작업에서 작성 | 페이지 내 `DIAGRAM_DATA_FLOW`, `DIAGRAM_STATE` 문자열 수정 |
| **trigger / decision 6 용어 친절화** | 본 작업에서 작성 | `TRIGGER_DECISION_MATRIX` 의 `meaning` / `next` 문자열 재작성 |
| **mermaid '이 그림 읽는 법' 단락** | 본 작업에서 작성 | 개요/상태 섹션 본문 |
| **FAQ 답변 친절화** | 본 작업에서 작성 | `FAQ` 상수 답변 재작성 |

## 7. Component 설계 — JSX 변경 단위

`LlmPipelinePage.tsx` 의 기존 컴포넌트와의 매핑:

- `StageCard` 컴포넌트 **재설계** — fold 다수 + 친절 본문 + 테이블 1줄 설명 인라인.
- `TableChip` 컴포넌트 **확장** — hover/click 시 1줄 설명 tooltip 또는 inline 펼침 (작은 옵션). 또는 chip 그대로 두고 카드 안 입력/출력 리스트가 *칩 + 1줄 설명* 형태로 분리.
- `TriggerDecisionMatrix` **본문 재작성** — JSX 구조 동일, `TRIGGER_DECISION_MATRIX` 상수만 친절 논조.
- `Glossary` **확장** — 12 → 30+. 컴포넌트 구조 동일.
- `FaqSection` **답변 재작성** — `FAQ` 상수 답변만 친절 논조. 컴포넌트 구조 동일.

신규 컴포넌트 후보:
- `TableExplainerList` — 카드 안 *"입력 N 테이블 + 각 1줄 설명 + ▼ 컬럼 상세"* 표시.
- `ListFold` — *"X 항목 모두 보기 ▼"* 공통 래퍼 (8 조건/13 ZIP/9 패턴/13 risk/17 필드 공통 사용).

## 8. 데이터 import 패턴 (drift 차단 핵심)

본 spec 의 핵심 설계 원칙 — *데이터 단일 source*:

```tsx
// pipeline 페이지의 StageCard
import { TREND_TEMPLATE_CONDITIONS } from "../data/llm-pipeline-audit/minervini";
import { BASE_PATTERNS } from "../data/llm-pipeline-audit/base-patterns";
import { RISK_FLAGS } from "../data/llm-pipeline-audit/risk-flags";

// 신규 source (audit 에 없는 정보만)
import { TABLE_DESCRIPTIONS } from "../data/llm-pipeline/tables";
import { ENTRY_PARAMS_FIELDS } from "../data/llm-pipeline/entry-params-fields";
```

- 기존 audit source 는 **그대로 사용** — pipeline 페이지의 fold 가 같은 데이터를 친절한 layout 으로 표시.
- audit 페이지가 fold 내용을 갱신하면 pipeline 도 자동 반영.
- `TABLE_DESCRIPTIONS` 와 `ENTRY_PARAMS_FIELDS` 는 양 페이지가 향후 함께 사용할 가능성 — `web/src/data/llm-pipeline/` 디렉토리 신규.

## 9. 친절화 톤 가이드

- **호명 톤**: "이 단계는 ~합니다" 직접체. 사용자에게 말 거는 톤.
- **비유 한도**: 일상어 비유 1-2개 (예: *"AI 가 받는 자료 묶음 = 시험 응시생에게 주는 자료집"*). 비유 남용 금지.
- **약어 정책**: 첫 등장 시 *"OHLCV (시가/고가/저가/종가/거래량)"* 식으로 풀이. 같은 카드 내 재등장은 약어만.
- **숫자 약속의 책임**: *"8 조건"* 이라고 적으면 *그 자리* 에서 fold 펼침으로 도달 가능해야 함. 외부 link 만으로 끝내지 않음.
- **SQL 노출 정책**: 본문에는 SQL 문법 금지. fold 안에서만 명시.

## 10. 검증 / 성공 기준

- **Build**: `npx tsc --noEmit` 0 error.
- **회귀 0**: 기존 페이지의 동작 (시뮬레이션 매트릭스 클릭 → 모달, mermaid 렌더, glossary 표시 등) 모두 유지.
- **내용 정합**: 친절 본문에서 인용된 모든 임계값 / 테이블명 / 함수명 / 책 페이지가 실제 코드/파일과 일치 (spec 자체 검증 시점 + 구현 후 검증).
- **사용자 1차 검증 케이스** (사용자가 처음 지적한 3 케이스 — 통독 후 *fold 펼치지 않고도* 의미가 잡혀야 함):
  - "결정론 필터 — minervini_pass (Trend Template 8조건)"
  - "analyze_chart_v3.md prompt ... ZIP 13개 파일 ..."
  - "weekly_classification 에 INSERT (source='weekend'). ON CONFLICT ..."
- **drift 차단**: 카드 fold 가 *어떤 audit 데이터 source 도 복제하지 않음* — 모두 import.

## 11. 변경 / 신규 파일 목록

### 수정
- `web/src/pages/LlmPipelinePage.tsx` — `STAGES`, `TRIGGER_DECISION_MATRIX`, `GLOSSARY`, `FAQ`, `DIAGRAM_DATA_FLOW`, `DIAGRAM_STATE`, `StageCard`, `TriggerDecisionMatrix`, `FaqSection` 본문.
- `web/src/pages/LlmPipelinePage.tsx` 의 header 한 줄 요약 + 안내 박스 미세 정련.

### 신규
- `web/src/data/llm-pipeline/tables.ts` — 11 테이블 한 줄 설명 + 컬럼 요약.
- `web/src/data/llm-pipeline/entry-params-fields.ts` — 17 필드 풀이.
- (필요 시) `web/src/data/llm-pipeline/zip-files.ts` — audit 의 ZIP 파일과 정합/공유 검토 후 결정.
- `web/src/pages/llm-pipeline/TableExplainerList.tsx` (신규 컴포넌트).
- `web/src/pages/llm-pipeline/ListFold.tsx` (신규 공통 fold 래퍼).

### 비변경
- audit 페이지 (`LlmPipelineAuditPage.tsx` + `web/src/data/llm-pipeline-audit/*`) — drift 차단을 위해 import 만, 변경 없음.
- `prompts/*.md` — 변경 없음.
- `kr_pipeline/common/thresholds.py` — 변경 없음.

## 12. 비범위 — 명확화

- **시뮬레이션 모달 콘텐츠 재작성** — 시뮬레이션 매트릭스 자체와 클릭 시 열리는 모달의 내용은 *별도 사이클*. 본 작업은 매트릭스 *외곽 안내 텍스트* 만 친절화.
- **audit 페이지 추가 변경** — 본 작업에서 audit 페이지는 import source 로만 사용, 콘텐츠 추가/수정 없음.
- **신규 cron / 신규 파이프라인 단계** — 본 작업은 *문서/UI 친절화* 만, 동작 변경 0.
- **prompt 또는 임계 변경** — 본 작업의 범위 외. 만약 친절화 중 발견된 prompt/임계 drift 가 있으면 *새 spec 으로 분리*.

## 13. 다음 단계

1. **사용자 review gate** — 이 spec 검토 후 승인.
2. **writing-plans skill** 호출 — 본 spec 을 입력으로 task 단위 implementation plan 작성.
3. **구현** — plan 의 task 별로 진행, 각 commit 마다 빌드·내용 정합 검증.

## 14. Self-Review

- **Placeholder scan**: ✅ TBD / TODO 없음. 모든 항목에 권위 source 명시.
- **Internal consistency**:
  - §5.1 카드 fold 구조 ↔ §6 콘텐츠 카탈로그 ↔ §11 파일 list 정합 ✅
  - §4 책임 분리 (drift 차단) ↔ §8 데이터 import 패턴 일관 ✅
  - §3 제외 (모달 비범위) ↔ §12 비범위 명확화 일관 ✅
- **Scope check**: ✅ 단일 spec — pipeline 페이지 친절화. audit/prompt/임계는 비범위.
- **Ambiguity check**:
  - "테이블 11종" = *StageCard 5 개의 입출력에 등장하는 unique 테이블 수* (확인 — `daily_indicators` / `weekly_indicators` / `daily_prices` / `index_daily` / `market_context_daily` / `corporate_actions` / `stocks` / `weekly_classification` / `trigger_evaluation_log` / `entry_params` / `signal_performance`). `schema.sql` 전체는 15 테이블이지만 *StageCard 미참조* 4개 (`pipeline_runs`, `weekly_prices`, `weekly_index`, `dart_corp_codes`) 는 본 spec 범위 외.
  - "8 조건" / "13 ZIP" / "9 패턴" / "13 risk flag" / "17 필드" 의 정확 개수는 권위 source 에서 *재확인 필요* (구현 시).
  - "친절 톤" 의 비유 한도 1-2개 — 명시.
  - drift 차단의 의미 — *기존 audit source 를 import* (§8) vs *신규 source 디렉토리* (§11) 의 경계 명확.
