# 0단계 — #37/#38 선계산·사후검증 패턴 실측 검증 (#44 착수 선행조건)

2026-07-17 최초 실행, 2026-07-18 **v2 — PR #51 코드리뷰 발견 반영 재실행**.
브랜치 `worktree-44-stage0-gate-verification` (base main c6241b9).

## 0. v2 개정 이력 (PR #51 리뷰 → 수리 → 재측정)

v1 하네스는 production 트리거 경로와 3가지가 달랐다(리뷰 발견, 전부 실측 확증):
① stop_loss 미주입(production 은 `load.py:164` 에서 base_low 주입) — invalidation
경로 일부 미측정, ② "행당 첫 발동일만" 측정(production 은 당일만 dedupe — 트리거
유지 시 다음 날 재평가) — 모집단 과소, ③ prev_close lookback 이 캘린더 창에 갇힘
(production 은 무제한). v2 는 셋을 모두 production 규약에 정합시켜 재실행했고,
§4/F1 의 ad-hoc 수치는 `scripts/stage0_layer2_readout.py` 로 스크립트화했다.
v1 리포트의 "표본 30건 전부 미충족 게이트 존재" 문장은 원자료 반증으로 정정(§5).

## 1. 목적과 방법론

이슈 #44 는 "#37(B 게이트 선계산)·#38(A 부분 이관) 패턴이 **실가동 데이터로 검증된
뒤** 착수"를 선행조건으로 명시한다. 현재 LLM cron 은 전부 dry-run 이라 실전 데이터가
없으므로, 사용자 승인(2026-07-17) 하에 다음 두 층으로 **대체 실측**했다:

- **층① (계산층, LLM 0회)**: production 코드를 그대로 import 해 과거 데이터에 재생.
  판독 기준 — build 예외 0 / 소스 날짜 불일치·결측 0 / 예상 밖 null 없음 / 값
  범위·발화율이 정의역 안에서 해석 가능할 것.
- **층② (LLM 소비층)**: 표본 B 무인 백필이 **머지(07-13) 이후 코드로 LLM 실호출**하며
  생성한 backtest_classification 행 판독 + 5b 층화 표본 30건 + go_now 양성 프로브
  1건의 직접 호출. 판독 기준 — 선계산 값과 LLM 최종 판정의 모순 0 / 강등 발화 건의
  개별 타당성 / 발화율이 머지 전과 같은 자릿수(패턴 판정 — 건별 재실행 비교는 LLM
  비결정성 때문에 금지 규약).

재생 하네스: `scripts/stage0_replay_5b_gates.py`(B), `scripts/stage0_replay_a_precompute.py`(A),
층② 판독: `scripts/stage0_layer2_readout.py`(재현 스크립트), `scripts/stage0_5b_llm_sample.py`,
`scripts/stage0_5b_gonow_probe.py`. 원자료: `data/verification/2026-07-17-stage0/*.json`.
production DB 는 read-only 로만 접근.

⚠ **행수 표류**: 표본 B 무인 백필이 측정 기간 내내 진행 중이라 backtest_classification
행수는 실행 시점마다 다르다(07-17 층① A 시점 3,655 → 07-18 readout 시점 3,908).
스크립트 출력이 실행 시각·행수를 함께 기록하므로 수치 간 소차는 표류분이다.

## 2. 층① 결과 — B (#37 computed_gates) [v2 재실행]

재생 대상: backtest_classification 의 pivot 보유 entry/watch 1,075행 → 유효 주간의
**모든 트리거 발동일**을 production 규약(stop_loss=base_low·당일 dedupe·prev_close
무제한 lookback)으로 검출(773행에서 **2,007 발동일**: promotion 1,474 / invalidation
452 / breakout_from_watch 72 / breakout 9) → `build_for_5b(as_of, prior_row)` 재생
(look-ahead 차단, prior 변환은 trigger_audit.prior_row_for 단일 정의 재사용).

