# 분석 회고 페이지 (`/review`) — 설계 스펙

작성 2026-08-22. 브레인스토밍 세션(2026-08-21~22)에서 합의된 설계.
목적 확정 근거와 실측치는 본문에 인라인 기록.

## 0. 목적과 배경

LLM 분석(패턴·pivot 산출)이 **사후적으로 쓸만했는지 회고**하는 화면.
"분석 → 평일 트리거 발동 → 이후 가격 진행"을 분석 1건 단위로 한눈에 본다.

설계를 규정한 실측 3가지 (2026-08-21, production DB):

1. 트리거 이력은 평일(거래일)에만 존재 — 저녁 체인 plist 월~금 발화,
   `trigger_evaluation_log` 138행 전수 요일 분포 월~금뿐.
2. 트리거의 pivot 유래: **daily_delta 분석 110건(80%) vs weekend 분석 28건(20%)**
   — "주말 분석만" 잇는 화면은 트리거 80%를 놓친다. → 회고 대상 = 전체 분석.
3. `go_now` = 0건 — 기존 성과 추적(`llm_signal_performance`) 재사용 불가.
   가격 진행은 `daily_prices`에서 직접 계산한다.

사용자 결정 4건: 목적=**회고** / 대상=**전체 분석(주말+delta), 미발동 포함** /
성과=**pivot 대비 T+5·T+20 + 스파크라인** / 접근=**A안(신규 페이지, 분석 중심)**.

## 1. 데이터 정의

### 회고 행 (analysis row)

- 원천: `weekly_classification` 에서 `source IN ('weekend','daily_delta')`
  AND `classification IN ('entry','watch')`.
- `source='system_disqualify'`(604행)는 LLM 분석이 아니므로 **회고 행에서 제외**.
  단, 아래 유효 구간의 **경계로는 포함**한다(실격이 모니터링을 종료시키므로).
- `ignore` 분류는 pivot이 없어 회고 대상이 아니다 — 제외.
- 유형 배지: `source` 컬럼 그대로 (weekend / daily_delta).

### 유효 구간 (validity window) — as-of 귀속의 핵심

분석 A(symbol S, 시점 t)의 유효 구간 = `[t, t')`,
t' = 같은 S의 **다음 classification 행**(source 무관 — weekend·delta·disqualify 모두)의
시점. 다음 행이 없으면 t' = 현재.

- 시점 비교 키는 `evaluate_pivot`의 active 선정 로직(`load.py get_active_monitoring`)과
  동일하게 `COALESCE(analyzed_for_date, classified_at::date), classified_at` 순서를 쓴다
  — 화면의 귀속이 실제 평가 당시의 active 분석과 일치해야 하기 때문.

### 트리거 귀속

`trigger_evaluation_log` 행을 `(evaluated_at AT TIME ZONE 'Asia/Seoul')` 이
유효 구간에 속하는 분석에 귀속한다. 재분류로 pivot이 바뀌어도 각 트리거는
"그때의 분석"에 붙는다. 검증 보조: 로그의 `pivot_price` 스냅샷과 귀속된 분석의
`pivot_price` 일치 여부를 테스트에서 대조한다(불일치 = 귀속 버그 신호).

### 성과 (pivot 기준)

- **발동 분석** (구간 내 `trigger_type='breakout'` 트리거 ≥1):
  첫 breakout 트리거일 D 기준
  `T+5 = adj_close(D+5거래일) / pivot − 1`, `T+20 = adj_close(D+20거래일) / pivot − 1`.
  해당 시점 미도래면 null + 상태 "진행 중 (T+n)".
- **미발동 분석**: T+5/T+20 대신 **최고 도달률** =
  `max(adj_close) / pivot − 1` (구간 시작 ~ min(구간 끝 + 20거래일, 오늘)).
  pivot에 얼마나 못 미쳤는지도 품질 신호다.
