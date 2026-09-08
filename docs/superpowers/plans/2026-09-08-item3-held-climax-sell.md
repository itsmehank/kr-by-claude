# 항목 ③ — 보유 종목 climax 강세 매도(백테스트·production 동시): 판정·결합식·의존성 맵·사전등록

> 트리거: thresholds.py 상수 **추가**(TRADE_HOLD_MIN_DAYS=56, 백테스트 리터럴 승격) + CLIMAX_*
> 소비처 신설(trade_management/held_climax.py·backtest/portfolio.py) — checklist (a) 사실 기준
> 해당 → §5 의존성 맵. 원칙 2-1(현 main G2) 적용. 신규 판정 숫자 **0**.

## 0. 판정(전문가, 2026-09-08)

- 종류 A(이익목표 절반매도 = 백테스트 5B): **이번 PR 범위 아님**. B 머지 후 별도 PR(플래그 OFF,
  백테스트 파리티) — #166(예고).
- 종류 B(climax 매도): **구현**. book-mandated(HMMS Ch.10 / TTLC Ch.9).

## 1. 결합식(결정론)

```
held_climax = P1(maturity_ok) ∧ P2(p2_accel_ok) ∧ (T1∨T2∨T3∨T4∨T5∨T6) ∧ scope_active ∧ ¬suppressed
suppressed  = (as_of − entry_date) < TRADE_HOLD_MIN_DAYS(56)
left_censored / no_transition / quality_flag → fired = None(미정의, 미발화)
null 트리거 = 미평가(#157 규약) — 나머지로만 OR
```
- suppressed 는 §6.1 **E1(리더십 배제)의 결정론 대용** — HMMS 8주 규칙 재사용
  [design-judgment: book 규칙의 대용 적용]. 백테스트 8주 면제(exempt_until)와 **같은 상수**.
- P1·P2·scope·T 임계 = 기존 CLIMAX_*(18주·25%·2주/15%·70%·7~15일) 전부 재사용.
- **LLM 전용이라 미적용되는 §6.1 판정(결측 목록)**: E1 base 서수 리더십 배제 · P1 후기 완화
  (3rd+ base → 12주) · supporting SMA200 ≥70% pass/fail(값은 코드, 판정은 프롬프트) · §6.2 T-C
  "prolonged advance". → 보유 climax 판정은 A 프롬프트 §6.1 보다 **좁다**(리더십 예외 없이 8주 억제로
  대체, 후기 완화 없음, supporting 미참여).

## 2. 변경 파일

| 파일 | 변경 |
|---|---|
| `kr_pipeline/common/thresholds.py` | +TRADE_HOLD_MIN_DAYS=56 [PRESERVES HMMS 8주] — 소비처 2(백테스트 면제·climax 억제) |
| `kr_pipeline/trade_management/held_climax.py` (신규) | `gates_from_series`(find_anchor·compute_climax_gates·compute_daily_extremes 재사용, build_payload 미호출) · `evaluate_held_climax`(순수 결합식) · `fetch_series`/`fetch_daily_flagged`(production 조회) · `slice_upto`(백테스트 절단) · `compute_held_climax` |
| `kr_pipeline/trade_management/runner.py` | ⑤ evaluate_stop 이후 **not triggered 분기**에 held_climax 판정 → `position_climax_evaluations` INSERT(멱등) → fired ∧ 신규 INSERT 시 `notify_sell_into_strength`. 스탑 triggered 면 미평가(스탑 우선). 산술 예외는 fail-soft 로그. 자동 청산 없음 |
| `kr_pipeline/db/schema.sql` | +`position_climax_evaluations`(position_id, eval_date PK; fired NULL 허용, suppressed, hold_days, triggers JSONB, anchor_week, weeks_since, maturity_ok, p2_accel_ok, scope_active, mode) — kr_pipeline·kr_test 적용 완료 |
| `kr_pipeline/llm_runner/slack.py` | +`notify_sell_into_strength`(전량 매도 권고, 트리거 목록·앵커·앵커 후 주·보유일) |
| `kr_pipeline/backtest/portfolio.py` | TickerData +weekly_full·daily_flagged(전 이력 적재), PortfolioConfig +climax_sell(기본 ON)·hold_min_days(SSOT), ① 스탑 블록 이후 미청산 포지션에 held_climax → reason=`climax` 전량 청산. 리터럴 56 → cfg.hold_min_days(2곳). sell_half OFF 그대로 |
| 테스트 `tests/test_trade_held_climax.py` (+17) | 결합식 각 항·null 트리거·8주 경계·3모드 None·production↔replay↔slice 일치·러너(발화 알림·멱등·스탑 우선·None 기록)·백테스트(reason=climax·억제·스탑 우선·climax_sell OFF·합성 데이터 미발화·5B OFF 불변). `test_trade_positions._cleanup` 에 FK 삭제 순서 추가 |

