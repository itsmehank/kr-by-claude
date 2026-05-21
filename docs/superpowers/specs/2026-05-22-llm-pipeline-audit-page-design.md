# LLM 분석 검증 페이지 (`/docs/llm-pipeline/audit`) — 설계

## 목적

Minervini / O'Neil 책 전문가가 한 페이지만 보고 우리 LLM 분석 시스템 전체 (스케줄링 / 필터링 / 결정론 로직 / LLM prompt 결정 규칙 / 책 인용 정확성) 를 line-by-line 검증할 수 있는 단일 페이지를 추가한다.

기존 `/docs/llm-pipeline` (이하 "안내 페이지") 은 시뮬레이션 + 개요 중심으로 유지하고, 본 페이지는 **모든 임계값, 모든 분기 조건, 모든 prompt 내용, 책 원문 인용** 을 전부 담는 깊이 우선 페이지.

## 비범위

- 새 분석 로직 / 새 prompt 추가. 본 페이지는 **현재 시스템의 정확한 서술** 만 다룸.
- 한국어 외 다른 언어 단일 페이지. 본문 한국어 + 책 인용은 영어 원문 + 한국어 요약 (전문가가 책 원전과 단어 매칭 가능하도록).
- 코드 수정. 코드 변경이 필요한 비일관성 (예: c6 임계 1.25 vs 책 1.30) 은 별도 follow-up 로 분리하고 본 페이지는 알려진 검토 사항으로 명시.

## 기존 안내 페이지와의 관계

| | 기존 `/docs/llm-pipeline` | 신규 `/docs/llm-pipeline/audit` |
|---|---|---|
| 대상 | 한국 운영자 (시스템 학습) | Minervini/O'Neil 전문가 (검증) |
| 깊이 | 시뮬레이션 + 개요 | line-by-line 깊이 |
| 길이 | 단일 페이지, 적당 | 단일 페이지, 매우 김 (수천 줄) |
| 책 인용 | 짧은 한국어 reference | 영어 원문 + 한국어 + 코드 ref |
| Prompt | 요약만 | 전체 내용 (접기) |
| 변경 시 | 우선순위 낮음 | 시스템 변경 시 즉시 반영 |

## 페이지 구조

```
┌────────────────────────────────────────────────────────────────┐
│  좌 sticky 목차 (lg:w-64)  │   메인 본문 (lg:flex-1)             │
│  ─────────────────────────│                                    │
│  1. 시스템 개요              │   ## 1. 시스템 개요                │
│  2. 실행 스케줄              │   ...                              │
│  3. 단계별 상세              │                                    │
│   ├─ 3.1 weekend           │   ## 2. 실행 스케줄                │
│   ├─ 3.2 daily_delta       │   ...                              │
│   ├─ 3.3 evaluate_pivot    │                                    │
│   ├─ 3.4 entry_params      │   ## 3. 단계별 상세                │
│   └─ 3.5 performance       │   ### 3.1 weekend                  │
│  4. Minervini 8조건         │   ...                              │
│  5. Base 패턴 9개            │                                    │
│  6. Risk Flags 13개          │   ...                              │
│  7. LLM Payload (ZIP 13)    │                                    │
│  8. Prompt 전체 (3개)        │                                    │
│  9. 비일관성 / 변경 이력      │                                    │
└────────────────────────────────────────────────────────────────┘
```

데스크탑: 좌 sticky 목차 + 우 메인. 모바일: 상단 collapsible 목차.

## 본문 섹션 상세

### 1. 시스템 개요

- 한 줄 요약: "주말 1단계 (전체 재분류) + 평일 4단계 (신규 분류 → 트리거 평가 → 매수 계획 → 성과 추적)"
- mermaid 데이터 흐름 다이어그램 (기존 페이지 `DIAGRAM_DATA_FLOW` 재사용)
- **핵심 설계 철학** 박스:
  > 결정론 게이트는 싸고 느슨한 사전 필터 — 명백한 비후보만 제거.
  > 정밀 임계 (1.4~1.5× 표준, pocket pivot 예외, 일중 강도 등) 와 예외 판단은
  > LLM 이 차트와 함께 수행. 게이트를 책 표준에 맞추면 (1) LLM 이 무력화되고
  > (2) 책이 인정한 예외 (pocket pivot, 시장 맥락) 가 사전 배제되는 false
  > negative 발생.

