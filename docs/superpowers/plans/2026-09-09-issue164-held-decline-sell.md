> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #164 — 보유 종목 약세 매도 신호(백테스트·production 동시): 판정·결합식·의존성 맵·측정·사전등록

> 트리거: CLIMAX_*·TOPPING_* 소비처 신설(trade_management/held_decline.py·backtest/portfolio.py
> decline 블록) — checklist (a) 사실 기준 해당(governance 2-1). thresholds.py 변경 **0**, 신규 판정
> 숫자 **0**.

## 0. 판정(전문가, 2026-09-09)

- **book-mandated** — TTLC Ch.9(최대 하락일 매도) / TLSMW Ch.5 / HMMS Ch.10 p.268 #2(최대 주간 하락).
  항목 ③(#167) 구조 재사용, 결합식만 추가.
- 변경 성격: book-fidelity 보완(governance 3-5). 성과 목적 아님.

## 1. 결합식(결정론, 신규 숫자 0)

```
held_decline = P1(maturity_ok) ∧ (T-A ta_max_decline_now ∨ TA-d ta_d_daily_max_decline_now)
left_censored / no_transition / quality_flag → fired = None(미정의, 미발화 — #169 동조)
null 신호 = 미평가(#157 규약) — 나머지로만 OR. 둘 다 미평가면 False
```
- **P1 재사용 사유**: baseline 부재 시 첫 하락이 자동 최대 — "상승 이래"는 확립된 상승 전제
  [design-judgment, 기록]. 채택 확정(변형 측정은 §3-3 기록만).
- **8주 억제 미적용**: 하락 신호에 리더십 예외 없음(Minervini "실적 직후라도") [book-mandated].
- **G0 미적용**: 책 전제 아님 — 신호 취지가 "선 위에서도 나가라".
- **우선순위**: 스탑 > 약세(decline) > 강세(climax) > 절반매도(5B). 같은 날 복수 성립 시 reason
  라벨은 앞선 것, 나머지는 기록에 병기(production `climax_also_fired`, backtest `exits[].also`).

## 2. 변경 파일

| 파일 | 변경 |
|---|---|
| `kr_pipeline/trade_management/held_decline.py` (신규) | `evaluate_held_decline`(순수 결합식) · `HeldDeclineDecision` · `decline_metrics`(Slack echo 전용 — 당일/당주 하락률·baseline 최대, 판정 비관여) · `compute_held_decline` |
| `kr_pipeline/trade_management/held_climax.py` | `gates_from_series` 에 §6.2 `ta_max_decline_now` 추가(compute_topping_gates 그 키만, 분배일 입력 None) + `compute_held_gates`(조회 1회) |
| `kr_pipeline/trade_management/runner.py` | not-triggered 분기: gates 1회 조회 → decline 평가·기록(`position_decline_evaluations`, 멱등) → 발화 시 `notify_sell_on_weakness` 후 climax 알림·5B 생략(climax 는 기록만) → 미발화 시 기존 climax 경로. 반환 +`decline_fired` |
| `kr_pipeline/llm_runner/slack.py` | +`notify_sell_on_weakness`(전량 매도 권고, 신호·당일 하락률/baseline 최대·당주 하락률/baseline 최대·앵커·경과 주·보유일·climax 병기) |
| `kr_pipeline/db/schema.sql` | +`position_decline_evaluations`(position_id, eval_date PK; fired NULL 허용, hold_days, signals JSONB, anchor_week, weeks_since, maturity_ok, ta_max_decline_now, ta_d_daily_max_decline_now, mode, climax_also_fired) — kr_pipeline·kr_test 적용 완료(운영 규칙 4) |
| `kr_pipeline/backtest/portfolio.py` | PortfolioConfig +`decline_sell`(기본 ON), ① 스탑 이후·climax 이전 decline 평가(같은 gates 1회) → reason=`decline` 전량 청산, 동시 성립 시 `also=["climax"]`. `_full_exit(also=)`·exits +`also` |
| 테스트 `tests/test_trade_held_decline.py` (+21) | 결합식(신호별·무신호·P1 미충족·억제 없음·null 미평가·P2/scope/G0 비관여)·3모드 None·gates_from_series T-A 파리티·left_censored·echo 정합·러너(발화 알림+climax 병기·스탑 우선·decline 침묵 시 climax 알림)·백테스트(8주 내 reason=decline·동시 성립 also·스탑 우선·합성 미발화·OFF)·production/backtest 동일 함수 |
| 기존 테스트 | 러너 mock 을 `compute_held_gates` 로 교체(held_climax·sell_half), FK 정리 순서에 decline 테이블 추가(positions·sell_half·held_climax) |

## 3. 측정(armA-prod 표본 A+B 200종목 2021~2025 — 관측만, 판정 아님)

§3-1 배포 전 기준선(decline_sell OFF = ③ 상태) / §3-2 배포 후(decline_sell ON 기본) / §3-3 변형(P1
제거, 기록만 — 채택은 P1 적용으로 이미 결정). 수치는 PR 회신·본 절에 동일 기록.

| 실행 | exits | 사유 분포 | final_multiple | CAGR | MDD | 평균 노출 |
|---|---|---|---|---|---|---|
| §3-1 기준선(decline OFF) | 37 | stop8 23 · sma50_trail 11 · floor 3 | 1.0185 | 0.41% | −26.87% | 24.7% |
| §3-2 배포 후(decline ON) | 37 | stop8 19 · **decline 11** · sma50_trail 5 · floor 2 | 1.1676 | 3.52% | −18.96% | 17.9% |
| §3-3 변형(P1 제거, 기록만) | 38 | stop8 15 · decline 18 · sma50_trail 4 · floor 1 | 1.2015 | 4.18% | −18.97% | 16.3% |

기준선은 항목 ③ §6-3·#169 §5 와 **동일 값**(decline OFF = ③ 상태 재현). 5B OFF 불변(n_half_sells 0).

§3-2 판정 진단(래핑 집계, 판정 함수 불변): 997 판정(anchored 952 · no_transition 45) · P1 True 804 ·
T-A True 41 · TA-d True 10(None 0) · 신호 ≥1 50 · **발화 11** · 신호 있으나 P1 False 39. decline 11건의
보유일: 1·3·7·9·17·22·23·28·38·78·548일 — 56일 미만 9건(억제 없음의 실효), 최장 548일(016710 +199.17%).
같은 날 climax 동시 성립(also) 0건. pnl: 음 5건(−3~−8%) · 양 6건(+0.3~+199%).

§3-3 변형(P1 제거 — 가설 생성용, 채택 아님): 895 판정 · 발화 18 · **그중 P1 미충족 7** = 배포본 11건
대비 추가 7건 전부가 P1 미충족 건(P1 재사용의 실효). 추가 7건의 pnl: −3.0 · −4.6 · −4.1 · +6.2 · −7.2 ·
−3.1 · −4.5%. 기록만 — 임계·결합식 조정 근거로 쓰지 않음(governance 3-3).

⚠ 성과 변동(1.0185 → 1.1676)은 **관측**이며 판정이 아니다(3-3). n=37 표본, holdout 사전등록 전 —
성과 근거로 인용 금지(3-2). 원자료: 스크래치패드 `measure_164.py`·`measure_164.json`.

production 영향: 현재 **0**(positions 0행).

## 4. 의존성 맵(2축 판정)

**1단계**: CLIMAX_MATURITY_WEEKS(P1) · T-A/TA-d 정의(#157·#159·#169, 분모 prev_close·동률 ≥·연속 세션)
→ `held_decline.fired`. **2단계**: runner(Slack·decline evaluations), portfolio ①(reason=decline).
결정론 소비 신설 2곳. A 프롬프트 §6.2 소비 불변.

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| CLIMAX_MATURITY_WEEKS=18 (P1 재사용) | 불변 | **있음(신규 소비처)** — P1 이 decline 발화 집합을 직접 결정(§3-3 변형 대비) | PRESERVES(HMMS p.263) / 재사용은 design | **관측 기록만** — 값 변경 금지, holdout(§5) |
| T-A 정의(주간 최대 하락, anchor 주 포함 baseline) | 불변 | **있음** — 신규 소비 | PRESERVES(HMMS p.268 #2) | holdout |
| TA-d 정의(#157 Q-2·Q-6·Q-7) | 불변 | **있음** — 신규 소비 | PRESERVES(TTLC Ch.9) | holdout |
| TRADE_HOLD_MIN_DAYS=56 | 불변 | **없음** — decline 은 억제 미적용(book-mandated) | — | 없음 |
| CLIMAX_GAIN_PCT·SCOPE·T1~T6 (climax) | 불변 | **없음** — decline 결합식 비참여. 단 우선순위로 같은 날 climax 라벨이 decline 로 바뀔 수 있음(병기) | — | 없음 |
| stop 스택(8%·본전·SMA50) | 불변 | **없음** — 스탑 우선 | PRESERVES | 없음 |
| find_anchor(#159)·no_transition(#169) | 불변 | 간접 — 3모드 None | — | 없음 |

**소비 경계 (1줄)**: `held_decline.fired → (production) Slack 권고 + position_decline_evaluations /
(backtest) reason=decline 전량 청산`. 자동 청산 없음. 하류 추적 안 함.
**게이트 점검**: 1 맵 ✓ 2 상수 행 ✓ 3 축1·축2 ✓ 4 영향 행 후속(holdout·관측) ✓ 5 경계 ✓

## 5. 사전등록(배포 전 기록)

1. 변경 성격: **book-fidelity 보완**(governance 3-5). 성과 목적 아님.
2. 기대 방향: 백테스트 exits 에 reason=decline **신설**, 결과 변동 방향 **미예측**.
3. 사전 기준선: §3-1(= 항목 ③ §6-3·#169 §5 와 동일 값).
4. 성과 판정: P0 재수집 후 **holdout 으로만**(governance 3-2). 재실행 비교 금지(3-1). §3 수치는
   관측 라벨(3-3).
5. 결측 처리: governance 4-2(null = 보수, 3모드 None).
6. 변형(P1 제거) 측정은 가설 생성용 기록 — 임계·결합식 조정 근거로 쓰지 않음(3-3).

## 6. 기록만(착수 금지)

- **#165** 시장 국면에 따른 강세매도/트레일 전환 — 규칙에 숫자 필요.
- decline 발화 후 재진입·재분류 상호작용은 미정의(전량 모델, 수동 체결).
