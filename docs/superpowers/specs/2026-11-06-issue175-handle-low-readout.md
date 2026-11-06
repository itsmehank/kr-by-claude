# #175 저장본 재현 readout — 구(2026-11-06 이전) vs 신 검출기 (2026-11-06)

> 읽기 전용(운영 DB SELECT 만, KRX 0·DART 0·LLM 0). 스크립트 `scripts/issue175_handle_low_readout.py`, 결과 JSON
> `data/verification/issue175_handle_low_readout_20261106.json`. 설계 = `specs/2026-11-06-issue175-handle-low-design.md` §6-2.
> 숫자는 관측이며 판정이 아니다(governance 3-5). 구 규칙 = `compute/handle_low_readout.legacy_detect`(독립 재구현: UTC 창 끝·1단 매칭·
> 0.80 컵 평균·분배일 ≥1), 신 규칙 = `compute/handle_quality.compute_handle_quality(as_of=COALESCE(analyzed_for_date, KST−1))`.
> 구 규칙의 창 끝은 저장 당시 store 경로 그대로(실전 = classified_at UTC 날짜 미포함, 백필/백테스트 = analyzed_for_date+1 미포함).

## (a) 머지 게이트 — 구·신 둘 다 식별한 저장 발화 행의 `handle_start`·`handle_high` 일치

| 표 | 저장 발화 행(2E metrics) | 구·신 둘 다 식별 | start·high 일치 | 불일치 | 구 미식별(legacy_none) | 신 미식별 가드 | 신 미식별 기타 |
|---|---|---|---|---|---|---|---|
| weekly_classification | 65 | 59 | **59/59** | 0 | 6 | 0 | **0** |
| backtest_classification | 585 | 496 | **496/496** | 0 | 73 | 16 | **0** |

**게이트 통과**(exit 0). 설계 §11 Q3 의 "58/58" 은 11-05 시점 발화 행 수였고 이후 행이 늘어 65 가 됐다(새 분류 저장분).

