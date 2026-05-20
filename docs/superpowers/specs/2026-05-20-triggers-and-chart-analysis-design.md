# 트리거 이력 노출 + ChartPage 종목별 분석 통합 — 설계

## 목적

두 갭을 한 번에 해소한다.

1. **트리거 평가 이벤트 가시성**: `trigger_evaluation_log` 가 API 와 UI 어디서도 보이지 않는다. 매일 결정론 트리거 게이트를 통과해 LLM 이 평가한 종목 / 결과 / reasoning 을 사람이 확인할 수 있어야 한다.
2. **종목별 분석 결과 단일 뷰**: ChartPage 가 현재 가격/지표만 보여준다. 종목 단위로 분류 / 결정론 지표 / 트리거 이력 / 매수 시그널 / 성과를 한 화면에서 봐야 매수 결정을 내릴 수 있다.

두 작업이 같은 trigger API 를 공유하므로 한 plan 으로 묶는다.

## 비범위

- `weekly_classification.base_end_date` 컬럼 신설. 기존 `base_start_date` + `analyzed_for_date` 로 충분히 base 기간 텍스트 표현 가능.
- 차트 위 base 영역 음영 overlay. 분류 카드의 텍스트 (Base 기간 / 가격대 / 깊이) 로 갈음.
- LLM prompt 변경. 기존 스키마 그대로 사용.
- 사용자 인증 / 권한. localhost 단일 사용자 전제.

## 데이터 모델

기존 테이블만 사용. 신규 컬럼/테이블 없음.

- `trigger_evaluation_log` (kr_pipeline/db/schema.sql:293): symbol / evaluated_at / trigger_type / close / volume / pivot_price / decision / confidence / reasoning / abort_reason / prior_classification_at
- `weekly_classification` (kr_pipeline/db/schema.sql:256): symbol / classified_at / analyzed_for_date / market / classification / pattern / pivot_price / pivot_basis / base_high / base_low / base_depth_pct / base_start_date / risk_flags / confidence / reasoning
- `daily_indicators` (Minervini 8조건 + drawdown_filter + rs_rating)
- `entry_params` (kr_pipeline/db/schema.sql:321): symbol / signal_at / entry_price / stop_loss / expected_target_price / risk_reward_ratio / observed_breakout_volume_ratio / known_warnings / notes
- `signal_performance` (kr_pipeline/db/schema.sql:362)

## API

### `GET /api/triggers`

**위치**: `api/routers/triggers.py` (신규)

**쿼리 파라미터**:

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `ticker` | str | — | 종목 코드 필터 (정확 일치) |
| `date` | YYYY-MM-DD | — | 단일 날짜 필터 (KST 일자 기준) |
| `from` | YYYY-MM-DD | — | 기간 시작 (포함) |
| `to` | YYYY-MM-DD | — | 기간 끝 (포함) |
| `decision` | str | — | `go_now` / `wait` / `abort` |
| `trigger_type` | str | — | `breakout` / `promotion` / `invalidation` |
| `limit` | int | 200 | 최대 1000 |
| `offset` | int | 0 | 페이지네이션 |

**응답** (배열, evaluated_at DESC):

```json
[
  {
    "symbol": "005930",
    "name": "삼성전자",
    "market": "KOSPI",
    "evaluated_at": "2026-05-20T09:32:12+09:00",
    "trigger_type": "breakout",
    "close": 84000,
    "volume": 12345678,
    "avg_volume_50d_ratio": 1.82,
    "pivot_price": 82300,
    "pivot_delta_pct": 2.07,
    "decision": "go_now",
    "confidence": 0.78,
    "reasoning": "거래량 증가와 함께 …",
    "abort_reason": null
  }
]
```

