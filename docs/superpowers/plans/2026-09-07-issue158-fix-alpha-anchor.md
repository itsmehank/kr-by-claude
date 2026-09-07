# #158 — find_anchor Fix α(C4 제거): Phase A 원인 분해 · Phase B 측정 · Phase C 적용

> 트리거: `climax_topping.py`(CLIMAX_ANCHOR_*·BREAKOUT_VOL_FLOOR 소비처)의 anchor 결합식 변경
> + `analyze_chart_v3.md` §6.1 앵커 정의 서술 동기화 + thresholds.py 는 **값·이름 불변**
> (CLIMAX_ANCHOR_TURNUP_WEEKS docstring 만 소비처 변경 사실 반영) — checklist (a) 사실 기준 해당
> → 본 문서 §5 의존성 맵. 원칙 2-1(현 main G2) 적용.

## 0. 판정(전문가, 2026-09-07)

- **원인**: 5조건 동일 주 동시 성립 요구 중 **C4(30/40주 SMA 4주 전 대비 상승)** 가 돌파 주와
  시간적으로 양립 불가. C4 는 [EXTENDS]이며 O'Neil 돌파 정의·Minervini 전환 기준 어디에도 "돌파
  주 동시 성립" 근거 없음.
- **Fix α**: C4 제거. 앵커 = 최근 **C1∧C2∧C3∧C5** 동시 성립 주. C1·C2·C3·C5 정의·수치 불변.
  TURNUP_WEEKS 상수는 C2 lookback 으로 계속 사용(삭제 금지).
- **원칙 1-1 4조건**: (a) 필수 부품 아님 — 제거 후 suite 정상 / (b) 커버리지 손실 없음 — C4 가
  담당하던 "Stage 2 = 이평 위·상승" 요구는 C5(close>SMA30/40)와 하류 P1(maturity) 이 담당 /
  (c) book-mandated 신호와 방향 충돌 — Stage 1 재형성(C1) 직후 주에 C4 가 원리상 불성립하여
  anchor 의존 신호 전체(P2·T1·T2·T-A·T5·T6·TA-d·scope)를 89.9% 행에서 차단 / (d) 미정의
  계산 없음 — C4 산출·소비 동시 제거.
- Minervini 기계 앵커(A4/A5 c1∧c2∧c3 연속 run)는 단절 취약 → 보류. A6 는 관측 기록만.

## 1. Phase A — 원인 분해(읽기 전용, 2026-07-21 stage3 replay 4,252행 × DB 결정론 재계산)

조건 전수(코드 순서): C0 이력>50주 [PRESERVES] · C1 직전 4주 close<SMA40 [EXTENDS] · C2 SMA40
4주 기울기 ≤+2% [EXTENDS] · C3 volume ≥1.4×50주 평균 [PRESERVES] · C4 SMA30/40 > 4주 전
[EXTENDS] · C5 close > SMA30, SMA40 [PRESERVES].

- near-pass(통과 개수 최대 주, 동률 최근) first-failing: C1 94.3% · C4 4.1% · C3 1.3% · C2 0.3%
  · C5 0. EXTENDS 실패 98.7% vs PRESERVES 1.3%. Stage 1(C1∧C2) 구간 부재 78행(2.0%).
- 보조 절단면(가장 최근 C1∧C2 주에서의 실패 집합, 3,743행): C4 단독 48.4% · C3+C4 41.4% ·
  C3+C4+C5 4.6% · C3+C5 3.4% · C3 단독 1.8%. 조건별 실패율 C4 94.4% / C3 51.2% / C5 8.5%.
  그 주 이후 8주 내 C3∧C4∧C5 동시 성립 59.0% — 그러나 그때는 C1 이 불성립(직전 4주가 이미
  SMA40 위). → **C1 과 C4 의 동일 주 동시 성립 요구가 구조적 차단.**
- A3: 분류 시점 minervini_pass — no_transition 3,820/3,821, anchored 431/431.
- A4: daily_indicators 에 sma_150/200·minervini_c1~c3 일별 이력 존재(2017-03-30~, 2,512종목,
  2018 이후 NULL 3.2~3.5%). 신규 계산 없이 산출 가능.
- A5(anchored 431행·30종목): Minervini 앵커 − O'Neil 앵커 = 중앙값 468일(사분위 7·468·1,077,
  −4~1,715), 종목 중앙값 345일. 연속 run 이 단절에 재시작(15/30 종목에서 시점별 상이) → 보류.
