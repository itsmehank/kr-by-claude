# LLM 분석 안내 페이지 v2 — 주말 분석 + 1주일 시뮬레이션 설계

## 목적

`/docs/llm-pipeline` 페이지가 평일 4단계만 설명한다. 주말 분석 (weekend batch) 이 어떻게 다른지 + 어떤 종목이 어느 단계에서 어떻게 처리되는지 처음 보는 사용자가 직관적으로 이해할 수 있어야 한다.

핵심 가치:
1. 주말 분석과 평일 분석의 **시기 / 대상 / 출력** 차이를 명확히 보여준다.
2. 10개 가상 종목이 1주일 동안 각 단계를 어떻게 통과하는지 **격자 매트릭스 + 모달**로 시각화한다.
3. 코드 / prompt 의 실제 동작에 기반한 사실 그대로 설명한다.

## 비범위

- 실시간 데이터로 시뮬레이션 (정적 JSON 사용).
- 시뮬레이션의 결과를 데이터베이스에 저장하거나 실제 LLM 호출.
- 별도 페이지나 라우트 분리. 한 페이지 안에 통합.
- 평일/주말 탭 구조. 위 → 아래 흐름이 더 자연스러움.

## 평일 vs 주말 정확한 차이 (조사 결과 요약)

| 항목 | **주말 (weekend.py)** | **평일 daily_delta.py** |
|---|---|---|
| 시점 | 토 03:20 (cron `20 3 * * 6`) | 평일 20:00 (cron `0 20 * * 1-5`) |
| LLM prompt | `analyze_chart_v3.md` | **동일** — `analyze_chart_v3.md` |
| 입력 필터 | `minervini_pass = TRUE AND drawdown_filter_pass = TRUE` 전체 | 같은 조건 **+** 최근 7일 분류 이력 없는 신규만 |
| 출력 분류 | entry / watch / ignore | 동일 (3분류) |
| `weekly_classification.source` | `'weekend'` | `'daily_delta'` |
| 후속 stage | 없음 (분류 + Slack digest 만) | evaluate_pivot → entry_params → performance |

**핵심**: 주말은 1단계 (분류 전체 갱신), 평일은 4단계 (신규 분류 + 트리거 평가 + 매수 계획 + 성과 추적).

분류 변경은 오직 weekend 또는 daily_delta 가 새 row INSERT 할 때 발생. `evaluate_pivot` 의 `abort` decision 은 `trigger_evaluation_log` 만 남기고 분류는 그대로 — 다음 토요일 weekend batch 에서 LLM 이 ignore 로 재분류해야 비로소 강등됨.

## 페이지 구조

```
[ 개요 박스 ]
    "주말 1단계 + 평일 4단계" 한 줄 + 주간 시각표

[ Stage 카드 5개 ]  (위 → 아래)
    ① weekend (order=0, 신규)
    ② daily_delta (기존, 설명 갱신)
    ③ evaluate_pivot (기존)
    ④ entry_params (기존)
    ⑤ performance (기존)

[ 1주일 시뮬레이션 ]
    범례 → 격자 매트릭스 (10 종목 × 8 날짜) → 셀 클릭 모달

[ 트리거-decision 매트릭스 ]  (기존)

[ 용어 사전 ]  (기존 + 주말 용어 추가)

[ FAQ ]  (기존 + 주말 관련 추가)
```

## Stage 카드

### weekend (신규, order=0)

```ts
{
  id: "weekend",
  order: 0,
  label: "주말 batch — 전체 재분류",
  summary: "결정론 통과 모든 종목을 토 새벽 LLM 으로 재분류 (전체 갱신)",
  targets:
    "토요일 03:20 cron. daily_indicators 의 직전 금요일 행 기준 minervini_pass=TRUE AND drawdown_filter_pass=TRUE AND stocks.delisted_at IS NULL 전체.",
  inputs: ["daily_indicators", "weekly_indicators", "market_context_daily", "corporate_actions", "stocks"],
  outputs: ["weekly_classification (source='weekend')"],
  deterministic: "결정론 필터 — minervini_pass + drawdown_filter_pass. 추가 게이트 없음.",
  llm: "analyze_chart_v3.md prompt (daily_delta 와 동일). ZIP 13개 파일 (payload.json + 일/주봉 OHLCV + 차트 PNG + 시장 컨텍스트 + corporate actions + minervini detail 등).",
  decisions: ["entry", "watch", "ignore"],
  actions:
    "weekly_classification 에 INSERT (source='weekend'). ON CONFLICT (symbol, classified_at) DO NOTHING. 이전 분류가 있어도 새 row 추가 — '현재 분류'는 DISTINCT ON (symbol) ORDER BY classified_at DESC. Slack digest 알림 (entry/watch/ignore 카운트).",
  sources: [
    "Minervini Trend Template (8 conditions)",
    "Minervini drawdown filter (≤50% from 52w high)",
    "O'Neil HMM base patterns",
  ],
  codeRef: "kr_pipeline/llm_runner/weekend.py + modes.py:run_weekend",
}
```