## 3. production ↔ backtest 파리티(구조)

판정 함수가 하나(`evaluate_held_climax(gates_from_series(weekly, daily), …)`)이고 입력 구성만
다르다: production = `_fetch_weekly_full(as_of)` + 일봉 전 이력(as_of 이하), backtest = 적재한
전 이력을 `slice_upto(as_of)` 로 절단. 테스트가 같은 시드에서 production·replay(payload_builder
개별 조회)·slice 세 경로의 §6.1 전 필드 일치를 고정한다.

**알려진 입력 차이(사실 기록)**: weekly_prices 는 production 에서 **당주 부분 주봉**(week_end =
오늘)이 존재하지만, 과거 구간(backtest)에는 완결 주만 있어 주중 as_of 에서 당주 행이 없다.
따라서 backtest 의 주간 극값(T1·T2·P2·scope)은 주중에는 직전 완결 주 기준이다. 판정 함수는
동일하며 입력 데이터 가용성의 차이다.

## 4. Phase A 요지(2026-09-08 회신)

- 백테스트 청산 규칙: stop8/floor/sma50_trail 전량 + 5B 절반매도(OFF) + 8주 면제 + 최약 교체(≤0%).
  이익목표 전량·climax·최대 하락일 매도 없음 → 본 PR 이 climax 만 신설.
