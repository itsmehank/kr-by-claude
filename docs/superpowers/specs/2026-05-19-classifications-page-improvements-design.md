# ClassificationsPage 개선 (A 사이클) Design

**Goal:** `/classifications` 페이지의 각 분류 row 에 책 원전 (Minervini / O'Neil) 에 충실한 tooltip 사전, market/sector 표시, 분석 기준일, 차트 새 탭 열기를 추가해 사용자가 정의/맥락을 한 번에 이해할 수 있게 만든다.

**Scope:** A 사이클 — UI 표시 + DB 컬럼 `analyzed_for_date` 추가 + tooltip 사전. **Reasoning 의 prompt 출력 형식 개선** (사용자 검토 항목 4) 은 별도 B 사이클.

**Single source of truth:** `weekly_classification` 테이블 (LLM 분류 결과). 기존 컬럼 + 신규 `analyzed_for_date`.

---

## 1. 데이터 모델 — `weekly_classification.analyzed_for_date` 추가

분석에 사용된 데이터의 기준일을 명시적으로 저장. LLM 호출 시각 (`classified_at`) 과 구분.

### 1-1. Schema 변경

`kr_pipeline/db/schema.sql` 의 `weekly_classification` 테이블 정의에 컬럼 추가:

```sql
analyzed_for_date DATE,   -- LLM 분석에 사용된 데이터의 기준일 (= weekend.py 의 as_of)
```

위치는 `classified_at` 다음. NOT NULL 아님 — 기존 행 backfill 안 함.

### 1-2. Migration

```sql
ALTER TABLE weekly_classification ADD COLUMN IF NOT EXISTS analyzed_for_date DATE;
```

`kr_test` DB 에도 동일 적용.

### 1-3. 적재 시점

- `kr_pipeline/llm_runner/store.insert_classification(..., analyzed_for_date: date | None = None)` 인자 추가
- `kr_pipeline/llm_runner/weekend.py._process_one` 가 호출 시 `as_of` (run 의 `as_of` 인자) 전달
- `kr_pipeline/llm_runner/daily_delta.py._process_one` 가 호출 시 `as_of` 전달

기존 row 의 `analyzed_for_date` 는 NULL — 정확한 기준일 알 수 없어서 backfill 안 함.

---

## 2. Backend API

### 2-1. `api/routers/classifications.py` 변경

SQL 의 `latest` CTE + 본 SELECT 에 `analyzed_for_date` 추가. Response 모델에도 포함.

### 2-2. `api/schemas/classification.py` — `ClassificationRow` 확장

```python
class ClassificationRow(BaseModel):
    # ...기존 필드...
    classified_at: datetime
    analyzed_for_date: date | None   # ← 추가
    expires_at: datetime | None
    # ...
```

---

## 3. Frontend 타입 + UI

### 3-1. `web/src/lib/types.ts`

`Classification` interface 에 추가:

```typescript
analyzed_for_date: string | null;
```

### 3-2. UI 표시 위치

| 위치 | 추가 정보 |
|---|---|
| Row header (collapsed) — 종목명 뒤 | 작은 회색 메타: `· {sector} · {market}` (예: `· 보험 · KOSPI`) |
| Row header — `pattern` 옆 | hover tooltip — pattern 정의 |
| Row header — `conf {value}` 옆 | (i) 아이콘 + hover tooltip — confidence 설명 |
| Row details — 각 risk_flag chip | hover tooltip — flag 정의 |
| Row details — `Pivot` 라벨 옆 | (i) 아이콘 + tooltip |
| Row details — `Base` 라벨 옆 | (i) 아이콘 + tooltip |
| Row details — 메타 줄 | `기준일: YYYY-MM-DD` (analyzed_for_date 있을 때만) |
| Row details — `차트 보기 →` 링크 | `target="_blank" rel="noopener noreferrer"` |

Header 정보 밀도 — market/sector 만 추가 (analyzed_for_date 는 details). 헤더가 너무 복잡해지지 않게.

---

## 4. Tooltip 사전 (frontend dict)

**원칙:** tooltip 한 줄 — 책 원전이면 그대로 정의, 임계값이 휴리스틱이면 "(실무 휴리스틱)" + "(O'Neil 원전: ...)" 짧게 명시.

### 4-1. Pattern (5개)

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
};
```

**double_bottom 의 buy point 정정** — 두 번째 바닥(D)이 아니라 W 중앙 peak(C) (사용자 검토 반영).

### 4-2. Risk Flag (13개 — prompt §5 taxonomy)

```typescript
const RISK_FLAG_DESCRIPTIONS: Record<string, string> = {
  climax_run:
    "1~3주에 가격 25%+ 상승 + 가장 큰 주봉/거래량 — Minervini Stage 3 climax 경고.",
  late_stage_base:
    "현재 Stage 2 advance 의 3번째 이상 base. O'Neil: base 3~4는 경계, Minervini: base 4+ 위험.",
  extended_from_ma:
    "50일 이평선 위 15%+ — 추격 진입 위험 (실무 휴리스틱; O'Neil 원전은 pivot 에서 5~10%+ 추격 시 늦은 매수).",
  faulty_pivot:
    "Pivot 의 형태적 결함 (wedging handle, handle이 base 하반부, V자 즉시 신고가, 거래량 없는 돌파 등).",
  low_volume_breakout:
    "돌파 거래량이 50일 평균의 1.5배 미만 (O'Neil: 50% above average 가 최소).",
  narrow_base:
    "패턴별 최소 기간보다 짧은 base.",
  wide_and_loose:
    "주봉 변동폭이 erratic / 시장 조정 대비 2.5배 초과 — 거래 어려운 base (O'Neil).",
  prior_uptrend_insufficient:
    "52주 저점 대비 25% 미만 상승 — Minervini Trend Template #5 위반 (Stage 2 진입 부족).",
  volume_contraction_on_advance:
    "상승 중 거래량 감소 — 수요 약화 / 기관 매수 부족 신호 (O'Neil: lost appetite).",
  reverse_split_distortion:
    "최근 12주 내 reverse split — 가격 왜곡 가능 (실무 휴리스틱, 책 원전 아님).",
  unfavorable_market_context:
    "시장 downtrend/correction 또는 distribution day 5개 이상 (25 sessions; O'Neil 의 '4~5주' 중 느슨한 쪽, IBD/Dr.K 표준은 20일).",
  etf_methodology_mismatch:
    "ETF/fund — Minervini/O'Neil 개별 leadership 종목 방법론 적용 안 됨.",
  thin_liquidity_us_only:
    "(US only) 일평균 거래대금 $5M 미만 (실무 변형; O'Neil disciple 원전은 35~50만 주 최소).",
};
```

### 4-3. 필드 tooltip (pivot / base / confidence)

```typescript
const FIELD_TOOLTIPS = {
  pivot:
    "베이스 안에서 거래량 동반으로 이 가격을 돌파하면 buy point (Minervini/O'Neil 진입 기준).",
  base:
    "가격 통합 구간 (low~high, 형성 시작일~현재). depth = 고점 대비 저점 하락률. 매물 소화 후 새 추세 시작.",
  confidence:
    "LLM 의 분류 자신감 (0~1). 데이터 부족 / 모호한 패턴 / 시장 컨텍스트 불리 시 낮아짐.",
};
```

### 4-4. Fallback

DB 에 dict 에 없는 새 값이 들어오면 (예: 향후 prompt 확장) tooltip 텍스트는 raw 코드명 그대로 표시 — 깨지지 않게:

```typescript
content={RISK_FLAG_DESCRIPTIONS[flag] ?? flag}
```

---

## 5. 컴포넌트 변경 위치 (`web/src/pages/ClassificationsPage.tsx`)

### 5-1. RowHeader

기존:
```tsx
<span className="num text-data text-ink shrink-0">{row.symbol}</span>
<span className="text-data text-ink truncate flex-1 min-w-0">{row.name}</span>
<ClassificationChip ... />
{row.pattern && <span className="text-data-xs text-muted">{row.pattern}</span>}
{row.confidence != null && <span className="num text-data-xs text-faint">conf {row.confidence.toFixed(2)}</span>}
```

변경 후:
```tsx
<span className="num text-data text-ink shrink-0">{row.symbol}</span>
<span className="text-data text-ink truncate min-w-0">{row.name}</span>
<span className="text-data-xs text-faint shrink-0 whitespace-nowrap">
  {row.sector && `· ${row.sector}`}{row.market && ` · ${row.market}`}
