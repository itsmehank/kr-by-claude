# §6.2 shadow 게이트 발화·기존 LLM 판정 불일치 16건 판독 (#44)

2026-07-21. 읽기 전용 분석 — LLM 재실행 0회(저장본 `backtest_classification` 판독만),
production DB(`kr_pipeline`)는 SELECT 만. 원자료: `data/verification/2026-07-21-stage3/replay_results.json`
(사전등록 `docs/superpowers/specs/2026-07-21-issue44-stage3-verification-prereg.md` §8 측정 결과의 `records`
필드 4,252행) + `backtest_classification`(reasoning/risk_flags/watch_reason/triggered_rules)
+ `kr_pipeline.llm_runner.compute.climax_topping.compute_topping_gates` 재실행(순수 함수,
LLM 아님 — g0/tb/td 세부값 및 tc/ta 보조 신호 확인용, DB 는 read-only).

## 1. 대상 16건

`s62_branch_either=True`(§6.2 발화) ∧ 기존 `classification != 'ignore'`(would_force 대상).
전량 `branch_d`(T-D 분배일)만으로 발화 — `branch_b`(T-B, 10주선 8주+ 연속 이탈)는 16건
전부 `False`. 전량 기존 분류 `watch`(entry 0건), `baseline=no_transition`(anchor 없음 —
50주 초과 전 이력에서 Stage1→2 전환 자체를 탐지 못한 종목들).

| symbol | date | dist_count_25s | tb_weeks_below_10w | tc_sma40_turndown | ta_max_decline_now |
|---|---|---|---|---|---|
| 004020 | 2021-02-06 | 4 | 2 | False | False |
| 001460 | 2021-10-16 | 4 | 1 | False | False |
| 010130 | 2022-02-26 | 5 | 1 | False | False |
| 017960 | 2022-05-21 | 8 | 1 | False | False |
| 078350 | 2022-05-21 | 5 | 1 | False | False |
| 038540 | 2022-06-04 | 5 | 3 | False | False |
| 017960 | 2022-07-23 | 5 | 3 | False | False |
| 214370 | 2022-09-24 | 6 | 1 | False | False |
| 016710 | 2022-12-24 | 4 | 1 | False | **True** |
| 003160 | 2023-05-27 | 4 | 1 | False | False |
| 060980 | 2023-07-29 | 4 | 2 | False | False |
| 264660 | 2023-08-05 | 10 | 1 | False | False |
| 017940 | 2023-10-28 | 5 | 1 | False | False |
| 206650 | 2024-01-20 | 7 | 1 | False | False |
| 166480 | 2024-07-20 | 5 | 1 | False | False |
| 298380 | 2024-09-28 | 4 | 1 | False | False |

핵심 구조적 사실: `tb_weeks_below_10w` 는 16건 전부 1~3주(임계 8주에 크게 미달) —
"10주선 아래로 짧게(1~3주) 들어간 상태"이지 지속 붕괴가 아니다. `tc_sma40_turndown`
(40주선 턴다운, T-C 보조 신호)은 **16건 전부 False** — 40주선은 계속 상승 중이었다.
즉 이 16건 전부 **T-D(분배일 카운트) 단독으로 발화**했고, §6.2 코드가 함께 산출하는
보조 부패 신호(T-B 지속 이탈, T-C 40주선 턴다운)는 하나도 동반되지 않았다.

## 2. 판독 절차

각 건의 `backtest_classification.reasoning`(LLM 저장 판독문)을 위 표의 게이트 세부값과
대조해, LLM 이 "10주선/§6.2/topping/shakeout" 관련 정당화를 명시했는지, 명시하지 않았어도
분배일 수치 자체를 인지하고 판단에 반영했는지 확인했다.

## 3. 분류 결과