- `name`, `market` 은 `stocks` 테이블 조인.
- `avg_volume_50d_ratio`, `pivot_delta_pct` 는 응답 시 계산 (`volume / avg_volume_50d` 는 `daily_indicators` 의 같은 날짜 행에서, `pivot_delta_pct` 는 `(close - pivot_price) / pivot_price * 100`).
- 결과가 없으면 빈 배열 `[]`.

**정렬**: `evaluated_at DESC`. (날짜 그룹 UI 는 프론트가 처리.)

### 기존 endpoint 재사용

- `GET /api/stocks/{ticker}` — 종목 메타
- `GET /api/classifications?ticker=…&limit=1` — 분류 최신
- `GET /api/indicators/daily?ticker=…&limit=1` — 결정론 지표 최신
- `GET /api/signals?ticker=…&limit=1` — entry_params 최신
- `GET /api/performance?ticker=…&limit=1` — signal_performance 최신

이미 존재한다고 가정. 누락 필터(`ticker=`)는 plan 단계에서 확인하고 필요 시 추가.

## 사이드바 / 라우트

`web/src/App.tsx` 의 `NAV_ITEMS` 에 추가:

```ts
{ to: "/triggers", label: "Triggers", kr: "트리거 이력", Icon: Activity }
```

위치: `Classifications` 와 `LLM Pipeline Guide` 사이.

라우트:

```tsx
<Route path="/triggers" element={<TriggersPage />} />
```

## 페이지 1 — `/triggers` (TriggersPage)

**파일**: `web/src/pages/TriggersPage.tsx` (신규)

**구성**:

1. 상단 필터 바: 종목 검색 / decision 드롭다운 / trigger_type 드롭다운 / 기간 (from~to, 기본 최근 7일)
2. 메인: 날짜 그룹 + 테이블
   - 그룹 헤더: `2026-05-20 (수) — 12건 (go 2 / wait 8 / abort 2)`
   - 테이블 컬럼: 종목 / 트리거 / decision (색 점) / 거래량비 / pivot대비 / reasoning (한 줄, ellipsis)
   - 행 hover 시 reasoning 전체 tooltip
   - 행 클릭 → `/chart/{ticker}` 이동
3. 페이지네이션: 하단 "더 보기" — offset 증가

**상태**:

- URL 쿼리 파라미터로 필터 상태 동기화 (`/triggers?decision=go_now&from=2026-05-13`)
- 빈 상태: "필터에 해당하는 트리거 평가 이력이 없습니다"

## 페이지 2 — ChartPage 확장

**파일**: `web/src/pages/ChartPage.tsx` 수정

### 레이아웃

종목이 선택된 경우 (`ticker` URL 파라미터 존재):

```
┌── 차트 (PriceChart, 기존) ───────────────────┐
│  + pivot/stop 가로 점선 overlay              │
│  + 트리거 마커                                │
└──────────────────────────────────────────┘
[기존 SMA/거래량 토글] + [신규 overlay 토글]

[분석 카드 그리드 — 차트 아래 세로 stack]
┌─ 분류 카드 ──────┐  ┌─ 결정론 지표 카드 ─┐
└──────────────┘  └─────────────────┘
┌─ 매수 시그널 카드 ┐  ┌─ 성과 카드 ───────┐
└──────────────┘  └─────────────────┘
┌─ 트리거 이력 표 (전폭) ─────────────────────┐
└────────────────────────────────────────┘
```

데스크탑 기준 2 컬럼 그리드, 모바일은 1 컬럼.

종목 미선택 시: 패널 hidden. 기존 종목 선택 UI 만 표시.

### 차트 위 overlay

PriceChart 컴포넌트 (`web/src/components/charts/PriceChart.tsx`) prop 확장:

```ts
interface PriceChartProps {
  // 기존 props ...
  pivotPrice?: number | null;
  stopLoss?: number | null;
  showPivotStop?: boolean;
  showTriggerMarkers?: boolean;
  triggerEvents?: Array<{
    date: string;           // YYYY-MM-DD
    decision: "go_now" | "wait" | "abort";
    triggerType: string;
    close: number | null;
    reasoning: string;
  }>;
}
```

