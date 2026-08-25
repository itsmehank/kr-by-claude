# /review 종목 행 회고 뷰 (streak view) — 설계 스펙

작성 2026-08-25. 브레인스토밍 합의 + 설계 검토 4건 반영본.
선행 스펙: `2026-08-22-analysis-review-page-design.md`(분석 1건=1행 뷰, PR #128) — 본 스펙은
그 위에 **종목 행 뷰를 기본 뷰로 추가**하며 기존 뷰는 토글로 유지한다.

## 0. 목적과 결정 이력

목적: 분석 회고 페이지에 들어갔을 때 **종목별 1행**으로 "이 종목의 분석이 과거에 어떻게
진행됐고 성과가 어땠는지"를 **그래프로** 바로 읽는다. 기존 기본 뷰(분석 1건=1행)는
통계적 회고용으로 남긴다.

사용자 결정(2026-08-25, 순서대로):
1. **묶음(streak) 종결** = ignore 행(모든 source) 또는 system_disqualify 행. 기록 공백은
   이어짐(닫지 않음). 근거 실측: 유효 분석 뒤에 오는 비유효 사건 = 실격 212 / ignore 8;
   10일↑ 공백 23건 중 21건은 6~7월 배치 미실행 결손(#132 백필 대상), 종목 자체 공백 2건.
2. **행 = 종목 1개**, 행 안에 묶음이 여러 개일 수 있음(63/209 종목이 묶음 2개↑) — 굵은
   색띠 구간으로 구분, 트리거는 띠 위의 점.
3. **기간 의미**: 행 = 기간 [from, to] 안에 유효 분석 1건↑인 종목. from에 걸친 묶음은
   **시작까지 소급** 표시, to 이후는 절단(진행중 묶음은 "진행중").
4. **성과는 pivot 기준만**. 묶음 시작 종가 대비 수익률은 만들지 않음(좌측 절단 왜곡).
   그래프에 묶음 시작 전 ~6개월 맥락 포함 + 좌측 절단 배지.
5. **뷰 관계**: 종목 행 뷰 기본, 분석 행 표는 토글(`view=analysis`), #127 타임라인은
   종목 행 펼침 상세로 흡수(`view=timeline` 토글 제거).
6. 접근 = **1안(백엔드가 묶음·성과·시계열까지 계산)**, 새 모듈 `review_streaks.py`.

설계 검토 반영(4건): 백필 병합 하한 / 좌측 절단 상수화 / status 필터 Python 적용·limit 500 /
구 URL 호환.

## 1. 데이터 규칙

### 원천과 병합
- 원천 = `weekly_classification` ∪ `classification_backfill`.
- **병합 하한**: `classification_backfill`은 `analyzed_for_date >= REVIEW_COVERAGE_START`
  행만 포함한다. 그 이전 행(2024-01~2026-05 산발 백테스트 표본 321행)은 회고 뷰 대상이
  아니다 — 합치면 종목마다 조각 묶음이 생기고 절단 판정이 틀어진다(검토 문제 1).
- `REVIEW_COVERAGE_START = date(2026, 6, 1)` — `api/services/review_streaks.py` 상단
  명시 상수. 라이브 주말 분류가 연속으로 존재하기 시작한 날. 6/1 이전을 백필하게 되면
  이 상수만 옮긴다.
- 중복: 같은 (symbol, key_date)에 라이브·백필 둘 다 있으면 **라이브 우선**
  (`/classifications` 라우터의 `DISTINCT ON + source_rank` 관례). 현재 중복 0건.
- 백필 행은 `backfilled=true` 표식(화면·응답 모두).

### 유효 행·닫는 행
- key_date = `COALESCE(analyzed_for_date, classified_at::date)`. 정렬 = `(key_date, classified_at)`.
- **유효 행** = `classification ∈ {entry, watch}` AND source ∈ {weekend, daily_delta, backfill}.
- **닫는 행** = `classification = 'ignore'`(source 무관 — 백필의 ignore 행도 포함) OR
  `source = 'system_disqualify'`. 모든 행은 유효/닫는 행 둘 중 하나로 귀속된다.

### 묶음(streak) 분할
- 종목별 정렬 순서에서 유효 행이 연속되는 최대 구간. 닫는 행이 나오면 묶음 종료:
  `end = 닫는 행 key_date`, `closed_by = 'ignore' | 'disqualify'`. 다음 유효 행부터 새 묶음.
- 기록 공백(행 없음)은 이어짐 — 공백 구간은 그래프에서 띠를 점선으로 그린다(정보 결손
  정직 표기). 공백 판정 = 연속 유효 행 사이 key_date 간격 > 10일.
- 마지막 유효 행 뒤에 닫는 행이 없으면 `end = null`, 상태 "진행중".

### 행 선정·표시 범위
- 행 = 기간 [from, to] 안에 key_date가 있는 유효 행이 1건↑인 종목.
- 표시 묶음 = [from, to]와 교차하는 묶음 전부. from 이전 시작은 시작까지 소급, to 이후는
  절단(표시상 end를 to로 클램프하되 `closed_by`는 실제 값 유지).
- **좌측 절단 배지**: 묶음 시작 key_date ≤ `REVIEW_COVERAGE_START + 7일`이면
  `censored=true`("관찰 시작=시스템 시작"). 그 묶음의 이력은 종목의 이야기 시작이 아니다.

### 트리거 귀속
- 기존 규칙 그대로: `trigger_evaluation_log.prior_classification_at` = 분석 `classified_at`
  직접 조인. 백필 분석에는 트리거가 없다(정상 — 그 기간 평일 평가 미실행).

## 2. 성과 (pivot 기준만)

묶음별 `metrics`:
- 묶음 내 돌파 트리거(`breakout`·`breakout_from_watch`) 있음 → **첫 돌파**의 T+5/T+20
  (기존 `chain_tn` 체인식, D 규칙·스냅샷 pivot_delta 그대로).
- 없고 pivot 있는 분석 있음 → **묶음 내 마지막 pivot** 대비 최고 도달률(기존 `max_reach`),
  창 = (그 분석 key_date, 묶음 end 또는 오늘).
- pivot이 끝내 없음(전부 base_forming/extended 등) → `stage = "베이스 형성 중"`, 숫자 없음.
  근거 실측: pivot 없는 watch 373건 중 292건(78%)이 base_forming — 규약상 pivot 미확정
  단계이며 LLM 누락이 아니다.
- **묶음 시작 종가 대비 수익률은 계산·표시하지 않는다**(결정 4).
- 종목 행 요약(`latest`) = 가장 최근 묶음의 상태·성과. 펼치면 묶음 전부.

## 3. 그래프

- 시간창 = `max(가용 데이터 시작일, 표시 묶음 중 가장 이른 시작일 − 120거래일)` ~ `to`.
  가용 데이터 시작일 = 해당 종목 `daily_prices` 최초일(현재 커버리지 2025-11-03) — 클램프.
- 층: ① 수정 종가 선 ② **pivot 계단선**(각 분석 key_date부터 다음 분석 전까지 그 분석의
  pivot; pivot 없는 구간은 비움) ③ **묶음 색띠**(가격선 아래; 닫힌 지점 마커 ✕=실격
  ○=ignore; 공백·백필 구간은 점선/연한 띠) ④ **트리거 점**(promotion 노랑·돌파 초록·
  invalidation 회색 — DecisionPill 색 관례) ⑤ 좌측 절단 배지(띠 시작에 ⟵ 표식).
- 축: 월 눈금 최소 표기. 툴팁·확대 없음(YAGNI — 상세는 펼침).
- 폭: 행 폭의 ~60%, inline SVG(의존성 추가 금지).

## 4. 백엔드

- 신규 `api/services/review_streaks.py`(기존 `review_builder.py` 무수정 — `chain_tn`·
  `max_reach`·`first_breakout`·`fetch_price_series`만 import):
  1. 원천 UNION 조회(병합 하한·라이브 우선 dedup) — 기간 [from, to]에 유효 행 있는
     종목의 **전 이력**(소급 표시를 위해 기간 밖 행도 포함).
  2. 종목별 묶음 분할 → 기간 교차 필터 → 절단 판정.
  3. 트리거 직접 조인, 묶음별 metrics.
  4. 시계열·pivot 계단 데이터 조립(시간창 규칙).
- 라우터 `api/routers/review.py`에 `GET /api/review/stocks` 추가. 파라미터:
  `from`·`to`(기본 최근 4주)·`source`(weekend|daily_delta|backfill)·`ticker`·
  `status`(open|closed)·`limit`(기본 200, **≤500**)·`offset` — 전부 `Query(ge=0)`.
  **status 필터·정렬·슬라이스는 기간 내 종목 전부를 계산한 뒤 Python에서** 적용
  (DB LIMIT 뒤 필터 금지 — 검토 문제 3, #130 동종). 정렬 = 최근 묶음 시작일 내림차순.
- 응답:
  ```
  { rows: [ { symbol, name, market,
              latest: { status: "open"|"closed", closed_by, stage, t5_pct, t20_pct, max_reach_pct,
                        first_breakout_at, censored, backfilled, streak_count },
              streaks: [ { start, end, closed_by, censored, backfilled, has_gap,
                           analyses: [ …ReviewRow 축약(key_date, source, classification,
                                        pattern, pivot_price, backfilled) ],
                           triggers: [ …ReviewTrigger ], metrics: {…} } ],
              series: [[date, adj_close], …], pivot_steps: [[from_date, to_date|null, pivot], …] } ],
    orphan_trigger_count }
  ```
- 조회 시 계산, 스키마 변경 없음, 읽기 전용.

## 5. 프론트

- `ReviewPage.tsx`: 기본 뷰 = 종목 행. 토글 "분석 단위 보기" → URL `view=analysis`로 기존
  표. 기존 `view=timeline` 토글 제거 — **구 URL(`view=timeline`)은 기본 뷰로 떨어지고
  에러 없음**(검토 경미 건). `StockTimeline`(#127)은 종목 행 펼침 안에서 묶음별로 재사용.
- 신규 `components/StockStreakRow.tsx`(행 + 펼침) · `components/StreakChart.tsx`(SVG) ·
  `lib/streakChart.ts`(계단·띠·점 좌표 계산 순수 함수).
- 컬럼: 종목 | 최근 묶음 상태(진행중/닫힘·사유, 절단·백필 배지) | 묶음 수 | 최근 pivot |
  성과(첫 돌파 T+5/T+20 · 최고 도달률 · "베이스 형성 중") | 그래프.
- 필터 바: 기간·유형·종목·상태(진행중/닫힘) — 기존 useSearchParams 관례.

## 6. 엣지 케이스
- 같은 key_date에 유효 행 2건(36쌍 실존) → 정렬 tie는 classified_at, 묶음 분할에 영향 없음.
- 묶음 시작이 가용 가격 데이터 이전 → 시간창 클램프, 배지 없음(절단 배지는 커버리지 기준).
- 기간 안에 닫는 행만 있고 유효 행 없는 종목 → 행 아님.
- ignore 직후 같은 날 delta 유효 행 → 닫힘 후 새 묶음(정렬 tie는 classified_at).
- 고아 트리거 → 기존 `orphan_trigger_count` 메타 유지.

## 7. 테스트
1. 묶음 분할: ignore 닫힘 / 실격 닫힘 / 공백(>10일) 이어짐+has_gap / 복수 묶음 / 닫힘 직후
   재진입.
2. 병합: 백필 하한(2026-06-01 이전 행 제외) / 라이브 우선 dedup / backfilled 표식.
3. 기간: from 소급 표시 / to 절단 / 기간 밖 묶음 미표시 / 닫는 행만 있는 종목 제외.
4. 절단 배지: 시작 ≤ COVERAGE_START+7 → true, 이후 → false.
5. 성과 선택: 돌파 있음 → 첫 돌파 T+N / 없음+pivot → 마지막 pivot max_reach / pivot 없음 →
   베이스 형성 중.
6. 시간창: −120거래일 역산, 가용 데이터 시작 클램프.
7. API 계약: status 필터가 슬라이스 전에 적용 / limit 500 캡 / ge=0 / 빈 결과.
8. vitest: `streakChart.ts` 계단·띠·점 좌표(공백 점선·절단 표식 포함).
9. 기존 suite 무회귀(실패 0).

## 8. 범위 제외
- 묶음 시작 종가 수익률, 그래프 툴팁·확대, 트리거 백필, #132 백필 실행 자체(데이터가
  오면 자동 병합), 종목 행 뷰의 집계 대시보드.