- legacy_none(구 규칙이 오늘 데이터·현 상수로 식별 못 함) 79 = `S5 handle<5` 75(#177 이전, 하한 3일 시절 저장) + `S4 rim not recovered` 4
  (adj 재적재 후 고가 변동). 이번 변경과 무관. 그중 weekly 4행은 신 규칙이 같은 `handle_start` 로 식별(2단 매칭 ①·②).
- 신 미식별 가드 16 = 전부 `handle_above_pivot`, 종목 005490·006490·006740·007110·031860·032080·090150·105550·189300·206640·207760·
  214370 — Phase A A2 "pivot 스케일 불일치(기업행위 후 adj 재스케일 vs 저장 pivot)" 집합과 일치(설계 §7 가드 의도대로 NULL 처리 대상).
- 저장 metrics 와의 차이(stored_drift, 게이트 비입력) 1 = 247540(2020-07-23 → 07-31): 구 규칙 재구현도 오늘 데이터에서 07-31 → 데이터 빈티지 차이.

## (b) `handle_end` 변화 행(저장 vs 신)

| 표 | 변화 행 | 09:00 KST 이전 실행 | 09:00 이후(저녁 daily_delta) |
|---|---|---|---|
| weekly_classification | 38 | 4 (053160·092230 07-28 02시, 049430 08-29 03시, 041520 10-17 05시 — 명세 §7-7 예측과 일치) | 34 |
| backtest_classification | 0 | — | — |

설계 §6-2(b) 의 "기대 4행" 은 과소 추정이었다. 구 UTC 규칙은 **저녁 실행(18~21시 KST)에서도 당일 봉을 제외**했다(UTC 날짜 = KST 날짜,
`date < 당일`). 신 규칙 `as_of(=analyzed_for_date) 포함` 은 그 봉을 넣는다 — 설계 S5′ 정의 그대로이며 백필 경로(`gate_at = D+1` 미포함 = D 포함)와
이제 같은 봉 집합이다(백테스트 변화 0 이 그 증거).

## (c) 발화 집합 변화

| 표 | fired→fired | fired→not | not→fired | legacy_none→fired | legacy_none→not | fired→none(가드) |
|---|---|---|---|---|---|---|
| weekly | 65 | 3 | 1 | 82 | 15 | 0 |
| backtest | 468 | 21 | 0 | 260 | 79 | 33 |

사유별(신): weekly `distribution_in_handle` 138 · `volume_not_contracting` 63 / backtest 677 · 492. (구: weekly 62·49, backtest 479·442.)
**관측(B-수치, 판정 아님)**: 식별 행 중 발화 비율 weekly 148/181 = 82%, backtest 749/853 = 88% — 구 규칙(81%·91%)과 비슷하게 높다.
(D′) 가 분배일을 "하단 마감" 으로 좁혔는데도 중앙 18일 손잡이에는 하단 마감 분배일이 거의 항상 1일 이상 있다. 수치(마감 위치 0.5)는 design 이라
변경은 별도 판정(2-2) — 다음 4주 실전 발생률과 함께 재검토 항목.

## (d) 커버리지

| 표 | 구 식별 | 신 식별 | 신 `pivot_eff_source` exact / minus_0_1 | 주요 미식별 사유(신) |
|---|---|---|---|---|
| weekly | 84/368 (22.8%) | **181/368 (49.2%)** | 87 / 94 | pivot_basis None 119·cup_high 15·range_high 5, 림 미회복 23, 손잡이 <5일 23, 베이스 <5일 2 |
| backtest | 548/2,350 (23.3%) | **853/2,350 (36.3%)** | 514 / 339 | pivot_basis None 1,037·range_high 67, 림 미회복 158, 손잡이 <5일 184, handle_above_pivot 34, 기타 17 |

림 미회복 124 → 23(weekly): 설계 §6-2(d) 기대(≥180/367) 충족. 잔여 미식별의 대부분은 `pivot_basis ≠ handle_high`(LLM 출력, 검출기 전제 — Phase A 판정대로 재설계로도 미해결).

## (e) `handle_low` 깊이(pivot_eff 대비 %) — 관측

| 표 | n | 최소 | Q1 | 중앙 | Q3 | P90 | 최대 | 8~12% 밴드 |
|---|---|---|---|---|---|---|---|---|
| weekly | 181 | 1.3 | 8.0 | 11.9 | 14.8 | 18.8 | 32.9 | 48 (26.5%) |
| backtest | 853 | 0.3 | 6.0 | 10.1 | 14.3 | 17.8 | 28.4 | 216 (25.3%) |

책 밴드(HMMS 8~12%)와의 대조는 관측이다(프롬프트 Gate3 가 판정). `handle_above_pivot` 34(backtest) 는 저장되지 않는다.

## (f) LLM 보고 깊이(`measurements.handle_depth_pct`)와 |차|

| 표 | n | 중앙 | Q3 | >3pp | 비율 |
|---|---|---|---|---|---|
| weekly | 165 | 0.05pp | 1.94pp | 29 | 17.6% (11-05 명세: 36%) |
| backtest | 781 | 1.17pp | 4.12pp | 257 | 32.9% |

## §7 과거 행 소급 `--plan` (2026-11-06, 읽기 전용 — `scripts/issue175_handle_low_backfill.py --plan --table all`)

운영 DB 에는 `handle_low` 열이 아직 없어(schema 적용은 머지·승인 후) 전 cwh 행을 후보로 집계했다. `--apply` 는 열 적용 후 테이블 하나씩,
사용자 승인 후에만.

| 테이블 | 후보(cwh) | 채워질 행 | 주요 미평가 사유 |
|---|---|---|---|
| weekly_classification | 372 | **182** | pivot_basis None 122·cup_high 15·range_high 5, 림 미회복 23, 손잡이 <5일 23, 베이스 <5일 2 |
| classification_backfill | 48 | **10** | pivot_basis None 29·range_high 5, 림 미회복 4 |
| backtest_classification | 2,351 | **853** | pivot_basis None 1,038·range_high 67, 림 미회복 158, 손잡이 <5일 184, handle_above_pivot 34, 기타 17 |
| recall_audit_classification | 323 | **104** | pivot_basis None 152·range_high 4, 손잡이 <5일 43, 림 미회복 14, handle_above_pivot 5, 기타 1 |

`handle_above_pivot` 39행(백테스트 34·리콜 감사 5)은 adj 재스케일 vs 저장 pivot 불일치 — 설계 §7 대로 NULL 유지.

## 독립 리뷰(2026-11-06) 반영·권고

- 구 규칙 재현의 실전 행 창 끝을 **UTC 날짜**로 고정(`legacy_window_end`, 세션 tz 무관) 후 재실행 — 게이트·전환표 수치 불변.
- 잔여 림 미회복(weekly 23·backtest 158)에는 "+1 tick" 구 관례 행이 섞여 있을 수 있다(2단 매칭은 −0.1 만 역산) — 소급 시 NULL 로 남음.
- `--apply` 전 추가 관측 권고(리뷰 Rec 3): `exact` 매칭 구 행(weekly 87·backtest 514)의 "손잡이 시작 봉 high − pivot_eff" 분포 — 수 % 이상이면 돌파 봉을
  시작으로 잡은 행이라 #161 소비 전 판단 재료. §6-4 관측에 "as_of 봉이 돌파 봉(close > pivot)인 행의 (B′) 발화율"(Rec 4) 추가.

## 다음

- `--apply` 는 사용자 승인 후(테이블 명시, 다른 열 불변). 그 전에 위 Rec 3 분포를 readout 에 추기.
- 배포 후 첫 주말: 신규 cwh 행 `handle_low` non-null 비율·발화율·(D′) 하단 마감 분배일 비율 1회 기록(설계 §6-4).