- pivot 가로 점선: 파란색 (`#2563eb`), dashed, label `pivot 32600`
- stop_loss 가로 점선: 빨간색 (`#dc2626`), dashed, label `stop 30200`
- 트리거 마커: 가격 위 (close 가격 좌표) 원형 점.
  - `go_now` → 초록 (`#16a34a`)
  - `wait` → 노랑 (`#ca8a04`)
  - `abort` → 회색 (`#6b7280`)
- 마커 hover tooltip: `trigger_type · decision · pivot대비 +X% · reasoning 한 줄`
- 데이터 없으면 (null) 해당 선/마커 안 그림.

### 토글 체크박스

`web/src/pages/ChartPage.tsx` 의 기존 SMA 토글 패턴 그대로 (line 124-131 useState 영역, line 425-473 체크박스 UI 영역):

- `showPivotStop` (default: true)
- `showTriggerMarkers` (default: true)

기존 SMA/거래량 체크박스 묶음 옆에 신규 묶음 "분석 결과" 으로 추가.

### 분석 카드 컴포넌트

**파일**:
- `web/src/components/panels/ClassificationCard.tsx`
- `web/src/components/panels/IndicatorsCard.tsx`
- `web/src/components/panels/EntrySignalCard.tsx`
- `web/src/components/panels/PerformanceCard.tsx`
- `web/src/components/panels/TriggerHistoryTable.tsx`

각 컴포넌트는 `ticker: string` 을 받아 자체 useQuery 로 데이터 fetch. 빈 상태 카드 (예: "분류 이력 없음") 자체 처리.

**1. ClassificationCard** (`useQuery` → `/api/classifications?ticker=X&limit=1`)
- 표시: `analyzed_for_date` / 분류 (watch/entry/ignore + 색) / 패턴 / Base 기간 (`base_start_date` ~ `analyzed_for_date`, 주 단위 환산) / Base 가격대 (`base_low`–`base_high`) / Base 깊이 / Pivot / Risk flags (배지) / reasoning (markdown)

**2. IndicatorsCard** (`useQuery` → `/api/indicators/daily?ticker=X&limit=1`)
- 표시: Minervini 8조건 (✓/✗ 그리드) / drawdown_filter / RS rating (큰 숫자) / 마지막 업데이트 일자

**3. EntrySignalCard** (`useQuery` → `/api/signals?ticker=X&limit=1`)
- 표시: signal_at / entry_mode / entry_price / stop_loss (+ % from current) / expected_target_price (+ %) / risk_reward_ratio / observed_breakout_volume_ratio / known_warnings (배지) / notes
- 없으면 "아직 매수 시그널 없음" 안내 + 트리거 이력으로 유도

**4. PerformanceCard** (`useQuery` → `/api/performance?ticker=X&limit=1`)
- 표시: signal_at / entry_price / return_1w/2w/4w/8w % / market_return 비교 (alpha)
- 없으면 "성과 기록 없음"

**5. TriggerHistoryTable** (`useQuery` → `/api/triggers?ticker=X&limit=20`)
- /triggers 페이지와 동일한 컬럼 (종목 컬럼 제외): 날짜 / 트리거 / decision / 거래량비 / pivot대비 / reasoning
- 더 보기 버튼 → `/triggers?ticker=X` 이동
- PriceChart 의 `triggerEvents` prop 도 같은 query 결과 재사용 (TanStack Query 캐시 공유)

### PriceChart 에 trigger 데이터 전달

ChartPage 에서 `useQuery<Trigger[]>` 한 번 호출 → 결과를 TriggerHistoryTable 에도 prop 으로 넘기고 PriceChart `triggerEvents` 에도 넘긴다. 또는 TriggerHistoryTable 이 자체 fetch 하고, PriceChart 용 query 를 ChartPage 가 별도 호출 — 같은 queryKey 라 한 번만 네트워크 발생.