### daily_delta (설명 갱신)

기존 카드의 `summary` / `targets` / `llm` 텍스트를 다음과 같이 수정:

- **summary**: "오늘 새로 결정론 통과한 **신규** 종목만 LLM 분류 — weekend 와 같은 prompt"
- **targets**: 추가 문장 — "**weekend 와의 차이**: weekend 는 결정론 통과 전체를 매주 재분석. daily_delta 는 그 사이 평일에 새로 결정론 통과한 종목만 빠르게 분류."
- **llm**: 끝에 추가 — "**weekend 와 동일한 `analyze_chart_v3.md` prompt 사용** — 차이는 source 컬럼 (`'daily_delta'` vs `'weekend'`) 과 입력 필터 (`신규성` 추가).

### evaluate_pivot / entry_params / performance

기존 텍스트 유지. 다만 evaluate_pivot 의 `actions` 끝에 명시 추가:
- "**분류 자체는 변경 안 함**. abort decision 이라도 weekly_classification 의 row 는 그대로 유지 — 다음 토요일 weekend batch 에서 LLM 이 재분석 후 ignore 로 분류해야 비로소 강등됨."

## 1주일 시뮬레이션 — 격자 매트릭스

### 가상 시나리오

- **종목**: SYM_001 ~ SYM_010 (10개)
- **기간**: 토(W1) → 일 → 월 → 화 → 수 → 목 → 금 → 토(W2) (8 일)
- **초기 상태 (토 W1, weekend batch 직후)**:
  - SYM_001: entry (cup_with_handle, pivot 곧 돌파 임박)
  - SYM_002: watch (flat_base 진행 중, pivot 의 약 90%)
  - SYM_003: watch (base 형성 초기)
  - SYM_004: entry (vcp, 이번 주 거래 활발 예상)
  - SYM_005: ignore (climax_run, wide_and_loose)
  - SYM_006~008: 결정론 미통과 (이번 주 평일에 새로 통과 — daily_delta)
  - SYM_009, _010: 결정론 미통과 + 주중에도 통과 안 함 (참조용, 회색)

### 1주일 시나리오 (이벤트)

- **토(W1) 03:20** — weekend batch: SYM_001~005 분류 (위 초기 상태).
- **일** — 시장 휴장. 아무 일도 없음.
- **월 20:00** — full-daily:
  - daily_delta: 신규 후보 0개 (월요일은 아직 새로 통과 안 함).
  - evaluate_pivot:
    - SYM_001 (entry): close > pivot + volume 1.8× → **breakout** → LLM **go_now**.
    - SYM_004 (entry): close < pivot → 트리거 없음.
    - SYM_002 (watch): close < pivot × 0.95 → 트리거 없음.
    - SYM_003 (watch): 트리거 없음.
  - entry_params: SYM_001 매수 계획 17 필드 생성.
- **화 20:00** — full-daily:
  - daily_delta: SYM_006 새로 결정론 통과 → LLM 분류 → **entry** (cup_with_handle 좋음).
  - evaluate_pivot:
    - SYM_002 (watch): close 76,500, pivot 80,000 → close ≥ pivot × 0.95 + volume ≥ avg → **promotion** → LLM **wait** (거래량 부족, 한두 일 더).
- **수 20:00** — full-daily:
  - daily_delta: SYM_007 새로 결정론 통과 → LLM 분류 → **watch** (base 형성 초기).
  - evaluate_pivot:
    - SYM_004 (entry): close < sma_50 + distribution volume → **invalidation** → LLM **abort** (sma50_breach_distribution_volume).
      - 분류는 그대로 entry. trigger_evaluation_log 만 남음.
- **목 20:00** — full-daily:
  - daily_delta: SYM_008 새로 결정론 통과 → LLM 분류 → **ignore** (late_stage_base).
  - evaluate_pivot:
    - SYM_006 (entry, 화요일 분류 → active): close > pivot + volume → **breakout** → LLM **go_now**.
  - entry_params: SYM_006 매수 계획 생성.
- **금 20:00** — full-daily:
  - daily_delta: 신규 후보 0개.
  - evaluate_pivot: 트리거 없음 (조용한 날).