- 거래일 산정: `daily_prices`에 해당 종목 행이 있는 날 기준(휴일·대체공휴일 자동 배제).
- 가격은 **수정 종가(adj_close)**. 거래정지일(adj null)은 결측으로 건너뛴다.
- pivot null인 행(일부 watch): 성과 전부 "—".

### 스파크라인

분석일부터 min(오늘, 분석일+20거래일)의 adj_close 시리즈(최대 21점) + pivot 기준선.
API 응답에 숫자 배열로 인라인.

## 2. 백엔드

- **신규 라우터** `api/routers/review.py`: `GET /api/review/analyses`
  - 쿼리 파라미터: `from`, `to`(분석일 기준, 기본 최근 4주), `classification`,
    `source`, `triggered`(true/false), `pattern`, `ticker`, `limit`(≤500), `offset`
  - 구현: 유효 구간은 window function(`LEAD` over symbol) 1패스, 트리거 귀속·가격
    시리즈는 LATERAL 서브쿼리. **조회 시 계산** — 분석이 주당 수십 건 규모라
    사전 계산 테이블·컬럼 추가는 하지 않는다(YAGNI). 스키마 변경 없음.
  - 응답 행: symbol, name, market, source, classified_at, analyzed_for_date,
    classification, pattern, pivot_price, first_breakout_at, first_breakout_decision,
    trigger_count, t5_pct, t20_pct, max_reach_pct(미발동), status(완료/진행중/미발동),
    spark(배열), triggers(귀속 트리거 목록 — 날짜·type·decision·close·pivot 스냅샷·
    reasoning).
- 기존 테이블·파이프라인 코드 무변경 (읽기 전용 화면).

## 3. 프론트

- 신규 라우트 `/review` "분석 회고" (`web/src/pages/ReviewPage.tsx`), App.tsx 내비 추가.
- 필터 바: 기간(기본 4주)·분류·유형(weekend/daily_delta)·발동 여부·패턴·종목 —
  TriggersPage의 URL 파라미터 패턴 재사용.
- 테이블 컬럼: 종목 | 분석일+유형배지 | 분류·패턴 | pivot | 발동(첫 breakout 일자
  + decision pill) | T+5 | T+20 (미발동이면 최고 도달률로 대체 표기) | 스파크라인 | 상태.
- 행 확장: 귀속 트리거 타임라인 — TriggersPage 행 스타일(DecisionPill·reasoning 접기)
  재사용. 종목 클릭 → `/chart/<symbol>` (기존 관례).
- 스파크라인은 의존성 추가 없이 inline SVG로 그린다.

## 4. 엣지 케이스

- 같은 날 delta 분석 + 당일 저녁 트리거: 유효 구간 시작이 당일이므로 정상 귀속.
- 재분류 경계일: 트리거는 `evaluated_at < t'` 조건으로 옛 분석에 붙는다(경계 테스트 필수).
- T+5/T+20 미도래: null + "진행 중". 스파크라인은 있는 데까지.
- 거래정지 결측: 스파크라인 결측 gap, T+N 산정은 행이 있는 거래일만 센다.
- disqualify 만 있고 후속 분석 없는 종목: 구간이 disqualify 에서 끝남 — 미발동/발동
  성과는 구간 규칙 그대로.

## 5. 테스트 (kr_test 관례)

1. as-of 귀속: 재분류 경계에서 트리거가 옛 분석에 귀속되는지 + disqualify 가
   구간을 끊는지.
2. 귀속 검증 보조: 트리거 pivot 스냅샷 = 귀속 분석 pivot 일치.
3. T+N 거래일 산정: 주말·공휴일(예: 2026-08-17 대체공휴일) 건너뜀, 미도래 null.
4. 미발동 최고 도달률 계산.
5. API 계약: 필터 조합·limit 상한·빈 결과.
6. 기존 suite 무회귀 (실패 0 기준 유지).

## 6. 범위 제외 (합의)

- 주 단위 집계 대시보드(C안) — 이 API 위에 2차로 얹는다.
- go_now 성과 추적 연동 — 실적 0건, 발생 후 재론.
- 페이지 내 매매 액션·알림.