### 2. 실행 스케줄

`pipeline_specs.py` 의 cron 정확한 인용. 표:

| Pipeline | Cron | KST 시각 | 실행 단계 | LLM 호출 |
|---|---|---|---|---|
| `llm-weekend` | `20 3 * * 6` | 토 03:20 | weekend | Yes |
| `llm-full-daily` | `0 20 * * 1-5` | 평일 20:00 | daily_delta → evaluate_pivot → entry_params → performance | Yes (4 stage 중 3개) |
| `llm-performance` | `0 23 * * *` | 매일 23:00 | performance | No (가격 backfill) |

각 cron 의 책 근거 또는 시스템 설계 표기.

### 3. 단계별 상세 (5 stages, 각 stage 깊은 카드)

각 stage 카드 구조:

```markdown
### 3.X {stage_id} — {label}

#### 시기
- {KST 시각}, {평일/토요일}

#### 입력 필터
SQL 전체 인용:
```sql
SELECT ...
  FROM ...
 WHERE ...
```
**코드 위치**: `kr_pipeline/llm_runner/load.py:LN`

#### 결정론 로직 (해당 시)
Python 전체 인용:
```python
def evaluate(...):
    ...
```
**코드 위치**: `kr_pipeline/llm_runner/compute/trigger_gate.py`

#### LLM Prompt
- **파일**: `prompts/analyze_chart_v3.md`
- **결정 규칙 요약**: [한국어, 200자 이내]
- **출력 schema**: JSON (entry/watch/ignore + pattern + pivot + risk_flags)
- **전체 내용**: [§8 참조 또는 inline `<details>`]

#### 출력
- 테이블: `weekly_classification`
- 컬럼: symbol, classified_at, classification, pattern, pivot_price, base_low, base_high, base_depth_pct, base_start_date, risk_flags, confidence, reasoning, source
- INSERT 정책: ON CONFLICT (symbol, classified_at) DO NOTHING (append-only)

#### 책 근거
📖 *Minervini, Trade Like a Stock Market Wizard, Ch.5*:
> "A stock must meet all eight criteria..."

한국어: 모든 8조건 충족 필수.

#### 코드 참조
- `kr_pipeline/llm_runner/weekend.py` (orchestration)
- `kr_pipeline/llm_runner/load.py:get_qualifying_tickers` (필터)
```