- **토(W2) 03:20** — weekend batch: SYM_001~008 (결정론 통과 종목) 전체 재분석.
  - SYM_001: entry → **entry** 유지 (이미 돌파, 진입 후 관리 단계).
  - SYM_002: watch → **entry** 승격 (이번 주 거래량 상승, handle 완성).
  - SYM_003: watch → **watch** 유지.
  - SYM_004: entry → **ignore** 강등 (수요일 invalidation 이후 base 깨짐 확인).
  - SYM_005: ignore → **ignore** 유지.
  - SYM_006: entry → **entry** 유지.
  - SYM_007: watch → **watch** 유지.
  - SYM_008: ignore → **ignore** 유지.

### 셀 시각화

배경색 + 이모지 + 라벨:
- 🟢 entry (초록 배경)
- 🟡 watch (노랑 배경)
- ⬜ ignore (회색 배경)
- 빈 셀 ( `—` ) = 그 날 그 종목에 변화 없음
- 우상단 작은 배지로 trigger / decision 표시:
  - ✨ go_now (golden star)
  - ⚠️ abort
  - ⏸ wait
  - ⚡ daily_delta 첫 등장
  - W (좌상단) = weekend 재분석
- 결정론 미통과 (SYM_009, _010) = 전체 행 회색 + 텍스트 "결정론 미통과"

### 상단 범례

```
🟢 entry   🟡 watch   ⬜ ignore   |   ✨ go_now   ⏸ wait   ⚠️ abort   |   ⚡ daily_delta 첫 분류   W weekend 재분석
```

### 셀 클릭 → 모달

- 모달 헤더: `SYM_002 · 화요일 (YYYY-MM-DD) · evaluate_pivot · promotion → wait`
- 본문 (2 컬럼):
  - **좌측 — LLM 입력 요약**:
    - 현재 분류: watch
    - pivot_price, base_low, sma_50
    - 오늘 close, volume, avg_volume_20d
    - 결정론 게이트 통과 조건 인용
  - **우측 — LLM 출력**:
    - decision: wait
    - confidence: 0.62
    - reasoning (200 자 한국어 요약 — 실제 prompt 가 요구하는 형태로 작성)
    - abort_reason: null
- 하단 — **"이 결과가 무엇을 의미하나?"** 한 줄 설명: "분류는 그대로 watch 유지. 내일 다시 게이트 확인."

모달은 `<dialog>` 또는 portal 기반. ESC + 백드롭 클릭으로 닫힘. tabindex 키보드 접근.

### 시뮬레이션 데이터 — 정적 JSON

파일: `web/src/data/llm-pipeline-simulation.ts`

```ts
export type SimClassification = "entry" | "watch" | "ignore";
export type SimTrigger = "breakout" | "promotion" | "invalidation";
export type SimDecision = "go_now" | "wait" | "abort";

export interface SimDay {
  date: string;       // YYYY-MM-DD
  label: string;      // "토 (W1)" / "월" / ...
  stage: "weekend" | "daily-pipeline" | "weekend-or-market-closed" | null;
}

export interface SimModal {
  title: string;
  inputs: Array<{ label: string; value: string }>;
  outputs: Array<{ label: string; value: string }>;
  reasoning: string;
  impact: string;
}

export interface SimCell {
  classification?: SimClassification;
  trigger?: SimTrigger;
  decision?: SimDecision;
  newlyDiscovered?: boolean;    // daily_delta 첫 등장
  reanalyzed?: boolean;          // weekend 재분석
  notIncluded?: boolean;         // 결정론 미통과
  modal?: SimModal;              // 클릭 시 표시
}

export interface SimRow {
  symbol: string;
  note?: string;                 // "결정론 미통과" 등
  cells: Record<string, SimCell>;  // date → cell
}

export const SIMULATION_DAYS: SimDay[];
export const SIMULATION_ROWS: SimRow[];
```

각 모달은 prompt 의 실제 출력 형태 (한국어 reasoning, abort_reason 카탈로그 등) 를 모사. 데이터는 정적이므로 시간이 지나도 변하지 않음.

## 트리거-decision 매트릭스

기존 유지. 다만 한 줄 추가:
- "분류 변경이 아닌 **그 날의 행동 판정**. 분류는 다음 weekend batch 에서만 변경 가능."

## 용어 사전 추가

- **weekend batch**: 토 03:20 cron 으로 실행되는 LLM 분석 — 결정론 통과 모든 종목 재분류.
- **결정론 필터**: minervini_pass + drawdown_filter_pass. LLM 호출 전 무료 필터.
- **신규 종목 (daily_delta)**: 결정론 통과 + 최근 7일 분류 이력 없음. 평일 daily_delta 의 대상.
- **재분석 (weekend)**: 이미 분류된 종목도 weekend batch 마다 같은 prompt 로 다시 분류. 이전 분류와 다를 수 있음.
- **현재 분류**: `DISTINCT ON (symbol) ORDER BY classified_at DESC` — 가장 최근 분류가 곧 "현재 상태".

