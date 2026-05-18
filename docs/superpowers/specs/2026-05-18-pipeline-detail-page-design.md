# Pipeline 상세 페이지 Design

**Goal:** `/runner/:pipelineId` 라우트로 각 pipeline 의 상세 정보 페이지를 제공한다. 사용자는 `/runner` 테이블에서 작업명을 클릭해 해당 작업의 개요, 실행 주기, 입출력 테이블, 의존 관계, 실행 모드, 최근 실행 이력을 한 화면에서 확인하고 수동 실행도 그 자리에서 트리거할 수 있다.

**Scope:** 정보 표시 + 라우팅 + 의존 관계 reverse lookup. 시각화 그래프, 모드별 CLI 복사, 로그 streaming 같은 확장은 out of scope.

**Single source of truth:** `kr_pipeline/llm_runner/pipeline_specs.py` 의 `PIPELINE_SPECS` 가 페이지에 표시되는 모든 정적 정보의 출처. LLM 동적 생성 없음.

---

## 1. 데이터 모델 (`PIPELINE_SPECS` 확장)

각 spec 에 4개 필드를 추가한다.

```python
{
    "id": "indicators-daily",
    # ...기존 필드 (group, label, description, module, pipeline_db_name,
    #              mode_prefix, modes, default_cron, schedule_label)...
    "long_description": "일봉 OHLCV 데이터를 기반으로 기술 지표를 계산합니다.\n\n계산 항목:\n- 이동평균선 (10/21/50/150/200일)\n- 52주 고가·저가\n- RS Rating\n- Minervini Trend Template 통과 여부\n- Pocket Pivot / Distribution Day\n\n선행 작업: ohlcv, corporate-actions",
    "inputs": ["daily_ohlcv", "corporate_actions"],
    "outputs": ["daily_indicators"],
    "depends_on": ["ohlcv", "corporate-actions"],
}
```

**필드 의미:**

- `long_description: str` — plain text. 단락 구분은 `\n`. 줄바꿈 외의 포맷팅 (굵게, 리스트 마커) 은 텍스트로 직접 표현. Frontend 는 `whitespace-pre-wrap` 으로 그대로 렌더.
- `inputs: list[str]` — 이 작업이 **읽는** DB 테이블명 리스트. 비어 있으면 외부 데이터 소스 (예: KRX API) 만 사용.
- `outputs: list[str]` — 이 작업이 **쓰는** DB 테이블명 리스트.
- `depends_on: list[str]` — 이 작업 전에 완료되어야 의미가 있는 다른 pipeline 의 `id` 리스트.

**후속 작업 (`consumed_by`) 은 명시하지 않는다.** 양방향 명시 시 PIPELINE_SPECS 안에 일관성 위험. Backend 에서 `depends_on` 의 reverse lookup 으로 동적 계산.

**확정된 의존 매핑:**

| id | depends_on | inputs | outputs |
|---|---|---|---|
| universe | (none) | (none) | stocks |
| ohlcv | (none) | (none) | daily_ohlcv |
| weekly | ohlcv | daily_ohlcv | weekly_ohlcv |
| corporate-actions | (none) | (none) | corporate_actions |
| indicators-daily | ohlcv, corporate-actions | daily_ohlcv, corporate_actions | daily_indicators |
| indicators-weekly | weekly, corporate-actions | weekly_ohlcv, corporate_actions | weekly_indicators |
| market-context | indicators-daily | daily_indicators, daily_ohlcv | market_context_daily |
| llm-full-daily | indicators-daily, market-context | daily_indicators, market_context_daily, daily_ohlcv | llm_signals, signal_performance |
| llm-weekend | indicators-daily, indicators-weekly, market-context | daily_indicators, weekly_indicators, market_context_daily | llm_classifications |
| llm-performance | ohlcv | daily_ohlcv, llm_signals | signal_performance |

테이블명은 실제 DB schema (`kr_pipeline/db/schema.sql`) 와 일치시킨다. 구현 시 schema 와 다르면 그 작업의 inputs/outputs 를 schema 기준으로 보정.

---

## 2. Backend API

### 2-1. 신규 엔드포인트: `GET /api/pipelines/{pipeline_id}`

- **200 응답** — pipeline detail dict
- **404 응답** — `pipeline_id` 가 PIPELINE_SPECS 에 없을 때

응답 구조:

