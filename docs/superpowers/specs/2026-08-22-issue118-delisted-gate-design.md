# #118 사이클 1 — 상폐 게이트 지표 산출 + #115 리콜 붕괴 설계 (v1)

> 6차(#115) ②-(a) 이행: 상폐 c1~c7 산출은 리콜 구간 붕괴와 #118 재분석
> 묶음(marginal 측정 등)의 공통 병목. 전부 탐색 등급·LLM 0·로컬 DB 전용.

## 1. 산출 정의 — 현행 함수 재사용(복제 금지)

- 대상: 상폐 435종목 (`delisted_adj_prices` v5-d). carve 5종목은 c8 부재
  (bt_rs 제외됨)로 게이트 미판정 — 명시 보고.
- **adj_high/low 유도**: 일자별 계수 = `adj_close/raw_close` 를 raw high/low
  에 적용(production 수정 고저가와 동형 — 동일 계수 원칙). halt(0값) 행 제외.
- c1~c7: `compute_minervini_c1_to_c7` — sma(50/150/200), `w52_high_low`
  (252, min_periods=240) 전부 현행 함수 그대로.
- rs_line_not_declining_7m: `aggregate_to_weekly` → `compute_rs_line`(KOSPI
  1001 비수정 주봉 종가 분모) → `compute_rs_line_not_declining`(30주) →
  daily backward 미러(Phase D 동형).
  **한계 명기**: index_daily 1001 은 2016-06-13~ — 그 이전 상폐 구간 RS line
  = NaN → 게이트 미충족 취급(production 동형). 2017 초 anchor 일부 영향.
- c8: `bt_rs_daily.rs_rating ≥ 70` (기산출).
- 무편향 게이트 = c1~c7 AND rs_line_not_declining_7m AND c8.

## 2. 격리 산출 표면

```sql
CREATE TABLE bt_delisted_indicators (
  ticker VARCHAR(10) NOT NULL, date DATE NOT NULL,
  c1 BOOLEAN, c2 BOOLEAN, c3 BOOLEAN, c4 BOOLEAN, c5 BOOLEAN,
  c6 BOOLEAN, c7 BOOLEAN, rs_gate BOOLEAN, c8 BOOLEAN,
  gate_pass BOOLEAN, PRIMARY KEY (ticker, date)
);
```
백테스트 전용 — 라이브 무접촉. `delisted_adj_prices` 소비 한정 해제 3호
필요(승인 소비자 목록에 본 산출 러너 추가 — 7차 확인 항목).

## 3. #115 리콜 구간 붕괴 (6차 ③ 조항 이행)

- 상폐 승자 에피소드 511건을 §1 게이트·5차 봉인 윈도우((anchor−28, anchor)
  개구간)로 판정 → 리콜 점 추정.
- **스냅샷 1회 + 일자 각인**(연속 갱신 없음), 말단 18~24개월(2025~26 상폐
  승자 7·1건) **절단 주석 상시 부착**.
- carve 5종목·RS NaN 구간 에피소드는 잔여 미판정으로 잔존 구간 표기(0 이
  아니면 헤드라인 라벨 유지).

## 4. 리드타임 분포 (6차 ②-(b) 승인 descriptive)

- 에피소드별 첫 게이트 통과일 탐색 구간 = [anchor−28일, anchor+91일(13주)].
- lead = (첫 통과일 − anchor)일 (음수 = 개시 전 포착). 미포착 = 구간 내 통과 0.
- 중간 포착의 **잔여 시장초과** = 첫 통과일→(anchor+13주 시점) 종목수익 −
  동일구간 시장수익 [descriptive — 판정 불입력].

## 5. 7차 결정 요청 (측정 전 봉인 대상 — 승인 전 산출 금지)

1. **미포착 분해 정의**: 의도된 포기(Stage 1) = 윈도우 내 구조 조건(c1~c5)
   실패 ≥ 2개 / **경계 탈락** = 실패가 단일 조건이거나 c8 단독 실패이며
   rs_rating ≥ 60 [design-judgment 초안 — 자구 확정 요청].
2. **중간 포착 유효율 지표 승격**(사용자 제기): 에피소드 진행 중 첫 통과
   시점의 잔여 시장초과 ≥ +20%p(값 합의) 비율 — descriptive 에서 판정 입력
   으로 승격할지, 승격 시 지위 문구.
3. 소비 한정 해제 3호(§2) 확인.

## 6. 게이트

- [ ] §1~4 산출·보고 (승인 불요 — 6차 기승인 범위)
- [ ] §5 7차 승인 → 미포착 분해·유효율 산출
- [ ] 이후: #118 체크리스트 재분석(#111·#117 재실행, marginal 4변수 —
      2017~24 고정, mc 튜닝 금지 조항 유지)
