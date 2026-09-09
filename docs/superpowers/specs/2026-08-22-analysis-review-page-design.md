> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# 분석 회고 페이지 (`/review`) — 설계 스펙

작성 2026-08-22 (v3 — 독립 검토 8건 반영 개정). 브레인스토밍 세션(2026-08-21~22) 합의.

## 0. 목적과 배경

LLM 분석(패턴·pivot 산출)이 **사후적으로 쓸만했는지 회고**하는 화면.
"분석 → 평일 트리거 → 이후 가격 진행"을 분석 1건 단위로 한눈에 본다.

설계를 규정한 실측 (2026-08-22 재실측, production DB):

1. 트리거 이력은 평일(거래일)에만 존재 — 저녁 체인 plist 월~금 발화,
   `trigger_evaluation_log` **142행** 전수 요일 분포 월~금뿐.
2. 트리거의 유래(`prior_classification_at` ground truth 기준):
   **daily_delta 85건 vs weekend 56건 (60:40)** + 귀속 불가 고아 1건(아래 §1).
   — "주말 분석만" 잇는 화면은 트리거 60%를 놓친다. → 회고 대상 = 전체 분석.
3. `go_now` = 0건(decision 분포: wait 125·abort 17) — 기존 성과 추적 재사용 불가.
   가격 진행은 `daily_prices`에서 직접 계산한다.
4. trigger_type 실분포: promotion 107 / invalidation 21 / breakout_from_watch 13 /
   breakout 1. **promotion 은 돌파가 아니라 staging** — 게이트가
   `close ≥ pivot×0.95 AND volume ≥ avg`(상한 없음)라 **pivot 을 이미 넘은 종목도
   promotion 만 반복될 수 있다**(fresh_cross·watch_reason 요건 미충족 시 — 거래량
   요건은 상수 분리돼 있으나 현행 `GATE_BREAKOUT_VOL_MULT=1.0` 으로 promotion 과 동일).
   go_now 는 promotion 에서 전면 금지(프롬프트 §3.3). 돌파 사건은
   `breakout`(entry 경로)·`breakout_from_watch`(watch 경로)가 담당.
5. 회고 행 pivot 보유율: entry 1행(전 기간), watch 533행 중 pivot null 367행(69%).
6. 거래정지일에도 `daily_prices` 행이 존재하며 **adj_close 는 직전가 carry 로 유지**
   된다(`nullify_halt_adj` — null 이 되는 것은 adj open/high/low·adj 거래량이며
   **raw volume 은 0 으로 유지**된다, halt 마커). halt 판정 관례 =
   `adj_low IS NULL`(`load.py` 동일 관례).

사용자 결정 5건: 목적=**회고** / 대상=**전체 분석(주말+delta), 미발동 포함** /
성과=**pivot 대비 T+5·T+20 + 스파크라인** / 접근=**A안(신규 페이지, 분석 중심)** /
발동=**breakout 계열만, promotion 은 별도 상태**.

## 1. 데이터 정의

### 회고 행 (analysis row)

- 원천: `weekly_classification` 에서 `source IN ('weekend','daily_delta')`
  AND `classification IN ('entry','watch')`.
- `source='system_disqualify'`(604행)는 LLM 분석이 아니므로 회고 행에서 제외.
  단, 성과 구간의 **끝 경계로는 포함**한다(실격이 모니터링을 종료시키므로).
- `ignore` 는 pivot 이 없어(739/740) 회고 대상이 아니다 — 제외.
- 유형 배지: `source` 그대로 (weekend / daily_delta).

### 트리거 귀속 — 직접 조인 (v3 개정: 시간창 재구성 폐기)

- **귀속 키 = `(t.symbol, t.prior_classification_at)` → `weekly_classification
  (symbol, classified_at)` 직접 조인.** 로그가 평가 당시의 active 분석을 NOT NULL
  로 기록하므로(evaluate_pivot.py:258,353) 이것이 ground truth 다.
- 시간창(as-of) 재구성은 쓰지 않는다 — 주말 배치가 새벽 실행되며 `analyzed_for_date`
  를 소급(backdate)하는 케이스에서 ground truth 와 불일치가 실증됐다(재구성 변형에
  따라 **최대 24/142, 17%**).
  같은 (symbol, 기준일) 복수 분석(36쌍)·0길이 구간 문제도 직접 조인으로 소멸.
- **고아 행 처리**: `prior_classification_at` 이 현 `weekly_classification` 에 없는
  트리거(재분석 대체 등 — 현재 1건, 033200/05-20)는 조용히 버리지 않고 응답
  메타(`orphan_trigger_count`)로 집계해 화면 하단에 노출한다.

