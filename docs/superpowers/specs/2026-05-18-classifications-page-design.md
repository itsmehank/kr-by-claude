# LLM 분류 결과 페이지 Design

**Goal:** `/classifications` 라우트에서 `weekly_classification` 테이블의 LLM 분류 결과 (watch / entry / ignore) 를 브라우저에서 확인한다. 현재는 DB+Slack digest 만 존재하고 UI 없음. 사용자가 "이번 주 새로 분류된 watch/entry 종목" 을 빠르게 보고, reasoning 전문 + 차트로 액션 결정.

**Scope:** 표시 + 필터 + row expand + 차트 페이지 라우팅. 직접 분류 수정/취소, 백테스트 결과 통합, expires_at 자동 숨김은 out of scope.

**Single source of truth:** `weekly_classification` 테이블 (kr_pipeline/llm_runner/store.py 가 INSERT 함). 두 source 모두 같은 테이블 — `source` 컬럼 (`weekend` / `daily-delta`) 으로 구분.

---

## 1. 라우팅 & 네비게이션

`web/src/App.tsx`:

- 사이드바 `NAV_ITEMS` 에 새 항목 추가 — `{ to: "/classifications", label: "Classifications", kr: "LLM 분류", Icon: ListChecks }` (lucide-react `ListChecks` 또는 비슷한 아이콘)
- 위치: Performance 와 Runner 사이 (LLM 출력 결과 그룹).
- 라우트: `<Route path="/classifications" element={<ClassificationsPage />} />`

---

## 2. Backend API

### 2-1. 신규 엔드포인트: `GET /api/classifications`

**쿼리 파라미터:**

| 이름 | 타입 | default | 의미 |
|---|---|---|---|
| `lookback_days` | int | 14 | `classified_at >= now() - lookback_days` |
| `classifications` | repeated str (FastAPI `list[str]`) | `None` | `["watch","entry"]` 같은 필터. None 이면 all. |
| `sources` | repeated str | `None` | `["weekend","daily-delta"]`. None 이면 all. |
| `min_confidence` | float | 0.0 | `confidence >= min_confidence` |
| `sort` | str | `"classified_at_desc"` | `"classified_at_desc"` 또는 `"confidence_desc"` |
| `limit` | int | 100 | 최대 행 수 |

**SQL 핵심:**

```sql
WITH latest AS (
  SELECT DISTINCT ON (symbol)
         symbol, classified_at, market, classification, pattern,
         pivot_price, pivot_basis, base_high, base_low, base_depth_pct,
         base_start_date, risk_flags, confidence, reasoning, source,
         expires_at, llm_call_duration_s, llm_input_tokens, llm_output_tokens
    FROM weekly_classification
   WHERE classified_at >= NOW() - (%s || ' days')::interval
   ORDER BY symbol, classified_at DESC
)
SELECT l.*, s.name, s.sector
  FROM latest l
  JOIN stocks s ON s.ticker = l.symbol
 WHERE (%(classifications)s IS NULL OR l.classification = ANY(%(classifications)s))
   AND (%(sources)s IS NULL OR l.source = ANY(%(sources)s))
   AND l.confidence >= %(min_confidence)s
 ORDER BY {sort_clause}
 LIMIT %(limit)s
```

여기서 `{sort_clause}`:
- `sort=classified_at_desc` → `l.classified_at DESC`
- `sort=confidence_desc` → `l.confidence DESC NULLS LAST, l.classified_at DESC`

(SQL 인젝션 방지 위해 직접 문자열 치환 — allowlist 매핑으로 처리. 사용자 입력 그대로 SQL 안에 안 넣음.)

— `DISTINCT ON (symbol)` 로 종목별 최신 1건만. 사용자가 "지난 주 watch 였다가 이번 주 ignore" 같은 변화를 보고 싶으면 별도 종목 상세 페이지 (out of scope).

**응답 모델** (Pydantic):