</span>
<div className="flex-1" />
<ClassificationChip ... />
{row.pattern && (
  <Tooltip content={PATTERN_DESCRIPTIONS[row.pattern] ?? row.pattern}>
    <span className="text-data-xs text-muted cursor-help underline decoration-dotted decoration-faint underline-offset-2">
      {row.pattern}
    </span>
  </Tooltip>
)}
{row.confidence != null && (
  <span className="num text-data-xs text-faint shrink-0 flex items-center gap-1">
    conf {row.confidence.toFixed(2)}
    <Tooltip content={FIELD_TOOLTIPS.confidence}>
      <span className="cursor-help"><Info size={11} /></span>
    </Tooltip>
  </span>
)}
```

### 5-2. RowDetails — Pivot/Base 박스

기존 Pivot caps 부분:
```tsx
<div className="caps text-faint">Pivot</div>
```

변경 후:
```tsx
<div className="caps text-faint flex items-center gap-1">
  Pivot
  <Tooltip content={FIELD_TOOLTIPS.pivot}>
    <span className="cursor-help"><Info size={10} /></span>
  </Tooltip>
</div>
```

Base 도 동일 패턴.

### 5-3. RowDetails — Risk Flag chips

기존:
```tsx
<span key={flag} className="chip bg-amber-soft text-amber">
  <AlertTriangle size={11} /> {flag}
</span>
```

변경 후:
```tsx
<Tooltip key={flag} content={RISK_FLAG_DESCRIPTIONS[flag] ?? flag}>
  <span className="chip bg-amber-soft text-amber cursor-help">
    <AlertTriangle size={11} /> {flag}
  </span>
