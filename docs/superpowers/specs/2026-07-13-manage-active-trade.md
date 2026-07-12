# manage_active_trade 사전등록 스펙 — 3층 손절 스택 이식 (#3 이슈4)

> 상태: **사전등록** (2026-07-13). 코어 결정론 모듈(stop_stack)은 본 스펙과 함께 구현·검증.
> 파이프라인 wiring(포지션 소스·실행 단계)은 실전 전환 결정 후 별도 착수 — 아래 §5.

## 1. 배경 (이슈 #3 이슈4 — 공백)

파이프라인(disqualify → 분류 → evaluate_pivot → entry_params → performance)에
"산 다음 언제 팔지"를 판단하는 단계가 없다. `prompts/calculate_entry_params_v2_0.md:36`
은 "별도 manage_active_trade 함수의 일"이라 선언만 하고, 실구현은 저장소 전체 0건
(설계 초기부터 의도적 보류 — specs/2026-05-17-llm-runner-design.md).
백테스트 시리즈(2026-07-02~07)가 책 원문 근거로 검증한 **3층 손절 스택**이 대체
설계로 확정돼 있다 (`docs/trading-rules-book-verified.md` §2, 시뮬 구현
`kr_pipeline/backtest/portfolio.py`·`stop_variant_sim.py`).

## 2. 코어 규칙 — 3층 손절 스택 (본 스펙에서 이식)

매 거래일, 아래 세 후보 중 **최댓값**이 그날의 유효 손절선:

1. **initial_stop**: 평균매입가 × (1 − 8%) — 상시. (O'Neil HMMS "7% to 8% is your
   absolute loss limit"; 절대 상한 10% = uncle point, Minervini TLSMW Ch.13)
2. **breakeven**: 종가가 평균매입가 × (1 + 20%) 에 **한 번이라도** 도달하면 이후
   상시 평균매입가가 바닥 (래치 — 해제 없음).
3. **sma50_trail**: 50일 이동평균선이 위 값들보다 높으면 그 값. (max() 가
   "더 높을 때만 교체"를 구현 — 시뮬과 동일)

종가 < 유효 손절선 → 매도 신호(triggered). binding = 세 후보 중 최댓값의 라벨.

구현: `kr_pipeline/trade_management/stop_stack.py` — 순수 함수(상태는 호출자가
`breakeven_armed` bool 로 운반), 백테스트 시뮬(stop_variant_sim._run 루프)과 동일
의미론. SSOT: `TRADE_STOP_INITIAL_PCT=0.08`, `TRADE_BREAKEVEN_TRIGGER_PCT=0.20`,
`TRADE_STOP_MAX_PCT=0.10`(uncle point — initial_stop_pct 인자 상한 검증).

## 3. 불변 계약 (구현·wiring 공통)

- **anchor 는 매수 시점 값으로 고정** — 평균매입가는 체결 사실. 보유 중 주간
  재분류가 갱신하는 새 pivot/base_low 를 손절 계산에 유입 금지
  (#1 pivot 재판독 ±22% 실측·docs/pivot-reanalysis-tradeoff.md — 매수가 anchor 는
  재판독과 자연 절연. 시뮬 구현들도 진입 시점 고정 방식).
- **[D4 체크리스트] `load.py get_active_with_current` 의 `stop_loss = base_low`
  정의를 재사용 금지** — 그것은 워치리스트 재검토 트리거용이며 무클램프 구조적
  스톱(실측 pivot 대비 −37.7% 사례)이라 포지션 손절로 쓰면 대형 미실현손실 방치.
- abort 자가리셋(evaluate_pivot._aborted_since_classification 의 classified_at
  매칭)은 **진입 전** 단계 장치 — 보유 포지션 관리와 무관하게 유지. 포지션 관리는
  분류 테이블 상태와 독립적으로 동작해야 한다(재분류가 손절 상태를 리셋하면 안 됨).
- 단순 abort 모델(B v3 결정)과 정합 — 부분 청산·피라미딩은 범위 외(전량 매도 신호만).

## 4. 코어 모듈 인터페이스

```python
evaluate_stop(*, entry_price, close, sma_50, breakeven_armed,
              initial_stop_pct=TRADE_STOP_INITIAL_PCT) -> StopDecision
# StopDecision: effective_stop, binding('initial_stop'|'breakeven'|'sma50_trail'),
#               breakeven_armed(갱신된 래치), triggered(close < effective_stop)
```

- 래치 갱신은 당일 종가로 먼저 판정 후 후보에 반영 (시뮬 순서와 동일 — 당일
  +20% 도달 시 당일부터 본전 바닥).
- sma_50 None(미산출) → 후보에서 제외 (시뮬과 동일).
- initial_stop_pct > TRADE_STOP_MAX_PCT → ValueError (uncle point 위반 차단).

## 5. Wiring (본 스펙 범위 외 — 실전 전환 결정 후)

포지션 소스(브로커 연동/수동 입력 테이블)가 아직 없다. 실전 전환 논의 시:
positions 테이블 스키마 + 일일 평가 러너(evaluate_stop 호출) + 신호 노출(웹/알림)
을 별도 사전등록으로. 그때 이 스펙 §3 계약을 승계 체크리스트로 사용.

## 6. 임계 의존성 맵 (2축 판정)

**1단계**: 신규 상수 3종 → StopDecision(effective_stop/triggered).
**2단계**: 소비 룰 = evaluate_stop 단일 (파이프라인 소비처는 §5 wiring 전까지 없음 — 백테스트 시뮬은 자체 상수 유지, 본 이식은 additive).
**3단계 — 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| TRADE_STOP_INITIAL_PCT=0.08 | 가능(%) | 있음 — 손절 후보 1층 | PRESERVES (O'Neil 7~8% — 상단 채택) | 임계와 함께 보정(변경 시 백테스트 재검증 — stop_variant 시뮬 재사용) |
| TRADE_BREAKEVEN_TRIGGER_PCT=0.20 | 가능(%) | 있음 — 2층 래치 발동점 | PRESERVES (O'Neil 20-25% 표준 익절 구간의 하한 — TLSMW/HMMS) | 임계와 함께 보정(동일) |
| TRADE_STOP_MAX_PCT=0.10 | 가능(%) | 있음 — 인자 상한 검증(fail-closed) | PRESERVES (uncle point 10% — HMMS/TLSMW) | 변경 금지 수준의 책 앵커 |

**소비 경계 (1줄)**: StopDecision → (§5 wiring 후) 매도 신호 러너 → 사용자 노출 — 현재는 소비처 없음(additive 모듈).

## 7. 보류 결정 기록 (이슈 #3 의 나머지)

- **D2 (이슈1 — 손절 anchor pivot→매수가 정합화)**: 본 스펙(이슈4) 완료 후 별도
  사전등록 — SSOT 클램프 재정의 + threshold-change-checklist 필수. 이 스펙의
  §3 "매수가 anchor 고정"이 선행 정합 논거.
- **D3 (이슈2 — 사이징 리스크 역산 전환)**: 이슈4 완료 후 별도 사전등록 —
  §3.1~3.3 티어 구조 재설계 수반. 책 기준: 계좌 리스크 1.25%/건 ÷ 손절폭 역산.
- **D4 (이슈3 — base_low 재사용 금지)**: §3 체크리스트로 본 스펙에 반영 완료.