```python
class ClassificationRow(BaseModel):
    symbol: str
    name: str
    market: str
    sector: str | None
    classification: str          # watch / entry / ignore
    pattern: str | None
    pivot_price: float | None
    pivot_basis: str | None
    base_high: float | None
    base_low: float | None
    base_depth_pct: float | None
    base_start_date: date | None
    risk_flags: list[str]        # 빈 리스트 가능
    confidence: float | None
    reasoning: str | None
    source: str                  # weekend / daily-delta
    classified_at: datetime
    expires_at: datetime | None
    llm_call_duration_s: float | None
    llm_input_tokens: int | None
    llm_output_tokens: int | None
```

응답 — `list[ClassificationRow]`.

### 2-2. 파일 위치

`api/routers/classifications.py` 신규. `api/main.py` 에 `include_router(classifications.router)` 추가.

---

## 3. Frontend

### 3-1. 타입

`web/src/lib/types.ts` 에 추가:

```typescript
export interface Classification {
  symbol: string;
  name: string;
  market: string;
  sector: string | null;
  classification: string;
  pattern: string | null;
  pivot_price: number | null;
  pivot_basis: string | null;
  base_high: number | null;
  base_low: number | null;
  base_depth_pct: number | null;
  base_start_date: string | null;
  risk_flags: string[];
  confidence: number | null;
  reasoning: string | null;
  source: string;
  classified_at: string;
  expires_at: string | null;
  llm_call_duration_s: number | null;
  llm_input_tokens: number | null;
  llm_output_tokens: number | null;
}
```

### 3-2. `web/src/pages/ClassificationsPage.tsx`

**컴포넌트 구조:**

```
ClassificationsPage
├── 헤더
│    ├ caps "Classifications"
│    ├ 큰 제목 "LLM 분류"
│    └ 카운트 칩들 (Watch N · Entry M · Ignore K)
│
├── 필터 바 (compact)
│    [ 최근 N 일: 14 ▼ ]   [ Classification: ✓ watch ✓ entry ☐ ignore ]
│    [ Source: weekend, daily-delta ]   [ min conf: 0.0 ]
│    [ 정렬: 시각 최신 ▼ ]   [ 🔄 새로고침 ]
│
├── 그룹별 리스트 (classification 별로 grouping, watch → entry → ignore)
│    각 그룹은 collapsible header + 리스트.
│    Default: watch / entry 펼침, ignore 접힘.
│    각 row 클릭 시 자기 자리에서 expand:
│
│    [▼] 001450 현대해상 [watch] flat_base 0.55 · 11분 전
│         pivot: 32,600 · base: 28,900 ~ 33,000 (12.3%, 2026-03-08 ~ )
│         risk_flags: [drawdown_high]
│         reasoning ━━━━━━━━━━━━━━━━━━━━━━━━━━
│         이 종목은 최근 8주 간 마감가가 ...
│         (whitespace-pre-wrap)
│         ──────────────────────────────────
│         confidence 0.55 · expires 05-25 · 92.3 초
│         [차트 보기 →] 클릭 시 /chart/001450
│
└── 빈 상태 안내
     "최근 N일간 분류 결과 없음. /runner 에서 'LLM 주말 분류' 또는 'LLM 평일 전체 분석' 실행."
```

**상태:**
- `useState<FilterState>` — lookback_days / classifications / sources / min_confidence / sort
- `useState<Set<string>>` — expanded rows (symbol 으로 식별)
- `useState<{watch: boolean, entry: boolean, ignore: boolean}>` — 그룹 펼침/접힘. ignore default `false` (접힘).
- `useQuery<Classification[]>` queryKey `["classifications", filters]`, queryFn 이 filter state 로 API 호출

**Filter UI 세부:**
- `lookback_days`: `<select>` 옵션 7 / 14 / 30 / 90 일
- `classifications`: 3개 checkbox (watch / entry / ignore). 기본 watch+entry 만 체크.
- `sources`: 2개 checkbox (weekend / daily-delta). 기본 둘 다 체크.
- `min_confidence`: number input 0.0~1.0
- `sort`: `<select>` "시각 최신" (classified_at DESC, default) / "Confidence" (confidence DESC NULLS LAST, then classified_at DESC)

**Row collapsed (header):**
- 화살표 (▶/▼)
- 종목 코드 + 이름
- classification 배지 (watch 파랑, entry 초록, ignore 회색)
- pattern (있으면)
- confidence (있으면 소숫점 2자리)
- relative time (예: "11분 전" — utils 의 `relativeTime`)
- KST tooltip (기존 RunnerPage 패턴 재사용 — `formatKst`)

