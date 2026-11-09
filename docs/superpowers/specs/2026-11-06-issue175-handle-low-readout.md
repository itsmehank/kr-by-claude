# #175 저장본 재현 readout — 구(2026-11-06 이전) vs 신 검출기 (2026-11-06, PR #263 리뷰 2차 반영본)

> 읽기 전용(운영 DB SELECT 만, KRX 0·DART 0·LLM 0). 스크립트 `scripts/issue175_handle_low_readout.py`, 결과 JSON
> `data/verification/issue175_handle_low_readout_20261106.json`. 설계 = `specs/2026-11-06-issue175-handle-low-design.md` §6-2.
> 숫자는 관측이며 판정이 아니다(governance 3-5). 구 규칙 = `compute/handle_low_readout.legacy_detect`(독립 재구현: UTC 창 끝·1단 매칭·
> 0.80 컵 평균·분배일 ≥1), 신 규칙 = `compute/handle_quality.compute_handle_quality(as_of=COALESCE(analyzed_for_date, KST−1))`.
> 구 규칙의 창 끝은 저장 당시 store 경로 그대로(실전 = classified_at **UTC** 날짜 미포함, 백필/백테스트 = analyzed_for_date+1 미포함).
> 2차 반영: S4′ 가 ①·② 중 **더 이른 봉**을 쓰도록 바뀌어(리뷰 1) 구 관례 행의 손잡이 시작이 돌파 봉에서 고점 당일로 당겨진 행이 생겼다 — 게이트 정의 §(a).

## (a) 머지 게이트 — 저장 발화 행에서 구·신 손잡이 시작·고점

게이트 = 구·신 둘 다 식별한 행에서 (i) `handle_start`·`handle_high` 일치 **또는** (ii) 신 시작이 더 이르고 ②(pivot−0.1) 매칭(`start_corrected`:
구 관례 행에서 고점 당일이 돌파 봉보다 앞선 경우 — S4′ 의도된 교정) + 구 식별·신 비식별이 가드·길이 규칙 외에는 0건.

| 표 | 저장 발화 행 | 둘 다 식별 | (i) 일치 | (ii) 교정 | 불일치 | 구 미식별 | 신 미식별 가드 | 신 미식별 길이 규칙 | 신 미식별 기타 |
|---|---|---|---|---|---|---|---|---|---|
| weekly_classification | 65 | 55 | 42 | **13** | 0 | 6 | 4 | 0 | **0** |
| backtest_classification | 585 | 500 | 284 | **216** | 0 | 73 | 11 | 1 | **0** |

**게이트 통과**(exit 0).

- 교정 행(ii)의 `handle_low`: 더 이른 시작이 봉을 더 포함해 weekly 7/13·backtest 175/216 은 저점이 **더 낮아지고** 나머지는 같다(높아진 행 0).
  구 규칙이 돌파 봉을 시작으로 잡았던 행이라 구 저점은 "돌파 후 되돌림 저점" 이었다(리뷰 1 결함).