- positions: entry_date·entry_price 만(전량 모델, pivot·entry_params 링크 없음 — #162).
- climax 산술 독립 호출 가능(replay 경로). LLM 결측 = §1 목록. 러너 Slack 조건은 스탑 1종뿐이었음.
- market_context 미참조(→ #165). A7: 표본 A+B 37 exits(stop8 23·sma50 11·floor 3), MFE 중앙값
  6.8% vs 실현 −8.4%, 반납 13.2pp — **근거로 쓰지 않음(n=37)**.

## 5. 의존성 맵(2축 판정)

**1단계**: TRADE_HOLD_MIN_DAYS → suppressed·exempt_until. CLIMAX_*(기존) → P1·P2·scope·T1~T6 →
`held_climax.fired`. **2단계**: runner(Slack·climax evaluations), portfolio ①(reason=climax).
결정론 소비 신설 2곳. A 프롬프트 §6.1 소비는 불변.

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| TRADE_HOLD_MIN_DAYS=56 (신설, 2소비처) | 불가(시간) | **있음** — 억제 경계: 시뮬 1,303 판정 중 P1∧P2∧scope∧T 성립 24건이 **전부 보유<56일**(억제) → 발화 0. 값 변경은 발화 집합을 직접 결정 | PRESERVES(HMMS 8주) / 대용 적용은 design | **B-수치** — 값 변경 금지, production 로그 누적 후 재검토(#165 와 별개) |
| CLIMAX_MATURITY_WEEKS=18 (P1) | 불변 | **있음(신규 소비처)** — 시뮬 anchored 판정의 P1 True 1,110/1,258 | PRESERVES | holdout(§6) |
| CLIMAX_GAIN_PCT=25·P2 풀링 | 불변 | **있음** — P2 True 37/1,258 = 가장 드문 항(결합의 병목) | PRESERVES | holdout |
| CLIMAX_SCOPE_*(≤2주·15%) | 불변 | **있음** — scope True 945/1,258 | PRESERVES | holdout |
| T1~T6 정의(#156·#157) | 불변 | **있음** — anyT 451/1,258(T4 358·T3 100·T2 77·T1 41·T6 8·T5 6) | PRESERVES/design | holdout |
| stop 스택(8%·본전·SMA50) | 불변 | **없음** — 스탑 우선, climax 는 not-triggered 분기 | PRESERVES | 없음 |
| 5B sell_half·21일 리터럴 | 불변(OFF) | **없음** | — | 없음 |
| find_anchor(#158 Fix α) | 불변 | 간접 — anchored 1,258/1,303(96.5%) | — | 없음 |

**소비 경계 (1줄)**: `held_climax.fired → (production) Slack 권고 + position_climax_evaluations /
(backtest) reason=climax 전량 청산`. 자동 청산 없음. 하류 추적 안 함.
**게이트 점검**: 1 맵 ✓ 2 상수 행 ✓ 3 축1·축2 ✓ 4 영향 행 후속(B-수치·holdout) ✓ 5 경계 ✓

## 6. 사전등록(배포 전 기록)

1. 변경 성격: **book-fidelity 보완**(HMMS Ch.10 / TTLC Ch.9 climax 매도). 성과 목적 아님.
2. production 영향: 현재 **0**(positions 0행). 실데이터 sanity(as_of 2026-09-04): 000660 anchored(앵커
   2025-01-10, +86주) fired False(P2·scope False), 005930 anchored(앵커 2020-06-05) suppressed(보유 15일) — 예외 없음.
3. 백테스트 기준선(배포 전, armA-prod 표본 A+B 200종목 2021~2025, climax_sell=OFF 로 재현):
   exits 37 = stop8 23 · sma50_trail 11 · floor 3, final_multiple 1.0185, CAGR 0.41%, MDD −26.87%,
   평균 노출 24.7%.
4. **배포 후 집계(climax_sell=ON, 같은 표본)**: exits 37, 사유 분포 **동일**, final_multiple
   **1.0185(불변)** — reason=climax 청산 **0건**. 진단: 1,303 판정(anchored 1,258·no_transition 45),
   P1∧P2∧scope∧T 동시 성립 24건이 전부 억제 기간(보유 < 56일) 안 → 발화 0. 관측만, 판정 아님.
5. 성과 판정: 없음. A7(반납 13.2pp 등)은 근거로 쓰지 않음(n=37). 재실행 비교 금지.

## 7. 기록만(착수 금지)

- **#164** 보유 종목 약세 매도 신호(TA-d/T-A) — stop 스택과 별개. TTLC Ch.9.
- **#165** 시장 국면에 따른 강세매도/트레일 전환 — 규칙에 숫자 필요.
- **#166** (예고) 5B production 이식 — B 머지 후 별도 지시.

## 8. 머지 후 관측 — 억제 24회 판정의 후속(2026-09-08, 전문가 지시; 관측만, 56일 조정 금지)

24회 억제 판정은 **포지션 3개**에 집중(각 10·9·5회 연속). 포지션별 첫 억제 판정 기준:

| 종목 | t1 | 첫 판정(보유일) | 판정일 미실현 | 트리거 | 청산 | 실현 | 판정 후 MFE | 반납(MFE_after−실현) |
|---|---|---|---|---|---|---|---|---|
| 161580 | 2023-06-21 | 07-07 (+16d) | +36.0% | T2·T4 | 07-24 sma50_trail | +8.6% | +105.8% | 97.2pp |
| 036460 | 2024-06-11 | 06-12 (+1d) | +4.1% | T1·T2·T4 | 07-12 floor | −2.0% | +44.3% | 46.3pp |
| 001750 | 2024-07-10 | 07-19 (+9d) | +35.9% | T2·T4 | 09-23 sma50_trail | +26.1% | +56.8% | 30.7pp |

중앙값(포지션 3): 첫 판정 보유 9일, 판정일 미실현 +35.9%, 실현 +8.6%, 판정 후 MFE +56.8%,
반납 46.4pp, 실현 − 판정일 미실현 = −9.8pp(전 3건 음수: −6.1 / −27.5 / −9.8), 판정→청산 30일.
용도 = "E1 대체(8주 억제)가 과잉 억제인가"의 **가설 생성**. n=3 포지션. 판정 아님, 56일 값 조정은
별도 사전등록 대상.