**Row expanded (추가 표시):**
- pivot_price (있으면), pivot_basis, base_high/low/depth/start_date
- risk_flags (있으면) — 각각 amber/danger 칩
- reasoning 박스 (whitespace-pre-wrap, 최대 높이 + scroll)
- confidence / expires_at / llm_call_duration_s
- `<Link to={`/chart/${symbol}`}>차트 보기 →</Link>`

**Sort/필터 적용은 클라이언트 side 가 아니라 서버 side** — query key 가 바뀌면 새 fetch.

**Row 인터랙션:**
- Row header 전체가 클릭 가능 (expand/collapse 토글)
- Row 안의 "차트 보기 →" 는 `<Link>` — 클릭 시 `event.stopPropagation()` 으로 row toggle 방지하고 라우팅만 발생

### 3-3. App.tsx 변경

- `import ClassificationsPage from "./pages/ClassificationsPage";`
- `NAV_ITEMS` 에 `{ to: "/classifications", label: "Classifications", kr: "LLM 분류", Icon: ListChecks }` 삽입 (Performance 다음, Runner 직전)
- `<Routes>` 에 `<Route path="/classifications" element={<ClassificationsPage />} />`

---

## 4. Testing

### Backend

`tests/test_api_classifications.py` 신규:

1. **기본 응답 구조** — 빈 결과여도 200 + 빈 list
2. **lookback_days 필터** — 그 이전 행 제외
3. **classification 필터** — `classifications=watch&classifications=entry` 면 ignore 제외
4. **source 필터** — `sources=weekend` 면 daily-delta 제외
5. **min_confidence 필터** — 그 미만 제외
6. **DISTINCT ON (symbol)** — 같은 symbol 의 두 분류 행 insert → 최신 1건만 응답
7. **stocks join** — name / sector 가 정상 포함

### Frontend

- tsc 0 errors
- 수동 검증 (Goal State):
  - `/classifications` 진입 → 헤더 / 필터 바 / 그룹별 리스트 표시
  - 필터 조작 → 결과 즉시 새로고침
  - row 클릭 → expand, 다시 클릭 → collapse
  - ignore 그룹 토글 → 펼침/접힘
  - 차트 보기 클릭 → `/chart/<symbol>` 로 라우팅
  - 빈 결과 (예: lookback_days=1) → 안내 메시지
  - 사이드바 새 메뉴 "LLM 분류" 노출

---

## 5. Out of scope (별도 plan)

- **종목별 분류 이력 시간순 페이지** (예: `/classifications/:symbol`) — 한 종목의 LLM 평가 변화 추적
- **`expires_at` 자동 숨김** — 만료된 watch 결과 자동 제외. 일단은 모든 행 표시.
- **entry_params 와의 통합** — entry 분류 종목의 진입 파라미터 보기 (이미 SignalsPage 에 있을 가능성). 별도 페이지 / 별도 작업.
- **분류 수동 수정 / 폐기** — UI 에서 watch → ignore 변경 같은 액션
- **CSV / Slack 알림 재전송** 같은 export 기능
- **백테스트 결과 (signal_performance) 통합** — entry 분류 종목의 사후 성과
- **expires_at < now() 인 row 시각적 dim** — 만료된 분류 표시

---

## Architecture summary

```
weekly_classification (DB)
        │
        └─→ GET /api/classifications  (신규)
              ├ DISTINCT ON (symbol) → 종목별 최신 1건
              ├ lookback_days / classifications / sources / min_confidence / limit 필터
              ├ JOIN stocks (name, sector)
              └ ORDER BY classified_at DESC LIMIT N
                    │
                    ▼
              ClassificationsPage (신규)
                ├ 헤더 (Watch/Entry/Ignore 카운트)
                ├ 필터 바 (server-side 적용)
                ├ 그룹별 리스트 (watch → entry → ignore)
                └ row expand: pivot/base/risk_flags/reasoning/[차트 보기]
                      │
                      ▼
                  /chart/:symbol (기존 ChartPage)