| 판독 기준 | 결과 |
|---|---|
| build 예외 | **0 / 2,007** |
| ohlcv_last_date ≠ as_of | **0 / 2,007** (None 별도 계수: **0**) |
| 게이트 null (판정 불능) | **0** — 22개 키 전부 값 산출 |
| 값 범위 | close_range_pos 5건(>1, 최대 1.0069 — 발견 F1) 제외 전부 정의역 내 |

발화율(발췌): spread_wide_loose 36.7%, no_dist_3d false 54.7%, market_recovery_ok
true 12.5% — 트리거일(고변동일) 특성과 표본 기간(2021~2024 약세장 비중)에 정합.

**알려진 한계**: production 은 LLM abort 후 그 분류의 후속 트리거를 skip 하지만
(`_aborted_since_classification`), 재생은 LLM 판정이 없어 abort 체인을 시뮬레이션하지
않는다 — 재생 모집단은 production 의 **상위집합**(과잉 방향 — 검증 목적상 보수적).

**발견 F1 — adj OHLC 불변식 위반 (게이트 결함 아님, 소스 유래) → 이슈 #49**:
close_range_pos>1 추적 결과 `daily_prices` 저장값 자체가 adj_close > adj_high.
pykrx `adjusted=True` 응답이 원인(직접 호출 재현: 299900 2021-03-22 고가 2,612 <
종가 2,613 — 원본은 동일값 10,450, 환산 반올림 컬럼별 불일치). 로컬 파이프라인은
응답을 그대로 저장(계수 곱셈 없음). 전수: 07-17 측정 21,541행 → 07-18 readout
21,284행 — **adj-refresh 가 수정값을 재기록하므로 모집단 자체가 동적**(시점 기록
필수 근거). 2025년 이후 8행·최대 10원으로 production 영향 미미. boolean 판정
(upper_third)은 불변이라 행동 영향 0.

## 3. 층① 결과 — A (#38 선계산) [v1 측정 유지 — 리뷰 지적 무관 경로]

재생 대상: backtest_classification 전 행 3,655건(07-17 시점)의 (symbol,
analyzed_for_date) 에서 `build_minervini_detail`→`_conditions_summary`,
`build_market_context`→`_market_direction_gate`.

| 판독 기준 | 결과 |
|---|---|
| 재생 예외 | **0 / 3,655** |
| marginal_count null (미확정 규약) | **0** — 전부 확정 산출 |
| §2 demotion_trigger 발화 | 1,044 / 3,655 = **28.6%** |
| §3.5 force_watch=true | **86.7%** |

해석: 표본 기간이 약세장 비중이 커서 force_watch 고율은 기간 특성으로 정합.
demotion 28.6%는 "TT 를 아슬아슬하게 통과한 후보가 많다"는 스크리너 모집단 특성과
일관 — 실전 전환 후 최초 몇 주간 이 비율을 재관측할 것.

§8.5 밴드 would-be 발화율(머지 전 데이터, readout §4 재현): 측정 모수 자체가 희소 —
entry 행이 weekly 1건 + backtest 1건뿐이고 발화 0. 역사적 entry 희소성(설계 의도)
때문에 이 게이트는 과거 데이터로는 검증력이 없음 → 층②의 실발화 1건이 유일한 실측.

## 4. 층② 결과 — 머지 후 LLM 실호출 판독 [재현: stage0_layer2_readout.py]

readout 실행 시점(2026-07-18) 기준 pre 2,300 / post 1,608행(표류 주의 — §1):

- **선계산 순종 위반 0건**: §2 demotion_trigger=true 로 재생된 1,044 (symbol, 토요일)
  중 저장 분류가 entry 인 사례 **pre 0/661·post 0/383** (전부 watch/ignore).
- **§8.5 밴드 실발화 1건 정당성 확인**: 178920 2021-07-17, close 55,200 >
  pivot 52,000.1×1.05=54,600.1 → watch/extended 강등 + triggered_rules 감사 기록.
- **발화율 패턴(pre 2,300 vs post 1,608)**: 2E_tier1 3.3→6.2% / 2E_tier2 2.3→4.9% /
  2F 5.1→7.5%. 같은 자릿수(폭주·사멸 없음). 단 pre/post 의 analyzed_for_date 분포가
  달라(표본 B 는 2021~2023 집중) 교락 있음 — 경보 아닌 참고 지표.