### 성과 구간 (per analysis)

- 구간 시작 = 분석 기준일 `key_date = COALESCE(analyzed_for_date, classified_at::date)`.
- 구간 끝 t' = 같은 symbol 의 **다음 classification 행**의 key_date. "다음 행"의
  모집합은 `weekly_classification` 의 **모든 행**(classification·source 무관 —
  **ignore·disqualify 포함**), 순서는 `(key_date, classified_at)` 사전식. 없으면 오늘.
  ⚠️ 구현 주의: LEAD 는 회고 행 필터(entry/watch·source) **적용 전** 전체 행에
  걸어야 한다 — 필터 후에 걸면 ignore 재분류를 지나 구간이 연장된다
  (다음 행이 ignore 인 회고 행 36건, 그중 기본 필터 노출 23건 실측).
- 이 구간은 **성과·스파크라인 창 계산에만** 쓴다(귀속은 위 직접 조인).
- **연장 금지의 스코프**: "구간을 넘겨 연장하지 않는다"는 **미발동·staging 의
  max_reach 창에만** 적용된다 — 재분석(새 pivot) 이후 가격을 옛 pivot 대비로
  계상하면 인접 회고 행과 이중 계상되기 때문. 반면 **돌파 행의 D~D+20 창은
  돌파 사건 기준의 사후 추적이라 t' 를 넘어도 된다**(의도) — 기준이 스냅샷
  체인이라 이후 재분석과 무관하고, 돌파 성과는 사건당 1회만 계상된다.

### 발동 정의·상태 축

- **돌파 발동** = 귀속 트리거 중 `trigger_type IN ('breakout','breakout_from_watch')`
  최초 발생. (`'breakout'` 단독은 실데이터 1/142건뿐이라 기각.)
  **"최초"의 순서 기준 = D**(아래 성과 절의 `COALESCE` 날짜 규칙, 동률이면
  `evaluated_at`) — 익일 catch-up 실행분에서 evaluated_at 순서와 D 순서가 어긋날
  수 있기 때문. `promotion_at` 응답 필드도 같은 D 규칙의 날짜다.
- **staging** = promotion 만 발생(돌파 계열 없음). §0-4 실측대로 pivot 을 이미
  넘었어도 breakout 요건 미충족이면 staging 에 머문다 — 라벨을 "임박"이 아닌
  **"staging(미확정)"** 으로 쓰고, 최고 도달률이 0% 이상(pivot 상회)인 staging 행은
  화면에서 구분 표기한다.
- 상태 축 — 판정 표 (귀속 트리거 조합 기준):

  | 돌파 계열 ≥1 | promotion ≥1 | 상태 |
  |---|---|---|
  | 예 | 무관 | 돌파-진행중 / 돌파-완료 (T+20 도래 여부) |
  | 아니오 | 예 | staging (invalidation 공존해도 staging) |
  | 아니오 | 아니오 | 미발동 (invalidation-only 포함 — trigger_count 로 구분 가능) |

  invalidation 은 상태에 영향 없이 타임라인에만 표시(하향 사건).
  breakout_from_watch 는 promotion 선행 없이도 발생한다(13건 중 9건).

### 성과 (pivot 기준)

- **돌파 트리거의 기준일 D** = `COALESCE(t.analyzed_for_date,
  (t.evaluated_at AT TIME ZONE 'UTC')::date)` — 파이프라인 관례(evaluate_pivot.py:47,127)
  와 동일. `evaluated_at` 날짜를 쓰면 익일 catch-up 실행분(breakout 계열 3/14건 실존)
  에서 스냅샷과 종가가 다른 날이 되어 아래 체인 항등식이 깨진다.
- **돌파 발동 분석**: **재정규화 면역 체인식** —
  `T+N = (1 + pivot_delta(D)) × adj_close(D + N거래일) / adj_close(D) − 1`,
  `pivot_delta(D)` = 트리거 로그의 같은 시점 스냅샷 `(close − pivot) / pivot`.
  pivot 은 분석 시점 수정주가 기준으로 고정 저장되는데 이후 기업행위 발생 시 수정
  종가 전 이력이 재계산되어 기준이 어긋난다 — 스냅샷 비율과 adj 수익률은 각자
  내부 기준이 일관되므로 체인은 재정규화와 무관하다. T+N 미도래면 null +
  상태 "돌파-진행중 (T+n)".