- A6(주간 anchor 의존 발화율, anchored vs no_transition 전체이력): P2 5.10/2.59 · T1 3.48/4.08
  · T2 3.94/2.36 · T-A 2.78/0.08 (%). 방향만 기록.

## 2. Phase B — Fix α 측정(스크래치패드, 사전등록 순환성 표기: 가설은 같은 4,252행에서 생성)

| 측정 | 결과 |
|---|---|
| B1 모드 | anchored 431→3,848 (90.5%), no_transition 3,821→**404 (9.5%)**. 종목(최신 행) anchored 30→198/214 |
| B2 기존 431행 | 불변 252 (58.5%), 후행 이동 179 (41.5%, 12종목, 이동폭 중앙값 99주·사분위 35·99·135), **선행 이동 0** |
| B3 weeks_since | 기존(현행 앵커) 중앙값 73·maturity 78.0% / 기존(Fix α) 32·72.2% / 신규 3,417행(180종목) 54·사분위 29·54·101·maturity **89.5%** |
| B4 발화율 | 아래 사전등록 기준선 표 |
| B5 잔여 404행 | Stage 1 부재 78, 나머지 326 의 차단 = **C3 단독 93.9%**·C3+C5 6.1% (PRESERVES 단일) |

E1 방향 일치(89.9→9.5%), E2 부분(선행 0·불변 58.5%), E3 수치 기록, **R1 발생(41.5%>20%)**,
R2 미발생(89.5% vs 39.0%).

**R1 재판정(전문가)**: 후행 이동 179행은 "옛 사이클 앵커 → 현 사이클 앵커" **교정**. C1∧C2
재성립 = Stage 1 재진입 = 새 Stage 2 시작. 책의 앵커는 "현재 상승의 시작"이므로 후행 앵커가
정답. → 채택.

## 3. Phase C — 변경(이것 하나만)

| 파일 | 변경 |
|---|---|
| `kr_pipeline/llm_runner/compute/climax_topping.py` | `find_anchor` 결합식에서 C4(`s30 > s30p and s40 > s40p`) 및 s30p/s40p 산출 제거. 모듈·함수 docstring 갱신 |
| `prompts/analyze_chart_v3.md` | §6.1 앵커 정의 서술("30/40-week lines turn up" → 동일 주 C1∧C2∧C3∧C5, 재진입 시 앵커 이동) 동기화 |
| `kr_pipeline/common/thresholds.py` | CLIMAX_ANCHOR_TURNUP_WEEKS **값·이름 불변**, docstring 만 "C2 lookback 전용, 구 C4 소비처 제거" 로 정정 |
| `tests/test_climax_topping.py` | +5: 재진입(179행 패턴)·무재진입(252행)·선행 이동 불가 단조 가드·C4 불성립 주 포착·3모드 회귀. `_sma` 로 C4 불성립을 픽스처 안에서 직접 확인 |

**Phase B 일치 확인**: 신규 코드 `find_anchor` 를 같은 4,252행에 재실행 → 모드 분포 anchored
3,848 / no_transition 404, 앵커 날짜·weeks_since **불일치 0행**(`scratchpad/phase_c_parity.py`).

## 4. 하류 영향

- anchor 의존 신호 전체(P1 maturity·P2·T1·T2·scope_active·T-A·T-D거래량·T5·T6·TA-d·tc_prolonged)가
  행의 ~80%에서 처음 산출됨(이전 no_transition: 주간은 전체 이력 극값, 일간은 None).
- `gates.py` §6.2 shadow: would_force 판정 입력은 g0/tb/td_dist(anchor 비의존) 뿐 → **판정
  무영향**. observe 필드 `tc_prolonged_ok`(anchored 전용 maturity≥18) 만 신규 anchored 행에서
  None→bool 로 채워짐(로그 관측치 변화, 발화 경로 없음).
- entry_params_calc 모순 검사·risk_flags 목록 불변.

## 5. 의존성 맵(2축 판정)

