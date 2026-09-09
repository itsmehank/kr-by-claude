# #166 — 이익목표 절반매도(5B) production 이식(플래그 OFF): 파리티·SSOT·의존성 맵·사전등록

> 트리거: thresholds.py 상수 **추가**(SELL_HALF_ENABLED·EARLY_GAIN_DAYS·SELL_HALF_GAIN_PCT — backtest
> 리터럴 승격) + 소비처 신설(trade_management/sell_half.py·runner) + backtest 5B 산술을 공용 함수로 교체
> — checklist (a) 사실 기준 해당 → §4 의존성 맵. 동작 변화 **0**(OFF, 백테스트 결과 불변 확인).

## 0. 판정(전문가, 2026-09-08)

종류 A. **book-permitted**(의무 아님): HMMS 20~25% 일부 실현 + 1~3주 예외 + 8주 규칙 / TTLC 절반매도.
프로젝트가 측정("꼬리 절단 비용" — CAGR 반토막↔MDD 개선, trading-rules-book-verified §3)으로 **OFF
선택 — 유지**. 이번은 파리티 이식만. **ON 전환은 별도 사전등록 대상이며 결정문에 그 측정을 알고 켜는
것임을 명기해야 한다.**

## 1. 로직(백테스트 5B 그대로 — `trade_management/sell_half.py` 순수 함수)

```
+20%(SELL_HALF_GAIN_PCT) 최초 도달일 t:
  (t − entry_date) > EARLY_GAIN_DAYS(21) → 즉시 절반매도 권고 [immediate]
  ≤ 21 → half_pending: entry + TRADE_HOLD_MIN_DAYS(56) 후 첫 평가일(> 56)에
         close ≥ entry×(1+0.20) 이면 권고 [week8], 미만이면 소멸(half_expired)
발화 = 포지션당 1회. production 은 권고만(수량 변경 없음 — 전량 모델, 손절 계산 수량 비참조).
```
hit20_date 는 플래그와 무관하게 갱신(백테스트 8주 면제 판정 입력). 절반매도 집행/대기/소멸 상태 반영은
플래그 ON 일 때만.

## 2. 상수 SSOT