- **미발동·staging 분석**: T+5/T+20 대신 **최고 도달률** =
  `max(adj_close) / pivot − 1`, 창 = **key_date 다음 거래일부터 t' 전까지**
  (`(key_date, t')`, 연장 없음). key_date 당일을 제외하는 이유: 그날 종가는 분석의
  **입력**이라, 포함하면 "사후 도달"이 아닌 "사전 상태"가 지표를 채운다
  (주말 분석은 key_date 가 토요일이라 자동 제외, delta 분석에서 실효).
  이 값은 스냅샷 체인이 불가하므로(트리거 없음) 창 내 기업행위 발생 시
  **왜곡 가능 배지**(`corp_action_flag`)를 표시한다. 배지 판정 =
  `corporate_actions.event_date ∈ [key_date, 오늘]`, 분석 행 단위 boolean —
  상한이 성과 창 끝이 아니라 **오늘**인 이유: 기업행위는 그 시점 *이전 전체*
  adj 이력을 rescale 하므로, 창 종료 후의 이벤트도 창 내 가격을 소급 왜곡한다.
  (실효 규모: 기본 필터(pivot 있음) 기준 현재 노출 5건 — 창 내 이벤트 1 +
  창 후 이벤트 4.)
- 거래일 산정: `daily_prices` 에 해당 종목 행이 있는 날 = 1거래일
  (휴일·대체공휴일은 행이 없어 자동 배제). **거래정지일도 행이 있으므로 거래일로
  세며, adj_close 는 carry 값을 그대로 쓴다**(§0-6 — "결측 skip" 규칙은 없다).
- pivot null 행: 성과 전부 "—". watch 의 69%(367행)가 해당 — **기본 필터를
  "pivot 있는 분석"으로** 두고 pivot null 행은 필터 해제 시에만 표시한다
  (대안 지표는 만들지 않음 — 필요해지면 2차).

### 스파크라인 — 성과 창과 동일 앵커 (v3 개정)

- **돌파 행**: 앵커 = 돌파일 D, 범위 = D ~ min(D+20거래일, 오늘) — T+20 시점이
  항상 차트 안에 있다.
- **미발동·staging 행**: 범위 = max_reach 창과 동일한 `(key_date, t')`
  (최고 도달 지점이 항상 차트 안). 구간이 20거래일보다 길면 그대로 다 그린다(점 수 상한 60 — 초과 시
  균등 다운샘플하되 **최고점(max_reach 발생일)과 최저점은 반드시 보존**한다 —
  표기된 max_reach_pct 와 차트 최고점이 어긋나지 않도록).
- pivot 기준선: **돌파 행은 체인 기저로 환산해 그린다** —
  `기준선 = adj_close(D) / (1 + pivot_delta(D))` (T+N 체인식과 동일 기저라
  재정규화 후에도 차트와 수치가 어긋나지 않는다). 미발동·staging 행은 저장된
  pivot 그대로(스냅샷 없음 — corp_action_flag 배지가 왜곡 가능성을 담당).
  API 응답에 숫자 배열 인라인.

## 2. 백엔드

- **신규 라우터** `api/routers/review.py`: `GET /api/review/analyses`
  - 쿼리 파라미터: `from`, `to`(분석 key_date 기준, 기본 최근 4주), `classification`,
    `source`, `triggered`(돌파 발동 여부), `pattern`, `ticker`,
    `include_pivot_null`(기본 false), `limit`(≤500), `offset`
  - 구현: 성과 구간 끝 t' 는 window function(`LEAD` over symbol,
    `(key_date, classified_at)` 정렬) 1패스. 트리거는 `prior_classification_at`
    직접 조인, 가격 시리즈는 LATERAL 서브쿼리. **조회 시 계산** — 분석이 주당
    수십 건 규모라 사전 계산 테이블·스키마 변경 없음(YAGNI).
  - 응답 행: symbol, name, market, source, classified_at, analyzed_for_date,
    classification, pattern, pivot_price, first_breakout_at(D), first_breakout_type,
    first_breakout_decision, promotion_at(최초 promotion), trigger_count,
    t5_pct, t20_pct, max_reach_pct, corp_action_flag,
    status(미발동/staging/돌파-진행중/돌파-완료), spark(배열),
    triggers(귀속 트리거 목록 — 날짜·type·decision·close·pivot 스냅샷·reasoning).
  - 응답 메타: `orphan_trigger_count` — 귀속 분석이 없어 `from`/`to`(분석 key_date)
  필터를 적용할 수 없으므로, **트리거 자신의 날짜**
  (`COALESCE(t.analyzed_for_date, evaluated_at UTC date)` — §1 의 D 와 동일 규칙)를
  기간 필터 기준으로 계수한다.