각 stage 별 차별점:
- **3.1 weekend**: source='weekend', 전체 minervini_pass 재분류, Slack digest
- **3.2 daily_delta**: source='daily_delta', 최근 7일 미분류 신규만, weekend 와 같은 prompt
- **3.3 evaluate_pivot**: 결정론 게이트 (trigger_gate.py) 전체 Python 코드 + 책 근거 (O'Neil HMMS Ch.2 — 1.4-1.5× breakout 책 범위 + 우리는 게이트 1.0× 로 완화 + LLM 이 정밀 판정), promotion staging 안전장치 (prompt §3.3 + entry_params SQL trigger_type='breakout' 필터)
- **3.4 entry_params**: 17 필드 각 정의 + 책 기준 (Minervini risk management 1-3% per trade, O'Neil "Buy at the Buy Point") + entry_mode 감지 (pocket_pivot vs pivot_breakout)
- **3.5 performance**: LLM 없음, signal_at 90일 cutoff, 1w/2w/4w/8w 가격 + 시장 대비 alpha

### 4. Minervini Trend Template 8조건

표 형식:

| # | 한국어 정의 | 임계값 | 코드 위치 | 책 원문 (영어) |
|---|---|---|---|---|
| 1 | 가격 > 150일 MA > 200일 MA | — | minervini.py:Ln | "Price > MA150 AND Price > MA200" |
| 2 | 150일 MA > 200일 MA | — | minervini.py:Ln | "MA150 > MA200" |
| 3 | 200일 MA 22일간 상승 | 22 거래일 | minervini.py:Ln | "MA200 trending up for ≥1 month" |
| 4 | 50일 > 150일 > 200일 MA | — | minervini.py:Ln | "MA50 > MA150 > MA200" |
| 5 | 가격 > 50일 MA | — | minervini.py:Ln | "Price > MA50" |
| 6 | 가격 ≥ 52주 저점 × 1.25 | 1.25× | minervini.py:Ln | "Price ≥ 52w-low × 1.25 to 1.30" (책 1.30, 코드 1.25 — §9 검토 사항) |
| 7 | 가격 ≥ 52주 고점 × 0.75 | 0.75× | minervini.py:Ln | "Price ≥ 52w-high × 0.75" |
| 8 | RS Rating ≥ 70 | 70 | rs_rating 컬럼 + SQL WHERE | "RS Rating ≥ 70" (O'Neil HMMS) |

책 근거: *Minervini, Trade Like a Stock Market Wizard, Ch.5 "Trend Template"*, 8 conditions 명시.

### 5. Base 패턴 9개 (analyze_chart_v3.md)

각 패턴 카드:

```markdown
#### flat_base
- **정의**: 5+ 주 sideways consolidation, ≤ 15% correction from base high
- **책 근거**: O'Neil HMMS — flat base 정의
- **prompt 위치**: prompts/analyze_chart_v3.md:Ln
```

9개 패턴 전체:
- flat_base, cup_with_handle, vcp, double_bottom, high_tight_flag, 3c_cheat, base_on_base, ascending_base, none

각 패턴별 책 페이지 (가능한 경우) + 영어 정의 + 한국어 요약.

### 6. Risk Flags 13개 taxonomy

각 flag 카드:

```markdown
#### climax_run
- **정의**: 1-3주 내 25%+ 가속 상승 + 최대 거래량 → Stage 3 경고
- **적용 기준**: rapid run + climactic volume
- **prompt 위치**: prompts/analyze_chart_v3.md:Ln
```

13개 flag 전체:
climax_run, late_stage_base, extended_from_ma, faulty_pivot, low_volume_breakout, narrow_base, wide_and_loose, thin_liquidity_us_only, prior_uptrend_insufficient, volume_contraction_on_advance, reverse_split_distortion, unfavorable_market_context, etf_methodology_mismatch.

### 7. LLM Payload — ZIP 13 파일 (zip_builder.py)

표 형식:

| # | 파일명 | 내용 요약 | 출처 코드 |
|---|---|---|---|
| 1 | README.md | 패키지 안내 | zip_builder.py:Ln |
| 2 | prompt_step1_analyze.md | 1단계 prompt 사본 | prompts/analyze_chart_v3.md |
| 3 | prompt_step2_entry_params.md | 2단계 prompt 사본 | prompts/calculate_entry_params_v2_0.md |
| 4 | payload.json | 핵심 데이터 (현재 메트릭 + 분류 메타) | payload_builder.py |
| 5 | market_context.json | confirmed_uptrend / distribution day count / FTD | market_context |
| 6 | corporate_actions.json | 액면분할 / 자본감소 등 | corporate_actions |
| 7 | minervini.json | 8조건 detail (각 c1-c8 + values + margin_pct) | minervini_detail_builder.py |
| 8 | daily.csv | 60거래일 OHLCV + 지표 | csv_builder.py |
| 9 | weekly.csv | 104주 OHLCV + 지표 | csv_builder.py |
| 10 | kospi_daily.csv | KOSPI 지수 일봉 | csv_builder.py |
| 11 | kospi_weekly.csv | KOSPI 지수 주봉 | csv_builder.py |
| 12 | daily_chart.png | 일봉 차트 이미지 (matplotlib) | chart_render |
| 13 | weekly_chart.png | 주봉 차트 이미지 | chart_render |

### 8. Prompt 전체 (3개, 접기)

세 prompt 의 전체 raw 내용을 `<details>` collapsible 로 표시:

```html
<details>
  <summary>1. analyze_chart_v3.md (weekend + daily_delta 공통, 309 행)</summary>
  <pre><code className="language-markdown">{promptContent}</code></pre>
</details>

<details>
  <summary>2. evaluate_pivot_trigger_v1.md (evaluate_pivot, ~120 행)</summary>
  ...
</details>

<details>
  <summary>3. calculate_entry_params_v2_0.md (entry_params, ~580 행)</summary>
  ...
</details>
```

각 prompt 의 raw 내용은 빌드 시점에 string 으로 import (Vite `?raw` 또는 별도 .ts 파일에 string 저장).

### 9. 비일관성 / 변경 이력

#### 9.1 최근 변경 (2026-05-21 ~ 2026-05-22)

타임라인:

- **drawdown_filter 컬럼/계산 완전 제거** (2026-05-21)
  - 사유: (w52_high − w52_low) / w52_high 공식이 시간 순서 무시 → 정통 강세 종목 (저점 대비 100~300% 상승) false negative 80% 발생
  - 영향: weekend / daily_delta 의 입력 필터에서 drawdown_filter_pass=TRUE 제거. LLM 분석 대상 종목 5× 증가.

- **avg_volume_20d → avg_volume_50d 전면 리네임** (2026-05-21)
  - 사유: 전문가 자문 — Minervini TLSMW Ch.10 (pivot point) + O'Neil HMMS Ch.2 의 breakout 거래량 baseline 은 50일 평균. 20일은 책에서 *가격* MA (돌파 후 follow-through 가드, Minervini TTLC Ch.1) 로만 등장.
  - 코드 변경: DB SELECT 는 처음부터 avg_volume_50d. 변수명/dict key/함수 인자/prompt 참조만 잘못된 20d 라는 이름이었음. 실제 값/동작 변화 없음.

- **trigger_gate breakout 게이트 1.5× → 1.0× 완화** (2026-05-21)
  - 사유: 전문가 자문 — 책 표준 (1.4-1.5×) 의 정밀 판정 + pocket pivot 예외 (O'Neil 제자 책 Ch.5 BIDU 사례) 는 LLM 이 차트 보고 결정. 게이트가 1.5× 로 사전 배제하던 false negative 해소.
  - 영향: 게이트는 "거래량 죽지 않은 정도" (avg 이상) 만 확인. LLM 이 표준/예외 판단.

- **promotion staging 안전장치 (이중 방어)** (2026-05-21)
  - 사유: promotion 트리거는 watch 분류의 "LLM 평가 시작" staging 신호일 뿐 매수 시그널 아님. 0.95× 임계는 책 근거 없는 시스템 자체 설계 (O'Neil 은 오히려 pivot 도달 전 매수 경고).
  - 코드 변경:
    - prompt §3.3 신규: promotion 트리거에서 `go_now` 발생 금지 명시
    - entry_params SQL: `WHERE trigger_type = 'breakout'` 필터 추가 (prompt 위반 시에도 promotion + go_now → entry_params 직행 차단)

#### 9.2 알려진 검토 사항

- **Minervini c6 임계 (1.25 vs 1.30)**: 책은 1.30× 52w-low 명시, 코드는 1.25× 사용. 의도된 KR calibration 인지 오류인지 확인 필요.
- **invalidation 에 SMA20 *가격* MA 추가**: Minervini TTLC Ch.1 — 돌파 직후 20일 가격선 종가 이탈 시 성공률 반감. 현재 invalidation 은 SMA50 만 보지만 SMA20 도 책 근거 분명. 별도 follow-up.

#### 9.3 향후 모니터링

- 1.0× 게이트 완화 후 LLM 호출 종목 수 / 비용 모니터링
- 분류 변경 추이 (entry → ignore 강등이 정상 흐름인지)
- pocket pivot 케이스 발견 시 LLM 이 정상 판정하는지 확인

## 데이터 / 컴포넌트 구조

### 신규 파일

```
web/src/data/
  llm-pipeline-audit.ts           # 정적 데이터 통합
                                  # - MINERVINI_CONDITIONS (8)
                                  # - BASE_PATTERNS (9)
                                  # - RISK_FLAGS (13)
                                  # - CRON_SCHEDULE (3)
                                  # - ZIP_FILES (13)
                                  # - CHANGE_LOG (4 + 검토 사항)
  prompts/
    analyze-chart-v3.ts           # raw string (export const TEXT = "...")
    evaluate-pivot-trigger-v1.ts
    calculate-entry-params-v2-0.ts

web/src/pages/
  LlmPipelineAuditPage.tsx        # 페이지 조립

web/src/pages/llm-pipeline-audit/
  TableOfContents.tsx             # sticky 목차 (스크롤 추적)
  Section.tsx                     # <section id={id}> wrapper
  BookCitation.tsx                # 책 인용 박스
  CollapsiblePrompt.tsx           # <details> wrapper for raw prompt
  StageCardDeep.tsx               # 각 stage 상세 카드 (현 StageCard 보다 깊은 버전)
```

### Prompt raw import 방식

옵션 A — Vite `?raw` import:
```ts
import promptText from "../../../../prompts/analyze_chart_v3.md?raw";
```

옵션 B — 별도 .ts 파일에 string export:
```ts
// web/src/data/prompts/analyze-chart-v3.ts
export const ANALYZE_CHART_V3 = `
{전체 prompt 내용}
`;
```

**B 추천** — vite root 외부 (`prompts/` 디렉터리) 의 파일을 raw import 하려면 vite config 손봐야 함. B 는 단순 string export. 빌드 시점 수동 동기화는 `?raw` 도 동일.

### TableOfContents 컴포넌트

```tsx
interface TocItem {
  id: string;          // 섹션 id (anchor)
  label: string;       // 표시 텍스트
  depth: 0 | 1;        // 들여쓰기 깊이
}

const TOC: TocItem[] = [
  { id: "overview", label: "1. 시스템 개요", depth: 0 },
  { id: "schedule", label: "2. 실행 스케줄", depth: 0 },
  { id: "stages", label: "3. 단계별 상세", depth: 0 },
  { id: "stage-weekend", label: "3.1 weekend", depth: 1 },
  ...
];
```

스크롤 시 현재 위치 강조 (`IntersectionObserver`). 클릭 시 `scrollIntoView({ behavior: "smooth" })`.

### BookCitation 컴포넌트

```tsx
interface Props {
  book: string;        // "Minervini, Trade Like a Stock Market Wizard"
  chapter?: string;    // "Ch.5"
  page?: string;       // "p.119"
  englishQuote: string;
  koreanSummary: string;
  codeRef?: string;    // "kr_pipeline/indicators/compute/minervini.py:26"
}
```

박스 형식 — emoji 📖 + 책 정보 헤더 + 영어 quote + 한국어 + 코드 ref.

## 라우트 / NAV

`web/src/App.tsx`:

- Route 추가: `<Route path="/docs/llm-pipeline/audit" element={<LlmPipelineAuditPage />} />`
- NAV item 추가 (LLM 분석 안내 다음): `{ to: "/docs/llm-pipeline/audit", label: "LLM Audit", kr: "LLM 분석 검증", Icon: ShieldCheck }`

## 테스트

- tsc clean
- 수동 검증:
  - `/docs/llm-pipeline/audit` 방문 시 sticky 목차 + 메인 본문 렌더
  - 목차 클릭 시 해당 섹션으로 부드럽게 스크롤
  - 스크롤 시 목차 강조 따라옴 (IntersectionObserver)
  - 9개 섹션 모두 표시
  - 3 prompt details 펼침 / 접힘
  - 코드 위치 (file:LN) 클릭 가능한 텍스트 (또는 단순 표시)
  - 영어 인용 + 한국어 요약 둘 다 표시

## 작업 분리 (plan task 후보)

1. **공용 컴포넌트** — Section / TableOfContents / BookCitation / CollapsiblePrompt / StageCardDeep
2. **정적 데이터 #1** — Minervini 8조건 + Base patterns 9 + Risk flags 13
3. **정적 데이터 #2** — Cron + ZIP files + Change log
4. **Prompt raw string** — 3 prompt 의 string 파일 (수동 복사)
5. **LlmPipelineAuditPage 조립** — 9 섹션 모두 + sticky TOC 연결
6. **NAV + Route 등록** + 최종 수동 검증

## 성공 기준

- `/docs/llm-pipeline/audit` 방문 시 단일 페이지에 9 섹션 모두 표시.
- 좌측 sticky 목차로 모든 섹션 빠르게 이동 가능.
- Minervini Trend Template 8조건 의 각 임계값 / 코드 위치 / 영어 원문 인용 모두 명시.
- 9 base 패턴 + 13 risk flag taxonomy 의 각 정의 표시.
- 5 stage 각각의 입력 SQL / Python 결정론 로직 / LLM prompt 파일 / 출력 테이블 컬럼 / 책 근거 명시.
- 3 prompt 전체 내용을 details 펼침으로 확인 가능.
- 비일관성 / 변경 이력 (4 + 검토 사항) 모두 표시.
- 전문가가 페이지만 보고 "어떤 임계가 책의 어디서 왔는지", "각 prompt 가 어떤 결정 규칙으로 작동하는지", "코드의 어떤 파일/라인을 보면 되는지" 모두 답할 수 있음.