</Tooltip>
```

### 5-4. RowDetails — 메타 줄에 analyzed_for_date 추가

기존:
```tsx
<div className="flex flex-wrap gap-x-4 gap-y-1 text-data-xs text-faint num">
  <span>source: {row.source}</span>
  {row.llm_call_duration_s != null && <span>duration: ...</span>}
  ...
```

변경 후 (analyzed_for_date 를 source 앞에):
```tsx
<div className="flex flex-wrap gap-x-4 gap-y-1 text-data-xs text-faint num">
  {row.analyzed_for_date && <span>기준일: {row.analyzed_for_date}</span>}
  <span>source: {row.source}</span>
  ...
```

### 5-5. RowDetails — 차트 보기 새 탭

기존:
```tsx
<Link
  to={`/chart/${row.symbol}`}
  onClick={(e) => e.stopPropagation()}
  ...
>
```

변경 후:
```tsx
<Link
  to={`/chart/${row.symbol}`}
  target="_blank"
  rel="noopener noreferrer"
  onClick={(e) => e.stopPropagation()}
  ...
>
```

---

## 6. 파일 변경 요약

| 파일 | 변경 |
|---|---|
| `kr_pipeline/db/schema.sql` | `weekly_classification.analyzed_for_date DATE` 추가 |
| (DB migration) | `ALTER TABLE weekly_classification ADD COLUMN IF NOT EXISTS analyzed_for_date DATE` 실행 (kr_pipeline + kr_test) |
| `kr_pipeline/llm_runner/store.py` | `insert_classification` 시그니처에 `analyzed_for_date` 인자 + INSERT SQL 확장 |
| `kr_pipeline/llm_runner/weekend.py` | `_process_one(...)` 가 `as_of` 받고 store 호출 시 전달 |
| `kr_pipeline/llm_runner/daily_delta.py` | 위와 동일 |
| `api/routers/classifications.py` | SQL CTE + 최종 SELECT 에 analyzed_for_date 추가, response 빌드 |
| `api/schemas/classification.py` | `ClassificationRow.analyzed_for_date` 추가 |
| `web/src/lib/types.ts` | `Classification.analyzed_for_date` 추가 |
| `web/src/pages/ClassificationsPage.tsx` | dict 상수 3개 + Tooltip 5곳 + market/sector 표시 + 메타 줄 기준일 + 새 탭 |

---

## 7. Testing

### Backend

- `tests/test_api_classifications.py` — 응답 dict 에 `analyzed_for_date` 키 존재. seed 새 행에 값 채워서 응답 매치
- `tests/test_llm_runner_store.py` (있으면 확장, 없으면 작은 단위 테스트 추가) — `insert_classification(analyzed_for_date=date(2026,5,18))` 호출 시 DB 컬럼에 저장
- `tests/test_llm_runner_main.py` — weekend / daily-delta mode 실행 시 `analyzed_for_date` 가 store 에 전달되는지

### Frontend

- tsc 0 errors
- 수동 검증:
  - row header 에 sector/market 메타 표시
  - pattern / confidence / pivot / base / risk_flag hover 시 tooltip
  - row details 의 메타 줄에 "기준일: YYYY-MM-DD" 표시 (새 분석 결과만)
  - "차트 보기" 클릭 시 새 탭으로 `/chart/<symbol>` 열림 (기존 탭 유지)
  - DB 의 기존 row 는 analyzed_for_date NULL → "기준일" 줄 안 보임 (조건부 렌더)

---

## 8. Out of scope (별도 plan)

- **항목 4 (reasoning prompt 개선)** — B 사이클 별도 brainstorming → plan
  - prompt 의 reasoning schema 를 markdown 구조 또는 structured JSON 으로
  - 새 패턴 추가 (high_tight_flag, 3c_cheat, base_on_base, ascending_base) 도 함께 논의
- `distribution_day_count_last_25` 를 20 sessions 로 통일 — 별도 작업 (DB + 코드 + prompt + 재계산). 현재 tooltip 에 컨텍스트만 명시.
- 기존 row 의 analyzed_for_date backfill — 정확한 기준일 알 수 없어 NULL 유지
- i18n (한국어/영어 toggle) — 현재 한국어 hardcode

---

## Architecture summary

```
weekly_classification (DB)
  + analyzed_for_date DATE  ← 신규

store.insert_classification(..., analyzed_for_date)
        ↑
   weekend.py / daily_delta.py 가 run 의 as_of 전달
        │
        ▼
GET /api/classifications  →  response 에 analyzed_for_date 포함
        │
        ▼
ClassificationsPage
   ├── RowHeader: + market/sector + pattern tooltip + confidence (i)
   ├── RowDetails:
   │    + Pivot/Base 라벨 옆 (i) tooltip
   │    + risk_flag chip 각각 tooltip
   │    + 메타 줄에 "기준일: YYYY-MM-DD"
   │    + 차트 보기 → target="_blank" (새 탭)
   └── dict 상수: PATTERN_DESCRIPTIONS, RISK_FLAG_DESCRIPTIONS, FIELD_TOOLTIPS
```