| 상수 | 값 | 태그 | 비고 |
|---|---|---|---|
| SELL_HALF_ENABLED | False | 플래그 | backtest `PortfolioConfig.sell_half` 기본값 + production runner 참조 — **한쪽만 ON 불가**(단일 출처). 연구 스크립트의 명시 override 는 시나리오 비교 전용 |
| EARLY_GAIN_DAYS | 21 | B (HMMS "1~3주" 상한) | 구 backtest 리터럴 21 승격 |
| SELL_HALF_GAIN_PCT | 0.20 | B 범위 20~25% / D: 20 선택 | 구 리터럴 1.20 승격. TRADE_BREAKEVEN_TRIGGER_PCT·armed_gain_cap(0.20)과 값 동일하나 역할 상이 — **별도 상수, 결합 금지** |
| TRADE_HOLD_MIN_DAYS | 56 | 기존(#167 공유) | 8주차 재판정 |

## 3. 변경 파일

| 파일 | 변경 |
|---|---|
| `kr_pipeline/common/thresholds.py` | +SELL_HALF_ENABLED·EARLY_GAIN_DAYS·SELL_HALF_GAIN_PCT |
| `kr_pipeline/trade_management/sell_half.py` (신규) | `SellHalfState`·`SellHalfDecision`·`evaluate_sell_half` — backtest·production 공용 |
| `kr_pipeline/backtest/portfolio.py` | ① 블록의 hit20/면제/5B 인라인 로직 → `evaluate_sell_half` 호출로 교체(리터럴 21·1.20 제거), `sell_half` 기본값 = SELL_HALF_ENABLED |
| `kr_pipeline/trade_management/runner.py` | 스탑 미발화 ∧ climax 미발화 분기에서만 5B 평가(우선순위 스탑 > climax > 절반매도). 플래그 OFF 면 블록 진입 없음. 상태 영속(`update_sell_half_state`, half_fired_at 최초 1회만 = 멱등) + `notify_sell_half` |
| `kr_pipeline/db/schema.sql` | positions +hit20_date·half_pending·half_fired_at·half_expired(ALTER IF NOT EXISTS, 양 DB 적용) |
| `kr_pipeline/trade_management/store.py` | get_open_positions 에 5B 상태 4컬럼, `update_sell_half_state` |
| `kr_pipeline/llm_runner/slack.py` | +`notify_sell_half`(절반 매도 권고, 도달일·경과일·근거) |
| `tests/test_trade_sell_half.py` (+11) | 플래그 기본 OFF·21일 경계(21 포함 → pending, 22 → immediate)·56일 대기/소멸(56 당일 미판정, 57 판정)·포지션당 1회·러너 OFF 미동작/ON 발화·멱등·pending→week8·우선순위(climax 발화일 5B 미평가)·백테스트 공용 함수(immediate·week8·소멸·OFF) |

## 4. 의존성 맵(2축 판정)

**1단계**: SELL_HALF_ENABLED → 블록 진입 여부. EARLY_GAIN_DAYS·SELL_HALF_GAIN_PCT·TRADE_HOLD_MIN_DAYS →
`evaluate_sell_half.fire/half_pending/half_expired` + hit20_date(→ backtest exempt_until).
**2단계**: backtest portfolio ①(절반 매도·8주 면제), runner(권고 Slack·positions 상태). 결정론 소비 2곳.

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| SELL_HALF_ENABLED=False | — | **없음(현재)** — OFF. ON 시 backtest 실측: final 1.0185→0.9448, MDD −26.87→−24.05, 절반매도 4건(표본 A+B) | 플래그 | ON 전환 = **별도 사전등록**(꼬리 절단 비용 명기) |
| EARLY_GAIN_DAYS=21 | 불가(시간) | **있음(ON 시)** — immediate/pending 분기 경계. OFF 에서도 hit20 내 within 판정이 backtest 8주 면제(exempt_until)를 결정 → 값 변경은 교체 규칙에 영향 | B(HMMS 1~3주) | **B-수치** — 값 변경 금지, 백테스트 결과 불변 확인으로 승격 검증 |
| SELL_HALF_GAIN_PCT=0.20 | 가능(비율) | **있음(ON 시)** / OFF 에서는 hit20_date(면제)만 | B/D | B-수치. TRADE_BREAKEVEN_TRIGGER_PCT 와 결합 금지 |
| TRADE_HOLD_MIN_DAYS=56 | 불가 | **있음** — 3소비처(면제·climax 억제·5B 8주차) | PRESERVES | #167 맵 유지 |
| stop 스택·held_climax | 불변 | **없음** — 우선순위 상위, 5B 는 둘 다 미발화일 때만 | — | 없음 |

**소비 경계 (1줄)**: `evaluate_sell_half → (backtest) _sell_half 절반 집행 / (production, ON 시) Slack
권고 + positions 5B 상태`. 자동 매도 없음. 하류 추적 안 함.
**게이트 점검**: 1 맵 ✓ 2 상수 행 ✓ 3 축1·축2 ✓ 4 영향 행 후속 ✓ 5 경계 ✓

## 5. 백테스트 불변 확인(리터럴 → 상수 + 공용 함수, armA-prod 표본 A+B 200종목)

| | exits | 사유 | 절반매도 | final_multiple | CAGR | MDD | 노출 |
|---|---|---|---|---|---|---|---|
| OFF(기본) | 37 | stop8 23 · sma50 11 · floor 3 | 0 | 1.0185 | 0.41% | −26.87% | 24.7% |
| ON(override) | 37 | 동일 | 4 | 0.9448 | −1.26% | −24.05% | 19.5% |

두 팔 모두 항목 ③ 시점 실측과 **동일**(OFF 1.0185 / ON 0.9448·절반매도 4). frozen·portfolio 테스트 통과.

## 6. 사전등록

- 변경 성격: **파리티 이식**. 동작 변화 0(OFF).
- production 영향 0(positions 0행·플래그 OFF). 성과 판정 없음. 재실행 비교 금지.
- ON 전환은 별도 사전등록 — 결정문에 "꼬리 절단 비용" 측정(§5 ON 행)을 알고 켜는 것임을 명기.

## 7. 종결

#166 머지로 항목 ①②③ 종결 → **#155 착수 조건 (a) 도달**. 착수는 지시 대기.