- 기존 테이블·파이프라인 코드 무변경 (읽기 전용 화면).

## 3. 프론트

- 신규 라우트 `/review` "분석 회고" (`web/src/pages/ReviewPage.tsx`), App.tsx 내비 추가.
- 필터 바: 기간(기본 4주)·분류·유형(weekend/daily_delta)·발동 여부·패턴·종목·
  pivot null 포함 토글 — TriggersPage 의 URL 파라미터 패턴 재사용.
- 테이블 컬럼: 종목 | 분석일+유형배지 | 분류·패턴 | pivot | 상태(미발동/staging/돌파
  + 첫 돌파일·decision pill, staging 인데 pivot 상회면 구분 표기) | T+5 | T+20
  (미발동·staging 이면 최고 도달률로 대체 표기 + 기업행위 배지) | 스파크라인.
- 행 확장: 귀속 트리거 타임라인 — TriggersPage 행 스타일(DecisionPill·reasoning 접기)
  재사용. 종목 클릭 → `/chart/<symbol>` (기존 관례).
- 스파크라인은 의존성 추가 없이 inline SVG. 화면 하단에 orphan_trigger_count > 0 시
  안내 문구.

## 4. 엣지 케이스

- 같은 날 delta 분석 + 당일 저녁 트리거: `prior_classification_at` 직접 조인이라
  자연 귀속.
- 주말 배치 새벽 실행·analyzed_for_date 소급: 귀속은 직접 조인이라 영향 없음.
  성과 구간 끝 계산에만 (key_date, classified_at) 사전식 정렬 사용.
- 같은 (symbol, key_date) 분석 2건(36쌍 실존): 귀속은 직접 조인으로 명확.
  구간은 사전식 정렬로 0길이 가능 — 그 행의 미발동 창은 비어 성과 "—".
- T+5/T+20 미도래: null + "돌파-진행중". 스파크라인은 있는 데까지.
- 거래정지: 행 존재·adj_close carry — 거래일로 세고 값 그대로 사용(§1).
- disqualify 만 있고 후속 분석 없는 종목: 구간이 disqualify 의 key_date 에서 끝남.
- 고아 트리거: 화면 유실 없이 메타 카운트로 노출.

## 5. 테스트 (kr_test 관례)

1. 귀속 직접 조인: backdate 된 주말 분석이 있어도 트리거가 평가 당시 분석에
   귀속되는지(시간창 방식이면 틀렸을 시나리오 고정 픽스처).
2. 고아 트리거: prior_classification_at 부재 시 orphan_trigger_count 집계, 행 유실 0.
3. D = COALESCE 규칙: 익일 catch-up 트리거(analyzed_for_date ≠ evaluated_at 날짜)에서
   체인 항등식 성립.
4. 체인식 성과: 재정규화 시나리오(기업행위로 adj 이력 전체 rescale)에서 T+N 불변.
5. T+N 거래일 산정: 주말·공휴일 건너뜀 + **거래정지일 포함**(행 존재·carry 값), 미도래 null.
6. 상태 축: promotion 만 → staging(pivot 상회 케이스 구분 플래그 포함),
   breakout_from_watch(promotion 선행 없이) → 돌파, promotion 후 돌파 → 기준일 = 돌파일.
7. 미발동 최고 도달률: 창 = (key_date, t') 한정(연장·day0 포함 없음), 0길이 → "—",
   corp_action_flag 판정([key_date, 오늘] 상한 — 창 후 이벤트 케이스 포함).
8. **t' 모집합**: 다음 행이 ignore 인 경우 구간이 거기서 끝나는지
   (LEAD 를 필터 후에 걸면 틀리는 픽스처).
9. 고아 트리거 기간 필터: from/to 가 트리거 자신의 D 규칙 날짜로 적용되는지.
10. 스파크라인 다운샘플: 60점 초과 시 최고·최저점 보존.
11. API 계약: 필터 조합(triggered·include_pivot_null)·limit 상한·빈 결과.
12. 기존 suite 무회귀 (실패 0 기준 유지).

## 6. 범위 제외 (합의)

- 주 단위 집계 대시보드(C안) — 이 API 위에 2차로 얹는다.
- go_now 성과 추적 연동 — 실적 0건, 발생 후 재론.
- 페이지 내 매매 액션·알림. halt 일 시각 마커·pivot null 행 대안 지표(2차 후보).