```json
{
  "id": "indicators-daily",
  "group": "indicators",
  "label": "Indicators (일봉)",
  "description": "(short, 한 줄)",
  "long_description": "(plain text + \\n)",
  "module": "kr_pipeline.indicators",
  "schedule_label": "평일 매일",
  "default_cron": "0 19 * * 1-5",
  "inputs": ["daily_ohlcv", "corporate_actions"],
  "outputs": ["daily_indicators"],
  "depends_on": [
    {"id": "ohlcv", "label": "OHLCV (일봉)"},
    {"id": "corporate-actions", "label": "Corporate Actions"}
  ],
  "consumed_by": [
    {"id": "market-context", "label": "Market Context"},
    {"id": "llm-full-daily", "label": "LLM 평일 전체 분석"},
    {"id": "llm-weekend", "label": "LLM 주말 분류"}
  ],
  "modes": [
    {"id": "incremental", "label": "증분 (30일)",
     "args": ["--target=daily", "--mode=incremental", "--window-days=30"],
     "is_heavy": false}
  ],
  "recent_runs": [
    {
      "id": 1234,
      "mode": "daily-incremental",
      "status": "success",
      "started_at": "2026-05-18T19:00:01+09:00",
      "finished_at": "2026-05-18T19:00:08+09:00",
      "rows_affected": 42980,
      "duration_seconds": 7,
      "error": null
    }
  ]
}
```

**`consumed_by` 계산:** PIPELINE_SPECS 를 한 번 순회하면서 `depends_on` 에 현재 pipeline_id 가 포함된 다른 spec 들을 모은다. 응답 시 `{id, label}` 페어로.

**`recent_runs` 쿼리:**
```sql
SELECT id, mode, status, started_at, finished_at, rows_affected, error
  FROM pipeline_runs
 WHERE pipeline = %s
 ORDER BY id DESC LIMIT 10
```

`pipeline_db_name` 으로 조회 후, `mode_prefix` 가 있는 spec (indicators-daily/weekly) 은 Python 단에서 `matches_mode_prefix(mode, prefix)` 로 필터해서 상위 5건만 응답. (LIMIT 10 + filter 5 — 기존 `/api/runs/summary` 와 같은 패턴.)

### 2-2. 기존 엔드포인트 영향

- `GET /api/pipelines` — PIPELINE_SPECS 전체를 반환하므로 새 필드 자동 포함. 코드 변경 없음.
- `GET /api/runs/summary` — 응답에 새 필드 추가하지 않음 (테이블 행에는 필요 없음). 코드 변경 없음.
- `POST /api/runner/run` — 변경 없음.

### 2-3. 라우터 위치

`api/routers/pipelines.py` 에 새 엔드포인트 추가. 기존 `list_pipelines()` 와 같은 파일.

---

## 3. Frontend

### 3-1. 라우팅

`web/src/App.tsx`:
```tsx
<Route path="/runner/:pipelineId" element={<PipelinePage />} />
```

기존 `/runner` 라우트는 그대로. 사이드바 네비게이션에는 노출하지 않는다 (상세 페이지는 테이블에서만 진입).

### 3-2. `RunnerPage` 변경

테이블의 작업 라벨을 `<Link>` 로 감싼다:

```tsx
<Link to={`/runner/${p.pipeline_id}`} className="hover:text-accent">
  {p.label}
</Link>
```

기존 (i) tooltip 은 그대로 유지. 모듈명 줄 (`kr_pipeline.indicators`) 도 그대로.

### 3-3. `web/src/pages/PipelinePage.tsx` 신규

**컴포넌트 구조:**

```
PipelinePage
├── 헤더: [← 목록으로] / 작업명 + 모듈명 / [▶ 실행]
├── 개요 박스 (whitespace-pre-wrap)
├── 실행 주기 박스 (schedule_label + cron)
├── 입출력 박스 (2-column: 입력 / 출력 테이블 리스트)
├── 의존 관계 박스 (선행 / 후속 — 각 항목 Link 칩)
├── 실행 모드 박스 (모드 리스트 + 각 모드 ▶ 버튼)
└── 최근 실행 박스 (5건, StatusChip + relative + rows + duration)
```

**상태:**
- `useQuery(["pipeline", pipelineId])` → `GET /api/pipelines/{id}`
- `useState<{mode_id: string} | null>` for "이 모드로 실행" 클릭 시 RunDialog 에 모드 선택 사전 지정
- 페이지 상단 [▶ 실행] 은 모드 미지정 (RunDialog 가 첫 모드 default 로)
- 모드 박스의 [▶ 이 모드로 실행] 은 해당 모드 사전 지정

**RunDialog 재사용:** 기존 `RunnerPage` 의 RunDialog 컴포넌트를 별도 파일 (`web/src/components/RunDialog.tsx`) 로 추출해 양쪽에서 import. 추출 시 props 에 `initialModeId?: string` 추가. PipelinePage 가 모드 사전 지정 시 그 값으로 초기화.

**의존 그래프 칩:** 선행/후속 각 항목을 `<Link to={`/runner/${depId}`}>` + 칩 스타일로. 클릭 시 같은 페이지로 라우팅, 페이지가 새 데이터로 refetch. 브라우저 히스토리 자연스럽게.