**1단계**: C1~C3·C5 상수(불변) → `anchor_week/weeks_since/no_transition` → P1·P2·T1·T2·scope·T-A·
T-D·T5·T6·TA-d·tc_prolonged.
**2단계**: `grep -rn "find_anchor\|anchor\[" kr_pipeline api` → climax_topping.py 3함수,
payload_builder(daily baseline 시작), gates.py observe. 프롬프트 §6.1/§6.2 앵커 정의 서술.

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| CLIMAX_ANCHOR_TURNUP_WEEKS=4 (C2 lookback, 구 C4 창) | 불가(시간) | **미미** — C2 는 불변, C4 소비처만 소멸. 값 변경 0 | EXTENDS | **모니터링** — 근거: 잔여 소비처 C2 의 산술·값 불변, 트리거 집합 변화는 C4 제거에서만 옴 |
| CLIMAX_MATURITY_WEEKS=18 (P1) | 불변 | **있음** — anchored 행 3,848 로 확대되어 P1 이 실판정됨(신규 89.5% 충족, 기존 no_transition 은 True 간주였음) | PRESERVES(HMMS p.263) | **사전등록 holdout** — B3 분포 기록 |
| CLIMAX_GAIN_PCT=25·P2 풀링 / T1·T2·T-A 극값 baseline | 불변 | **있음** — baseline 이 "전체 이력"→"현 사이클" 로 좁아져 극값 갱신 빈도 변화(B4 방향: P2·T2 ↑, T1 ↑, T-A ↑ vs 구 no_transition) | PRESERVES | **사전등록 holdout** — B4 기준선 첨부 |
| CLIMAX_SCOPE_*(고점 ≤2주·조정 ≤15%) | 불변 | **있음** — 고점 탐색 구간이 현 사이클로 축소 → scope_active True 가능 행 증가 | PRESERVES | 동일 holdout |
| BREAKOUT_VOL_FLOOR=1.4 (C3) | 가능(배수) | **있음** — B5: 잔여 no_transition 의 93.9% 가 C3 단독 차단 → Fix α 후 유일한 실효 게이트 | PRESERVES(HMMS Ch.2) | **관측 기록만**(아래 미해결) — 임계 변경 금지 |
| T5/T6/TA-d 연속 세션·adj_hl 규약 | 불변 | **없음** — 일간 baseline 시작이 anchor 주 월요일로 산출되는 행이 늘 뿐 규약 동일 | — | 없음 |
| gates.py §6.2 shadow would_force | 불변 | **없음**(anchor 비의존 입력) | — | 없음 |

**소비 경계 (1줄)**: `find_anchor → climax_topping_gates.* → analyze_chart_v3.md §6.1/§6.2 LLM 판정 →
weekly_classification.risk_flags(climax_run/topping_distribution → ignore)`. 하류 추적 안 함.

**게이트 점검**: 1 맵 ✓ 2 상수 행 ✓ 3 축1·축2 ✓ 4 영향 행 후속=holdout 예약·모니터링 행 근거 ✓ 5 경계 ✓

## 6. 사전등록(배포 전 기록)

1. 변경 성격: **book-fidelity 교정**. 성과 개선 목적 아님.
2. 기대 방향: §6.1 climax_run·§6.2 topping_distribution 발화 **증가**. 폭 미예측.
3. 사전 기준선 — Phase B B4 발화율(결정론 재계산, 저장본 4,252행):

   | 신호 | 기존 anchored 현행 앵커(431) | 구 no_transition 전체이력(3,821) | 신규 anchored Fix α(3,417) |
   |---|---|---|---|
   | P2 | 5.10% | 2.59% | 4.98% |
   | T1 | 3.48% | 4.08% | 7.67% |
   | T2 | 3.94% | 2.36% | 4.89% |
   | T-A | 2.78% | 0.08% | 1.90% |

   저장본 LLM 발화 기준선(#157 §5-3 과 동일 시점): weekly_classification climax_run 678 ·
   topping 27 (2,139행).
4. 성과 판정: 현 표본으로 하지 않음. P0 재수집 후 holdout 으로만.
5. 재실행 비교 금지. 배포 후 저장본 집계는 **1회 실행·저장**(anchor 모드별 분리 — #157 규약).

## 7. 미해결 관측(기록만 — 착수 금지)

- **#156** T1 주간 스프레드 절대값 편향.
- 주간 no_transition 전체-이력 관례 vs 일간 None(#157 Q-8) 병존 — Fix α 로 no_transition 이
  9.5% 로 줄어 노출 축소, 규약 자체는 미해소.
- **C3 의 주간 적용(1.4× 50주 평균)** 이 HMMS 의 일간 기준(돌파일 거래량 40~50%↑ vs 50일 평균)
  에 대응하는지 — B5 에서 잔여 차단의 93.9% 가 C3. 기록만.
- #155 규칙 전수조사에 **"책에 없는 조건이 책 신호를 차단한 사례" 3건째**로 표기(#151
  spread_wide_loose 와 같은 계열; 이슈 코멘트로 기록).