## FAQ 추가

- **Q**: 주말 batch 와 daily_delta 가 같은 prompt 라면 둘 다 필요한가?
  - **A**: 시점이 다름. weekend = 매주 한 번 전체 결산 (시각차 확보, 분류 갱신). daily_delta = 평일에 새로 결정론 통과한 종목을 7일 기다리지 않고 즉시 분류 (조기 포착).
- **Q**: evaluate_pivot 의 abort 가 종목 분류를 ignore 로 바꾸나?
  - **A**: 아니오. evaluate_pivot 은 `trigger_evaluation_log` 만 INSERT. 분류는 그대로 유지. 다음 weekend batch 에서 LLM 이 재분석할 때 base 가 깨졌다고 판단되면 ignore 로 분류됨.
- **Q**: 한 종목이 한 주에 여러 번 분류될 수 있나?
  - **A**: 가능. 예: 토 weekend (재분석) → 평일에 daily_delta 가 다시 분류할 수 없음 (최근 7일 분류 이력 있어서 신규 아님). 하지만 다음 주 weekend 에서 또 재분석.

## 컴포넌트 분리

신규:
- `web/src/data/llm-pipeline-simulation.ts` — 정적 가상 데이터 + 모달 콘텐츠
- `web/src/pages/llm-pipeline/SimulationMatrix.tsx` — 격자 + 셀 렌더링
- `web/src/pages/llm-pipeline/SimulationModal.tsx` — 셀 클릭 → 상세

수정:
- `web/src/pages/LlmPipelinePage.tsx`:
  - STAGES 배열에 weekend 추가 (order=0)
  - daily_delta stage 텍스트 갱신
  - evaluate_pivot stage 텍스트 (분류 미변경 명시) 갱신
  - return JSX 에 "1주일 시뮬레이션" 섹션 삽입 (개요 박스 다음 또는 stage 카드 다음)
  - 용어 사전 / FAQ 항목 추가

## 컴포넌트 책임 경계

- **SimulationMatrix**: 격자 렌더링만. props `{ days: SimDay[]; rows: SimRow[]; onCellClick: (row, day) => void }`. 셀 색 / 이모지 결정만 책임. 데이터 fetch 안 함.
- **SimulationModal**: 모달 표시만. props `{ open: boolean; cell: SimModal | null; onClose: () => void }`. 단순 dialog.
- **llm-pipeline-simulation.ts**: 데이터만. 함수 없음.
- **LlmPipelinePage**: 페이지 조립 + 상단/하단 섹션 그대로 + simulation state (`selectedCell` 등).

## 테스트

- 코드 변경: tsc clean.
- 수동 검증:
  - `/docs/llm-pipeline` 방문 → weekend 카드 표시 확인.
  - 1주일 시뮬레이션 격자 표시 (10 종목 × 8 일).
  - 셀 호버 → 컬러/배지 변화.
  - 셀 클릭 → 모달 열림, 내용 표시.
  - ESC / 백드롭 클릭 → 모달 닫힘.
  - 결정론 미통과 행 (SYM_009, _010) → 회색 + 비어 있음.

## 작업 분리 (plan task 후보)

1. STAGES 배열에 weekend stage 추가 + daily_delta/evaluate_pivot 설명 갱신
2. 용어 사전 / FAQ 추가
3. 시뮬레이션 정적 데이터 작성 (10 종목 × 8 일, 모달 콘텐츠 포함)
4. `SimulationMatrix` 컴포넌트 — 격자 + 셀 색
5. `SimulationModal` 컴포넌트 — dialog + 좌/우 컬럼
6. `LlmPipelinePage` 통합 — 시뮬레이션 섹션 + state 관리

순서: 1 → 2 → 3 → 4 → 5 → 6 (3 이 4/5 의 데이터 형식을 결정하므로 먼저).

## 성공 기준

- `/docs/llm-pipeline` 에 weekend 단계가 4 기존 stage 와 함께 5개 카드로 표시된다.
- daily_delta 카드가 weekend 와의 관계를 명시한다.
- 1주일 시뮬레이션 격자가 표시되고 10 종목 × 8 날짜의 셀이 색 + 라벨 + 이모지로 표현된다.
- 셀 클릭 시 모달이 열려 그 종목 / 그 날의 LLM 입력 / 출력 / reasoning / 영향이 보인다.
- 결정론 미통과 종목 (SYM_009, _010) 은 회색 + 비어 있음으로 명확히 구분된다.
- 평일/주말 분석을 처음 보는 사용자가 이 페이지만으로 두 분석의 시기/대상/출력 차이와 한 종목이 1주일 동안 어떻게 변화하는지 이해할 수 있다.