**최근 실행 행:**
- relative time (예: "11분 전") 에 KST absolute tooltip (기존 RunnerPage 패턴 재사용 — `formatKst` 헬퍼는 utils 로 추출 또는 PipelinePage 내 재정의)
- mode 컬럼 추가 (테이블에는 없던 정보) — 어떤 모드로 실행됐는지 보임
- 클릭 가능한 row 는 아님 (run detail 페이지는 별도 기능, out of scope)

**Error states:**
- 로딩 중: "로딩 중…"
- 404: "작업을 찾을 수 없습니다" + [← 목록으로]
- 네트워크 에러: 에러 메시지 + 새로고침 버튼

### 3-4. 타입

`web/src/lib/types.ts` 에 새 타입:

```typescript
export interface PipelineRef {
  id: string;
  label: string;
}

export interface PipelineRecentRun {
  id: number;
  mode: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  rows_affected: number | null;
  duration_seconds: number | null;
  error: string | null;
}

export interface PipelineDetail {
  id: string;
  group: string;
  label: string;
  description: string;
  long_description: string;
  module: string;
  schedule_label: string;
  default_cron: string;
  inputs: string[];
  outputs: string[];
  depends_on: PipelineRef[];
  consumed_by: PipelineRef[];
  modes: PipelineMode[];
  recent_runs: PipelineRecentRun[];
}
```

기존 `PipelineSpec` 은 `long_description / inputs / outputs / depends_on: string[]` 만 추가 (raw spec 형태).

---

## 4. Testing

### Backend (`tests/`)

- **`test_pipeline_specs.py`** 추가 테스트:
  - 모든 spec 이 `long_description / inputs / outputs / depends_on` 필드 보유 + 타입 검증
  - `depends_on` 의 모든 id 가 PIPELINE_SPECS 의 실제 id 에 존재 (참조 무결성)
  - `long_description` 가 비어 있지 않음 (`len > 20`)

- **신규 `test_api_pipeline_detail.py`**:
  - `GET /api/pipelines/indicators-daily` 200 + 응답 키 모두 존재
  - `GET /api/pipelines/nonexistent` 404
  - `consumed_by` reverse lookup 정확성 — 예: `ohlcv` 의 consumed_by 에 `weekly`, `indicators-daily`, `llm-performance` 포함 (`depends_on` 매핑 기준)
  - `recent_runs` 에 mode_prefix 필터 적용 — `indicators-daily` 의 recent_runs 가 `daily-` prefix 만 포함 (DB 에 `daily-incremental` + `weekly-incremental` 두 행 넣고 검증)

### Frontend

- tsc 0 errors
- 수동 검증 항목 (Goal State):
  - `/runner` 의 작업명 클릭 → `/runner/<id>` 로 라우팅
  - 페이지에 6개 박스 모두 표시
  - 선행/후속 칩 클릭 → 해당 pipeline 페이지로 라우팅 + 데이터 새로고침
  - [▶ 실행] / [▶ 이 모드로 실행] 둘 다 RunDialog 띄움 + 후자는 모드 사전 지정됨
  - 뒤로가기 / 앞으로가기 정상 작동
  - 404 페이지 (잘못된 id 직접 URL 입력) — "작업을 찾을 수 없습니다"

---

## 5. Out of scope (이 spec 에서 다루지 않음)

별도 plan 으로 진행:

- **Market Context cron fallback** (옵션 c): `api/services/market_context_builder.py` 의 SQL 을 `WHERE date <= on_date ORDER BY date DESC LIMIT 1` 로 변경. 오늘 행 없으면 가장 최근 평일 데이터 반환.
- **`llm-full-daily` cron 시간 재배치** (옵션 a): 현재 `30 16 * * 1-5` → 새 시간 (예: `0 20 * * 1-5`). 정확한 시간은 별도 결정.
- **모드별 CLI 명령어 복사 기능** (Rich 옵션에서 본 [Copy CLI]) — 사용자가 Standard 를 선택했으므로 제외.
- **실행 이력 graph / spark line** — Rich 옵션. 제외.
- **DB schema 표시 / log streaming** — Everything 옵션. 제외.
- **모드별 cron line 개별 toggle** — 별도 큰 plan (옵션 C, 이전 대화에서 언급된 미래 확장).

---

## Architecture summary

```
PIPELINE_SPECS (확장)
  + long_description, inputs, outputs, depends_on
        │
        ├─→ GET /api/pipelines           (변경 없음 — 자동 포함)
        ├─→ GET /api/pipelines/{id}      (신규: detail + consumed_by reverse + recent_runs)
        └─→ GET /api/runs/summary        (변경 없음)
                │
                ▼
           PipelinePage (신규)
             ├ 개요 / 주기 / 입출력 / 의존 / 모드 / 최근 실행
             └ RunDialog (RunnerPage 와 공유, 컴포넌트 추출)
                │
                ▼
           ← Link to other pipeline detail (의존 칩)