- 구 미식별(legacy_none) 79 = `S5 handle<5` 75(#177 이전 하한 3일 시절 저장) + `S4 rim not recovered` 4(adj 재적재 후 고가 변동). 이번 변경과 무관.
- 신 미식별 가드 15 = `handle_above_pivot`·`pivot_below_cup_bottom`(컵 바닥 봉 고가 ≥ pivot — 재스케일 종목: 005490·006490·006740·007110·031860·032080·
  090150·105550·189300·206640·207760·214370, Phase A A2 집합). 길이 규칙 1 = 002390(시작이 당겨져 베이스 4일 < 5).
- 저장 metrics 와의 차이(stored_drift, 게이트 비입력) 1 = 247540 — 구 규칙 재구현도 오늘 데이터에서 같은 값(데이터 빈티지).

## (b) `handle_end` 변화 행(저장 vs 신)

| 표 | 변화 행 | 09:00 KST 이전 실행 | 09:00 이후(저녁 daily_delta) |
|---|---|---|---|
| weekly_classification | 34 | 4 (053160·092230 07-28 02시, 049430 08-29 03시, 041520 10-17 05시 — 명세 §7-7 예측과 일치) | 30 |
| backtest_classification | 0 | — | — |

설계 §6-2(b) "기대 4행" 은 과소였다. 구 UTC 규칙은 **저녁 실행(18~21시 KST)에서도 당일 봉을 제외**했다(`date < 당일`). 신 규칙 `as_of 포함` 은 그 봉을
넣는다 — 설계 S5′ 정의 그대로이며 백필 경로(`gate_at = D+1` 미포함 = D 포함)와 같은 봉 집합(백테스트 변화 0 이 그 증거).

## (c) 발화 집합 변화

| 표 | fired→fired | fired→not | not→fired | legacy_none→fired | legacy_none→not | fired→none(가드) |
|---|---|---|---|---|---|---|
| weekly | 61 | 3 | 1 | 92 | 21 | 4 |
| backtest | 476 | 17 | 1 | 333 | 97 | 29 |

사유별(신): weekly `distribution_in_handle` 147 · `volume_not_contracting` 66 / backtest 767 · 527. (구: weekly 62·49, backtest 479·442.)
**관측(B-수치, 판정 아님)**: 식별 행 중 발화 비율 weekly 154/192 = 80%, backtest 810/946 = 86% — 구 규칙(81%·91%)과 비슷하게 높다.
(D′) 가 분배일을 "하단 마감" 으로 좁혔는데도 손잡이(중앙 ~18일)에는 하단 마감 분배일이 거의 항상 1일 이상 있다. 수치(마감 위치 0.5)는 design 이라
변경은 별도 판정(2-2) — 다음 4주 실전 발생률과 함께 재검토 항목.

## (d) 커버리지

| 표 | 구 식별 | 신 식별 | 신 `pivot_eff_source` exact / minus_0_1 | 주요 미식별 사유(신) |
|---|---|---|---|---|
| weekly | 84/368 (22.8%) | **192/368 (52.2%)** | 60 / 132 | pivot_basis None 119·cup_high 15·range_high 5, 림 미회복 23, 손잡이 <5일 7, 베이스 <5일 2, 컵 바닥 가드 5 |
| backtest | 548/2,350 (23.3%) | **946/2,350 (40.3%)** | 293 / 653 | pivot_basis None 1,037·range_high 67, 림 미회복 158, 손잡이 <5일 93, 컵 바닥 가드 36, 기타 13 |

미식별의 대부분은 `pivot_basis ≠ handle_high`(weekly 139: 그중 119 는 LLM 이 pivot 자체를 내지 않은 `base_forming` 행 — 손잡이 고점이 없어 어떤 코드로도
불가, 20 은 LLM 이 컵 고점·구간 고점 기준으로 읽은 행). 손잡이 고점이 있는 행 기준으로는 weekly 192/249 = 77%.

## (e) `handle_low` 깊이(pivot_eff 대비 %) — 관측

| 표 | n | Q1 | 중앙 | Q3 | P90 | 최대 | 8~12% 밴드 |
|---|---|---|---|---|---|---|---|
| weekly | 192 | 9.0 | 12.2 | 15.0 | 18.6 | 25.6 | 55 (28.6%) |
| backtest | 946 | 8.2 | 11.5 | 15.0 | 18.5 | 28.4 | 290 (30.7%) |

책 밴드(HMMS 8~12%)와의 대조는 관측이다(프롬프트 Gate3 가 판정).

## (f) LLM 보고 깊이(`measurements.handle_depth_pct`)와 |차|

| 표 | n | 중앙 | >3pp | 비율 |
|---|---|---|---|---|
| weekly | 177 | 0.04pp | 24 | 13.6% (11-05 명세: 36%, 1차 반영본 17.6%) |
| backtest | 873 | 0.26pp | 158 | 18.1% (1차 32.9%) |

시작이 고점 당일로 당겨지면서 LLM 이 본 손잡이 구간과 일치율이 올라갔다(관측).

## §7 과거 행 소급 `--plan` (읽기 전용 — `scripts/issue175_handle_low_backfill.py --plan --table all`)

운영 DB 에는 `handle_low` 열이 아직 없어(schema 적용은 머지·승인 후) 전 cwh 행을 후보로 집계했다. `--apply` 는 열 적용 후 테이블 하나씩, 사용자 승인 후에만.

| 테이블 | 후보(cwh) | 채워질 행 | 주요 미평가 사유 |
|---|---|---|---|
| weekly_classification | 372 | **193** | pivot_basis None 122·cup_high 15·range_high 5, 림 미회복 23, 손잡이 <5일 7, 베이스 <5일 2, 컵 바닥 가드 5 |
| classification_backfill | 48 | **10** | pivot_basis None 29·range_high 5, 림 미회복 4 |
| backtest_classification | 2,351 | **946** | pivot_basis None 1,038·range_high 67, 림 미회복 158, 손잡이 <5일 93, 컵 바닥 가드 36, 기타 13 |
| recall_audit_classification | 323 | **128** | pivot_basis None 152·range_high 4, 손잡이 <5일 ~27, 림 미회복 ~14, 가드 4 |

가드(`pivot_below_cup_bottom`·`handle_above_pivot`) 행은 adj 재스케일 vs 저장 pivot 불일치 — 설계 §7 대로 NULL 유지.

## 독립 리뷰 반영·권고

- R1(브랜치 전체): 구 규칙 재현의 실전 행 창 끝을 **UTC 날짜**로 고정(`legacy_window_end`).
- R2(PR #263 코드 리뷰): S4′ 더 이른 봉 선택(위 (a)(ii)), `pivot_below_cup_bottom` 가드, (B′) 50일 평균 = 손잡이 첫 non-NULL, 스킵 사유 반환값
  (`compute_handle_quality_with_reason`), as_of 폴백 단일화, 스크립트 정리, 레거시 앵커 스크립트 키 갱신.
- 잔여 림 미회복(weekly 23·backtest 158)에는 "+1 tick" 구 관례 행이 섞여 있을 수 있다(2단 매칭은 −0.1 만 역산) — 소급 시 NULL 로 남음.
- `--apply` 전 추가 관측 권고(R1 Rec 3): `exact` 매칭 구 행의 "손잡이 시작 봉 high − pivot_eff" 분포. §6-4 관측에 "as_of 봉이 돌파 봉인 행의 (B′) 발화율"(Rec 4).

## §6-4 첫 실전 관측 — 2026-11-08 run 2381 (as_of 2026-11-06, 판정 아님·3-3)

- 발단: 11-07 토 06:34 자동 실행(run 2380)은 claude CLI 실행 파일 미발견으로 37/37 실패(#269) → 11-08 23:49 사용자가 `weekend_chain.sh` 수동 재실행(run 2381, 새 검출기 코드 + #184 C3′, prompt `f7eb1fb770fb`, 37/37 성공).
- 소급 `--apply` 는 11-06 완료(weekly 193·backfill 10·backtest 946·recall 128, §7 plan 과 동일). Rec 3 분포는 #175 코멘트(11-06) 기록.

| 항목 | 값 |
|---|---|
| 후보·행 | 37 (watch 36 · ignore 1) |
| 패턴 | none 19 · flat_base 11 · cup_without_handle 5 · **cup_with_handle 2** |
| handle_low non-null | cwh 2 중 1 (50%) — 전체 37행 중 1 |
| handle_quality 발화 | 1/37 (3%) |
| 발화 행 metrics | handle 10-29~11-06(7일), pivot_eff 16,960(`pivot_eff_source` exact), handle_low 15,310(깊이 9.73%), (B′) volume_vs_50d 1.401(손잡이 평균 > 50일 평균 = 결함), (D′) distribution_days 4 · lower_close 4, dry_up_days 0 |
| 비교선 | 10-02 69행(cwh 5·handle_low 3) · 10-08 77행(5·4) · 10-16 60행(5·4) · 10-23 4행·10-30 7행(체인 결손) |

- 해석(관측): 분모(cwh 2)가 작아 커버리지 50% 는 수치로 쓰지 않는다. 발화 1건은 (B′)·(D′) 둘 다 결함 — Rec 4 "as_of 봉이 돌파 봉인 행" 여부는 `handle_end`=as_of(11-06)라 해당(§6-3 start_corrected 유형). 4주 누적(≈12-06) 후 B-수치(발화율 82% 대비)로 재집계.
- 같은 run 의 교차 관측: #253 pivot 소수부≠0 0건·sanity_pivot_offset_rule 0건·effective_pivot≠pivot 9건(래칫), #184 volume_regime_flag 전부 mixed·ver 2.

## 다음

- 4주 누적(≈12-06) B-수치: 발화율·(B′)/(D′) 분포·handle_low 깊이 분포 — 주말 run 이 결손 없이 4회 쌓여야 함(#269 수리 PR #270 머지·plist 재설치 선행).
