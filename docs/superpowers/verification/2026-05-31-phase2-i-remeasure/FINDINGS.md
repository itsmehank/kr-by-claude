# Phase 2 (i) build-first 재측정 — FINDINGS (진행 중)

> spec §10 / plan Task 11. 동일입력 N=10 재현성 측정. 실제 LLM 호출 (claude --print), DB 미기록.
> 데이터: 검증 시점 운영 DB (005850 주봉 2025-04 ~ 2026-05).

## 0. 요약 (현재까지)

- **005850 (gate3_neg, 프로덕션 비결정성의 원래 검체) — 1차 바 통과.** 측정-우선 scaffolding + (A) 경계 수렴 규칙 적용 후 동일입력 verdict 가 **watch 10/10 재현**. 프로덕션 baseline (cup_with_handle 1/5, watch 4/ignore 1) 대비 결정적 안정화.
- **음성 패널 (gate0/1/2 + climax + positive) 미실행** — (A) 의 over-forcing("always watch") 반증 시험으로 진행 예정.

## 1. 스캐폴딩 구멍 (smoke 가 잡음 → Task 7 ↺)

- smoke #1 (측정-우선 1차, fix 전): `measurements=null` 비상구 발견 — none-run 에서 feature 비감사 → 측정-우선 설계(성공정의 #1) 무력화.
- **Task 7 ↺ fix**: `prior_uptrend_pct`·`cup_depth_pct`·`cup_shape` 항상 보고 강제 + `rejected_gate`(gate0/gate1/gate2/not_cup_family) 의무화 → none 근거 감사 가능. (commit `32deb17`)
- smoke #2 (fix 후): measurements 정상 populate 확인 (`measurements_null_runs=0`).

## 2. 005850 N=10 — (A) 경계 수렴 규칙 전후

데이터 객관 read (60주): prior_uptrend ≈ +110~166%(>>30), 2026-02 peak 77,400 → 04 trough ~53,200 (−31%) → 05 회복 ~77,300. depth 26~31% (33% cap 직하 경계), 최근주(05-22) 35% intraweek range = climax flavor. **= 진짜 경계 종목** (cup-faulty 와 climax 사이).

| 축 | (A) 전 N=10 | **(A) 후 N=10** |
|---|---|---|
| classification | watch 6 / ignore 4 | **watch 10/10** ✅ |
| pattern | cup 6 / none 4 | cup_with_handle 10/10 |
| cup_shape | U 6 / **V 4** | **U 10/10** |
| rejected_gate | null 6 / not_cup_family 4 | null 10/10 |
| handle_status | faulty 3 / not_formed 3 / null 4 | faulty 7~8 / not_formed 2~3 |
| cup_depth_pct | 24.8~31.0 (전부 <33) | 24.8~31.3 (전부 <33, band-contained) |

- **진단 (instrumentation)**: 산술 feature(depth·prior_uptrend)는 (A) 전부터 안정 — 측정-우선이 *산술* 차원 고정 성공. 불안정은 **질적 `cup_shape` U/V(6/4)** 였고, 그게 verdict(watch/ignore)로 캐스케이드.
- **(A) 효과**: 경계 수렴 규칙(명백한 실격 아니면 형성중 watch 수렴 + 1차 라우팅/Gate2 를 '명백한' 실격으로 한정)으로 verdict 가 watch 10/10 재현. (commit `aa268b9`)

## 3. ★ 미래 부채 / caveat (정직 기록)

1. **(A)는 U/V 를 *증명*으로 푼 게 아니라 *라우팅 지시*로 덮음.** (A) 후 cup_shape=U 10/10 (V→0) 이라, V 회차가 없어 **#1(지각 비결정) vs #3(진짜 경계) 판별이 무력화**됨. (depth,shape) 짝 비교 불가. → 경계 종목의 U/V 곡률을 *측정 함수*로 고정(베이스 바닥 시간비율·대칭 등 측정 앵커 = 옵션 (B)), 또는 OHLCV 독립 곡률 검출(옵션 (ii))은 **미해결 과제로 남김**. 단 (i) 성공정의는 'verdict 재현'이지 'U/V 원인 규명'이 아니므로 이번 합격을 바꾸지 않음.

2. **(A) over-forcing("always watch") 미검증.** (A)가 005850(경계)만 watch 로 수렴시킨 게 아니라 *명백한 직하강 V / 명백한 climax 과열*까지 watch 로 빨아들이는지는 **음성 패널(gate2_neg·climax)로만 반증 가능**. 이게 다음 단계 최우선 리스크.

## 4. 다음 — 음성 패널 ((A) 반증 시험)

| 가지 | 케이스 | 기대 (안정) | (A) 반증 의미 |
|---|---|---|---|
| **gate2_neg** | 명백한 직하강·좁은 V (둥근 바닥 없음) | **none/ignore 유지** | watch 로 새면 (A) 과광범위 → Gate2 재정련 |
| **climax** | 급등+거래량 폭발+연장 과열 | **ignore 유지** | watch 로 새면 (A)가 정당한 회피를 깸 |
| gate0_neg | 선행상승 <30% | none | — |
| gate1_neg | depth >33% / wide-loose | none | — |
| positive | 적법 핸들 cup (상단절반·50일선 위·하향 drift·≤12%) | entry/watch | over-forcing 역방향(적법인데 none?) 가드 |

- 병렬화(ZIP 1회 빌드 + ThreadPool workers=5)로 종목당 N=10 ≈ ~8~10분 (commit `perf`). 순차 40분 대비 ~5배.

## 5. climax_neg (001820 삼화콘덴서) N=10 — (A) over-forcing 반증 **통과**

데이터: +132% 4주 / 50일선 +131% 과확장 = 교과서적 climax. 합격기준 사전 고정 = ignore ≥9/10.

| 축 | 결과 |
|---|---|
| **classification** | **ignore 10/10** ✅ |
| **climax_run flag** | **10/10** ✅ (과열 인식 재현) |
| rejected_gate | not_cup_family 10/10 |
| extended_from_ma | 10/10 |
| pattern | none 10/10 |

- **결론: (A) 균형 증명.** 경계 종목(005850)은 watch 10/10 수렴 + 명백한 climax 는 ignore 10/10 배제 유지 → (A)는 "애매한 것만 watch, 명백 실격은 여전히 ignore". caveat 2(over-forcing="always watch") 반증.
- 부수 관찰: not_cup_family 경로라 cup_depth_pct noisy(0~41.5)·prior_uptrend noisy — cup 아니니 depth 무의미(verdict/routing/flag 는 안정). measurements 강제 보고가 비-cup 에선 noise 산출이나 무해(rejected_gate 가 not_cup_family 로 근거 명시).

## 6. 잔여 패널 (진행 중)

| 가지 | 티커 | 기대 | 상태 |
|---|---|---|---|
| gate1_neg (deep U) | 004440 삼일씨엔에스 (dd54.9%) | Gate1 none (깊은-U도 watch 로 안 끌림) | 실행 중 |
| gate2_neg (clear V) | 미정 | none | 데이터 제약(moderate-depth clear-V 희소) — 억지선정 금지, 005850 V-회차 사후분석 보강 검토 |
| gate0_neg (선행<30%) | 미정 | none | 미선정 |
| positive (적법 cup) | 미정 | entry/watch | 미선정 |
