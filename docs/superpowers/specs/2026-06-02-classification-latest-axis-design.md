# 분류 "최신 상태" 판정 축 전환 — `classified_at` → `analyzed_for_date`

설계일: 2026-06-02
범위: sub-project ① (3분해 중 첫 번째). ②(as-of 시계열 정합화), ③(백필/백테스트 별도 테이블)은 별도 스펙.

## 배경 / 문제

`weekly_classification`은 한 종목에 분류 행이 시계열로 쌓인다. 각 행에는:
- `classified_at` — LLM 실행 시각 (종목마다 `datetime.now()`로 찍힘)
- `analyzed_for_date` — 분석에 쓰인 데이터 기준일 (= 실행 시작 시 고정된 `as_of`)

현재 "종목의 현재 분류 상태"는 전부 `classified_at DESC`로 판정한다. 이 방식의 두 결함:

1. **지연-실행 분열**: 한 논리적 실행이 자정을 넘기면, 같은 실행의 종목들이 `classified_at` 기준 서로 다른 날짜로 갈라진다. 반면 `analyzed_for_date`는 실행 시작 시 고정(`__main__.py:62-68`)이라 실행 내내 일정하다.
2. **데이터 기준일과 무관**: "현재 상태"가 어느 데이터를 분석한 결과인지(`analyzed_for_date`)를 반영하지 않는다. 같은 데이터 날짜를 재실행해도 구분 못 함.

> 참고: 이 변경은 sub-project ③(백필 별도 테이블)과 독립이다. 백필 오염 방지는 ③의 테이블 분리가 담당하고, ①은 **라이브 테이블의 지연-실행 robust + 같은 데이터 날짜 재실행 정확성**을 담당한다. 라이브 행에서는 `classified_at ≈ analyzed_for_date`라 동작이 대부분 동일하되, 위 두 경계 케이스에서만 달라진다.

## 핵심 규칙

"종목별 최신 1건"과 staleness 판정을 다음 키로 변경한다:

```sql
-- 최신 선택
ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC

-- staleness
WHERE COALESCE(analyzed_for_date, classified_at::date) >= (CURRENT_DATE - lookback_days)
```

- **1차 축** `analyzed_for_date` (데이터 기준일): 지연-실행 robust.
- **2차 타이브레이크** `classified_at`: 같은 데이터 날짜를 두 번 실행하면 "나중에 실행한 것"이 최신.
- **`COALESCE(…, classified_at::date)`**: `analyzed_for_date`가 NULL인 행(레거시 + `disqualified` 이벤트)은 기존 `classified_at` 기준으로 폴백 → 하위호환.

## 변경 대상 — "최신 상태" 판정 6곳

| # | 위치 | 역할 | 비고 |
|---|------|------|------|
| 1 | `api/routers/classifications.py` 내부 CTE (45 staleness, 47 ORDER BY) | web 현재 분류 목록 | **외부 `SORT_CLAUSES`(12-13)는 화면 표시 순서일 뿐 — 변경 안 함** |
| 2 | `kr_pipeline/llm_runner/load.py` `get_active_monitoring` (51,55) | 모니터링용 현재 pivot/stop | |
| 3 | `kr_pipeline/llm_runner/load.py` `get_classified_losing_minervini` (84-87) | disqualify 강등 판정 ("최신이 entry/watch/ignore인데 오늘 minervini 탈락 → 강등") | 강등 결정 기준일에 직접 영향 |
| 4 | `api/services/zip_builder.py` `_fetch_latest_analysis_result` (112) | 검증 ZIP에 넣을 최신 분석 | |
| 5 | `kr_pipeline/llm_runner/compute/payload_lite.py` (35, 159) | 활성 신호 prior 분류 | `WHERE classification IN ('entry','watch')` 필터는 **유지** (절대 최신이 아니라 활성 신호 중 최신) |
| 6 | `kr_pipeline/llm_runner/freeze_cleanup.py` (59-61) | freeze 보존 판정 (활성 종목 freeze 보호) | |

## 유지 대상 — 1곳

| 위치 | 이유 |
|------|------|
| `kr_pipeline/llm_runner/compute/delta.py` (35) `find_new_tickers` | `classified_at >= as_of - 7일`은 "최근에 **LLM을 돌렸나**"(실행 비용 절약) 가드. 데이터 기준 최신성이 아니라 실행 최근성이므로 `classified_at`이 의미상 옳다. 백필은 ③에서 별도 테이블이라 여기서 안 보임. → **변경하지 않음** (이 결정을 코드 주석으로 명시) |

## NULL / disqualified 처리

- **레거시 행**(analyzed_for_date 컬럼 도입 이전): NULL → `COALESCE(…, classified_at::date)` 폴백으로 기존 동작 유지.
- **disqualified 행**: `store.insert_disqualification`이 현재 `analyzed_for_date`를 안 채워 NULL. COALESCE로 강등 실행일(`classified_at::date`) 폴백 → 강등이 최신으로 올라옴(정상 동작).
  - **추가 보강**: `insert_disqualification`에 `analyzed_for_date=as_of`를 채우도록 한다. 호출부(강등 경로)가 `as_of`를 넘기도록 시그니처 1개 인자 추가.

## 테스트 전략

신규 단위 테스트:
- (a) 같은 종목, `analyzed_for_date` 다른 2행 → 큰 쪽 선택
- (b) `analyzed_for_date` 동일, `classified_at` 다른 2행 → 타이브레이크로 나중 실행 선택
- (c) `analyzed_for_date` NULL 레거시 행 → `classified_at` 폴백
- (d) 지연-실행: 같은 실행의 두 행이 `classified_at`은 자정 넘겨 다르지만 `analyzed_for_date` 동일 → 한 묶음으로 인식
- (e) 강등 경로: `get_classified_losing_minervini`가 축 변경 후에도 라이브 데이터에서 동일 강등 결정

회귀:
- 6개 소비처 기존 테스트가 새 정렬에서 통과
- `uv run pytest tests/` baseline isolation fail(~25개) 수가 늘지 않는지 확인 (CLAUDE.md 기준)

## 비범위 (Out of scope)

- as-of 시계열 정합화(차트·CSV 빌더 `on_date`) → sub-project ②
- 백필/백테스트 별도 테이블 + 실행 경로 → sub-project ③
- web 표시 정렬에 `analyzed_for_date` 순 옵션 추가 → 선택적 후속(정확성 무관)
- thresholds.py 상수 변경 없음 → threshold-change-checklist 비해당

## 영향받는 파일 요약

- `api/routers/classifications.py` (내부 CTE)
- `kr_pipeline/llm_runner/load.py` (2개 함수)
- `api/services/zip_builder.py` (_fetch_latest_analysis_result)
- `kr_pipeline/llm_runner/compute/payload_lite.py` (2개 쿼리)
- `kr_pipeline/llm_runner/freeze_cleanup.py`
- `kr_pipeline/llm_runner/store.py` (insert_disqualification 보강) + 강등 호출부
- `kr_pipeline/llm_runner/compute/delta.py` (변경 없음, 주석만 추가)
- 테스트 파일 (신규 + 회귀)