**발견 F2 — 백필 경로의 가격 sanity 미실행 → 이슈 #50**: 머지 후 entry 중 1건
(317870 2022-04-09)이 pivot 없이 entry 로 저장 — `_validate_classification_prices`
는 weekly 경로(store.py:337)에만 호출되고 백필 insert 는 enum 검사만. §8.5 밴드
(`if ... and pv:`)와 평일 트리거 모두 무발화 통과 → 행동 불능 entry 조용히 잔존.

## 5. 층② — 5b LLM 직접 호출 실측 (표본 30 + 양성 프로브 1)

**층화 표본 30건** (`stage0_5b_llm_sample.py`, v1 재생의 705 풀에서 추출 — 추출 풀은
v1 기준이나 각 컨텍스트의 게이트 값·호출 기록 자체는 유효): 모델 전 건
claude-sonnet-5. 호출 실패 0, **H1~H4 위반 0**(abort 1건 = stop_loss_breach 카탈로그
내), **S1 모순 0**(breakout·bfw 12건 reasoning 전수 판독 — 전 건이 computed_gates
값을 그대로 인용, 재계산 없음). H4 후반부(비-abort 인데 abort_reason non-null —
리뷰 반영 보강) 사후 판독: **잠재 위반 0/30**.

go_now 0회의 해석(v1 문장 정정): 30건 중 **29건은 미충족 게이트가 최소 1개** 존재.
나머지 1건(016710, promotion)은 §3.1 5게이트를 전부 충족했으나 **promotion 은
프롬프트가 go_now 자체를 금지**하는 유형이라 wait 이 정답 — 즉 30건 전부에서
go_now 억제는 규약상 올바른 판정이었다(단 "전부 미충족 게이트 존재"는 틀린 서술
이었음 — 원자료 반증으로 정정).

**go_now 양성 프로브 1건** (`stage0_5b_gonow_probe.py`): v2 재생 2,007건 중 §3.1
5게이트+§3.5 회복 2게이트 전충족 컨텍스트는 정확히 1건 — 112610 2023-04-14
breakout_from_watch. 실호출 결과 **decision=go_now (confidence 0.85)**, reasoning 이
게이트 값 전부를 그대로 인용. **양성 경로(자격을 갖추면 실제로 go_now) 실측 확인.**

## 6. 미커버 공백 (이 검증이 말하지 못하는 것)

1. **weekly(production) 경로**: 머지 후 주말 분류 실행 0회(cron dry-run) —
   conditions_summary 가 실린 weekly payload 의 실호출은 미검증. 표본 B 와 코드
   경로는 동일(build_payload 공용)하나 실행 환경이 다름.
2. **null 보수 경로**: 층①·② 전체에서 게이트 null 이 발생하지 않아 "null=통과 금지"
   규약은 단위 테스트로만 검증된 상태(실데이터 미발화).
3. **abort 체인**: §2 한계 — 재생은 abort 후 skip 을 시뮬레이션하지 않음(상위집합
   측정이라 검증 결론에는 보수 방향).
4. go_now 양성 경로는 표본 1건(historical 전체에서 유일) — 실전 전환 후 누적 관측.

## 7. 판정 — #44 선행조건 충족 (사용자 결정 2026-07-18, v2 재확인)

- 층①(재생 5,662건: B 2,007 + A 3,655)·층②(LLM 실호출 판독 1,608 + 직접 호출 31)
  에서 **#37/#38 패턴 자체의 결함 0건, 선계산 순종 위반 0건, 양성 경로 1/1 확인**.
- v2 재실행(모집단 2.8배 확대·production 규약 정합)에서도 결론 불변 — v1 의 측정
  공백(리뷰 발견 ①②③)이 결론을 바꾸지 않았음을 재측정으로 확인.
- 발견 2건은 패턴 로직 무관 — F1=이슈 #49, F2=이슈 #50.
- 잔여 공백(§6)은 실전 전환 후 자연 관측 대상. 다음 단계 = #44 1단계 분해 설계 브리핑.