- **(B) 게이트 과발화 — LLM 이 정당한 예외를 명시**: **15건**
  - (B-명시, §6.2/10주선/topping/shakeout 직접 언급) 8건: 004020, 078350, 016710, 003160,
    060980, 017940, 298380, 017960(2022-07-23)
  - (B-준명시, 분배일 수치를 직접 인지하고 "장기 이탈 지속 시 ignore 재검토" 유형의
    조건부 유보로 마무리) 3건: 001460, 206650, 166480
  - (B-암묵, 종목 자체 분배일 카운트를 본문에 정량 인용하며 "이미 시장 컨텍스트로
    포괄" 등으로 명시적으로 escalate 보류) 4건: 010130, 017960(2022-05-21), 214370, 264660
- **(A) LLM 놓침**: **0건**
- **(C) 데이터 품질**: **0건** — 전 16건 `quality_flag_topping=False`(#49 유형 adj
  불변식 위반은 close≤0/None 게이트에만 영향, 16건 모두 미해당). halt/0-volume 의심
  흔적도 reasoning·재계산 값에서 발견되지 않음(다만 daily/weekly 원장 자체를 셀 단위로
  전수 대조하지는 않음 — 한계로 기재).
- **(D) 판정 곤란**: **1건** — 038540(2022-06-04). reasoning 이 분배일·10주선·40주선
  어느 축도 본문에서 다루지 않는다(risk_flags=`narrow_base`/`late_stage_base`/
  `unfavorable_market_context`만, market-level 분배 3회만 언급 — 종목 자체 dist_count=5는
  미언급). 단, 재계산된 `tc_sma40_turndown=False`·`tb_weeks=3`은 여전히 지속붕괴가
  아님을 보여줘 게이트 과발화 쪽에 무게가 실리나, LLM 이 그 축을 검토했다는 텍스트
  근거가 없어 B로 단정하지 않고 D로 유보.

## 4. 대표 사례 발췌

**B-명시 — 004020 (2021-02-06)**: `dist_count_25s=4`(임계 최소치), `tb_weeks=2`.
reasoning 결론부: "40주선 상승 지속·Stage 2 유지·10주선 결정적 이탈 아님으로 **§6.2
topping force-ignore 미충족(ignore 아님)**." — LLM 이 §6.2 규약 자체를 명명하며
현재 상태가 강등 조건에 미달함을 직접 판정했다. 재계산치(`tc_sma40_turndown=False`)가
이 판정과 정확히 일치.

**B-명시 — 017940 (2023-10-28)**: `dist_count_25s=5`, `tb_weeks=1`. reasoning: "§6.2
topping 게이트는 G0가 주봉 10주선 -0.18%(**단일주 정상 pullback, T-B 1주 면제**)에
불과하고 1주 전 신고가·40주선 상승이라 top이 아닌 shakeout → force-ignore 아님." —
LLM 이 T-B 임계(8주)를 알고 있고 "1주"라는 실제 재계산치(`tb_weeks=1`)와 정합하는
근거로 명시 반박.

**B-암묵 — 017960 (2022-05-21)**: `dist_count_25s=8`(임계의 2배). reasoning: "최근 25일
종목 자체 distribution day도 8회로 기관 매도 흔적이 있으나, **상승일 거래량까지 함께
마르는 패턴은 아니라 별도 플래그는 보류했습니다**." — §6.2 라는 이름은 안 쓰지만
정확히 그 입력값(분배일 8회)을 인지한 뒤 의도적으로 escalate 하지 않은 판단.

**D — 038540 (2022-06-04)**: reasoning 이 시장 전체 분배(3회)만 언급하고 종목 자체
`dist_count_25s=5`(§6.2 발화 원인)는 어디에도 등장하지 않는다. narrow_base·
late_stage_base 축으로만 watch 를 정당화 — §6.2 축 자체를 다루지 않아 "정당한 예외를
의도적으로 인정"했는지 "단순히 그 신호를 못 봤는지" 텍스트만으로 구분 불가.

## 5. 집계 및 결론

**B=15 / A=0 / C=0 / D=1** (16건 중).

이 16건은 게이트 규약 자체의 구조적 결함 신호다. 전량이 `branch_b`(T-B, 지속 붕괴)
없이 `branch_d`(T-D, 단순 분배일 카운트≥4) 단독으로 발화했고, 재계산된 보조신호
T-C(40주선 턴다운)는 16건 전부 False — 즉 "10주선을 1~3주 짧게 하회 + 최근 25세션
분배일 4개 이상"만으로 §6.2 가 발화하며, 이는 시장 전체가 불리한 국면(대부분 KOSPI/KOSDAQ
downtrend·correction·미확인 rally, `unfavorable_market_context` 가 16건 중 15건에 동반)
에서 종목별 분배일 카운트가 자연히 부풀려지는 상황과 강하게 겹친다. LLM 은 15/16 건에서
(명시적이든 암묵적이든) 이 분배일 신호를 이미 인지하고도 40주선 상승 지속·단일주
pullback·shakeout 근거로 watch 유지를 정당화했다 — 게이트가 놓친 게 아니라
**게이트가 LLM 보다 관대한(느슨한) 기준으로 과발화**하는 패턴이다.

**활성화 결정 함의**: 사전등록 §4 해석 밴드상 ignore 정합률 57.89%는 "30~60% = 규약
재검토 신호" 구간에 해당했는데, 이번 16건 판독은 그 신호가 실체 있음을 뒷받침한다 —
현재 `6_2_topping_shadow` 자격조건(G0 ∧ (T-B ∨ T-D))을 그대로 실제 강등(ignore 강제)에
쓰면, 40주선이 여전히 상승 중인 정상 Stage 2 pullback을 시장 전체 분배일 과다 국면에서
오분류로 ignore 강등시킬 위험이 높다. 활성화 전에 **T-D 단독 발화(branch_d ∧ ¬branch_b)
분지에 T-C(40주선 턴다운) 코로보레이션을 추가 조건으로 요구하는 안**을 규약 재검토
항목으로 올릴 것을 권고한다.