후자가 컴포넌트 결합 약해서 추천. 구체 결정은 plan 단계.

## 컴포넌트 책임 경계

- **TriggersPage**: 전체 종목 × 기간 뷰. 필터/페이지네이션. 행 클릭으로 ChartPage 이동만 책임.
- **TriggerHistoryTable**: 종목 1개 × 최근 N건 뷰. 자체 fetch. /triggers 와 컬럼 일관.
- **ChartPage**: 종목 선택 + 토글 상태 관리. 패널 컴포넌트들은 자체 fetch 하므로 ChartPage 는 ticker 만 prop 으로 넘긴다.
- **PriceChart**: 가격/지표 라인 + 신규 overlay (pivot/stop 선 + 트리거 마커). overlay 데이터는 prop 으로 받음 (fetch 안 함).
- **각 카드 컴포넌트**: 단일 데이터 fetch + 표시. 빈 상태 자체 처리.

## 테스트

### API
`tests/api/test_triggers_router.py` (신규):
- 빈 결과
- ticker 필터
- date 필터
- from/to 기간 필터
- decision 필터
- trigger_type 필터
- 복합 필터
- limit / offset
- stocks 조인 (name 포함)

### 프론트
기존 패턴 (vitest 또는 RTL 없으면 컴파일/타입체크 + 수동 확인). 신규 컴포넌트는 각자 빈 상태 / 로딩 / 에러 / 정상 표시 시각 검증.

## 데이터 흐름 다이어그램

```
[/triggers]                    [/chart/{ticker}]
     │                                │
     ├── /api/triggers (필터)         ├── /api/stocks/{ticker}
     │                                ├── /api/classifications?ticker=
     │                                ├── /api/indicators/daily?ticker=
     │                                ├── /api/signals?ticker=
     │                                ├── /api/performance?ticker=
     │                                └── /api/triggers?ticker=&limit=20
     │                                     │
     │                                     └─→ PriceChart triggerEvents
     │                                     └─→ TriggerHistoryTable rows
     ▼                                ▼
   날짜 그룹 테이블                   차트 + 5 카드 + 표
   행 클릭 → /chart/{ticker} ───────→ 같은 종목 ChartPage
```

## 작업 분리 (plan task 후보)

1. `GET /api/triggers` 라우터 + 테스트
2. `/triggers` 페이지 (NAV_ITEMS + Route + 페이지 컴포넌트 + 필터 + 날짜 그룹 + 테이블)
3. 분석 카드 컴포넌트 5개 (각자 빈 상태 처리)
4. PriceChart overlay 확장 (pivot/stop 선, 트리거 마커) + 토글 체크박스
5. ChartPage 통합 (카드 그리드 + overlay 데이터 전달)

각 task 는 독립 commit 가능. 1 → 2 → 3 → 4 → 5 순서. (3 은 1 의 응답 형식 확정 후 가능; 5 는 3, 4 모두 후.)

## 성공 기준

- `/triggers` 페이지에서 결정론 트리거 게이트 통과한 모든 LLM 평가 이벤트를 날짜 그룹으로 확인할 수 있다.
- 필터 (종목 / decision / trigger_type / 기간) 가 동작한다.
- ChartPage 에서 종목을 선택하면 차트 위에 pivot/stop 가로선과 트리거 마커가 표시되고, 차트 아래에 분류 / 결정론 지표 / 매수 시그널 / 성과 / 트리거 이력 5개 카드가 표시된다.
- overlay 는 기존 SMA 토글과 같은 패턴의 체크박스로 켜고 끌 수 있다.
- /triggers 의 행과 ChartPage 의 차트 마커 / 트리거 이력 표가 같은 데이터를 가리킨다 (날짜/decision 일치).
- 데이터가 없는 종목은 빈 상태 카드를 표시하고 ChartPage 자체는 깨지지 않는다.
