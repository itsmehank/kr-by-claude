> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #169 — no_transition 주간 anchor 의존 신호 null 전환: 판정·변경·의존성 맵·측정·사전등록

> 트리거: `climax_topping.py`(CLIMAX_*·TOPPING_* 소비처) 의 no_transition 분기 산술 변경 +
> `analyze_chart_v3.md` §6.1/§6.2 결측 모드 서술 변경 — checklist (a) 사실 기준 해당(governance
> 2-1: 값 변경 0 은 맵 생략 사유 아님). thresholds.py 변경 **0**.

## 0. 판정(전문가, 2026-09-09)

- 책 정의("상승 시작 이래" — HMMS Ch.10 / TTLC Ch.9 "since the beginning of the move")는 앵커
  부재 시 **미정의**. #157 Q-8 일간판 판정(T5/T6/TA-d → None)을 주간판에 일관 적용.
- 구 #44 규약(D1 부속: no_transition → P1 충족 간주 + 극값은 전체 이력 기준) **폐기**.
  governance 1-1 4조건: (a) 전체 이력 대체는 책에 없는 대용 (b) 커버리지 손실 없음 — 신호
  자체가 미정의 (c) 책 정의와 방향 충돌 (d) null 처리 경로(left_censored) 기존 존재. 충족.
  원문은 1-2 에 따라 보존(plans/2026-07-20-issue44 D1 부속에 superseded 표기).
- 변경 성격: **book-fidelity 정합**(일간·주간 통일, governance 3-5). 성과 목적 아님.

## 1. 변경(이것 하나만)

| 파일 | 변경 |
|---|---|
| `kr_pipeline/llm_runner/compute/climax_topping.py` | `compute_climax_gates`: no_transition → `maturity_weeks`·`maturity_ok`(현 True 간주 폐기)·`p2_*`·`t1_max_spread_now`·`t2_max_volume_now`·`scope_active` 전부 None. `compute_topping_gates`: no_transition → `ta_max_decline_now`·`td_max_down_volume_now` None(`tc_prolonged_ok` 는 기존 None). anchor 비의존(T3·T4·G0·T-B·T-C·`td_dist_ok`) 불변. `find_anchor` 불변. `baseline="no_transition"` 모드 기록 유지 |
| `api/services/payload_builder.py` | 주석 1줄(관례 병존 문구 제거). 코드 경로 변경 0 |
| `prompts/analyze_chart_v3.md` | **행 A** §6.1·§6.2 no_transition 항목: "전체 이력 baseline" → "anchor 의존 필드 null, 나머지로만 판정(left_censored 와 동일)". **행 B** 상단 SSOT 자기 선언 1줄(HTML 주석, governance 4-6 — PR #170 Q-2(B) 이행). 두 행 모두 **분류 변동 귀속 후보** |
| `tests/test_climax_topping.py` | 구 P1 간주 테스트 교체 → anchor 의존 None / anchor 비의존 유지 / left_censored 와 동일 출력(§6.1·§6.2) 3건, T1 3모드 회귀·topping 픽스처 갱신 |
| `tests/test_climax_payload.py` | no_transition payload 테스트: 주간도 None·anchor 비의존 유지 |
| `tests/test_trade_held_climax.py` | +1 no_transition 실제 산술 경로(gates_from_series) 미발화 |
| `tests/test_climax_daily_prompt_sync.py` | grep 가드 갱신(구 규약 문구 잔존 금지 + 상단 SSOT 선언) |

**하류 자동 전파(별도 코드 변경 0 확인)**: `held_climax.gates_from_series` → 같은 순수 함수.
`evaluate_held_climax` 는 이미 mode≠anchored 에서 fired=None(항목 ③ 설계) 이라 동작 불변.
백테스트(`portfolio.py` climax_sell) 도 같은 경로. `gates.py` observe(`tc_prolonged_ok`) 불변.
`payload_builder` 일간 경로는 #157 부터 no_transition 조회 생략 — 불변.

`evaluate_pivot_trigger_v1.md` 의 SSOT 자기 선언은 본 PR 범위 밖(프롬프트 미수정 — governance
4-6 이연 기록 유지).

## 2. 의존성 맵(2축 판정)

**1단계**: CLIMAX_*/TOPPING_* 상수(불변) → `find_anchor` 3모드(불변) → **no_transition 분기의
P1·P2·T1·T2·scope·T-A·T-D거래량**(값 → None). **2단계**: `grep -rn "compute_climax_gates\|
compute_topping_gates\|no_transition" kr_pipeline api scripts` → payload_builder(§6 payload),
held_climax(③ 매도), portfolio 백테스트(③ 경유), stage3 replay 스크립트(검증용), gates.py observe.

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| CLIMAX_MATURITY_WEEKS=18 (P1) | 불변 | **있음** — no_transition 404행에서 True 간주 → None. §6.1 결합식 발화 불가(구 후보 9행 소멸) | PRESERVES(HMMS p.263, 기산일 필요) | **사전등록 holdout**(§4) |
| CLIMAX_GAIN_PCT=25·P2 풀링 / T1·T2·T-A 극값 baseline | 불변 | **있음** — 전체-이력 baseline 소멸(P2 18·T1 10·T2 7·T-A 0·T-D거래량 4 발화 행 → None) | PRESERVES | 동일 holdout |
| CLIMAX_SCOPE_* | 불변 | **있음** — scope_active True 149행 → None(P1·P2 와 함께 결합식 불가) | PRESERVES | 동일 holdout |
| TOPPING_BELOW_10W_WEEKS=8·STOCK_DISTRIBUTION_COUNT_25D=4 (G0·T-B·T-D분배일) | 불변 | **없음** — anchor 비의존, 산술 동일. §6.2 발화 3행 전부 T-B/분배일 경유라 T-A/T-D거래량 제거로 잃는 행 0 | PRESERVES | 없음 |
| CLIMAX_UP_DAYS_*(T4)·T3 | 불변 | **없음** — daily 입력만, 계산 유지(결합식은 P1·P2·scope None 으로 불가) | PRESERVES | 없음 |
| BREAKOUT_VOL_FLOOR=1.4 (C3) | 가능(배수) | **없음**(find_anchor 불변) — 잔여 404행 차단 사유 재확인만(§3) | PRESERVES | **관측 기록만** — 임계 변경 금지(#158 §7 계승 → **#184**, 2026-09-11 이관) |
| TRADE_HOLD_MIN_DAYS=56·held_climax 결합식 | 불변 | **없음** — mode≠anchored 는 이미 fired=None | — | 백테스트 불변 확인(§5) |

**소비 경계 (1줄)**: `find_anchor → compute_*_gates → payload climax_topping_gates → analyze_chart_v3
§6.1/§6.2 LLM 판정 → weekly_classification.risk_flags` / `→ held_climax.fired → 권고·백테스트 청산`.
하류 추적 안 함.

**게이트 점검**: 1 맵 ✓ 2 상수 행 ✓ 3 축1·축2 ✓ 4 영향 행 후속=holdout·관측 근거 ✓ 5 경계 ✓

## 3. 측정(저장본 4,252행 결정론 재계산, #159 앵커 — 판정 아님)

모드: anchored 3,848 / no_transition **404**(#158 B1 과 일치). 변경 전 = main 모듈 사본, 변경 후 =
본 브랜치. production DB read-only. LLM 호출 0.

| 항목 | 값 |
|---|---|
| 변경 전 발화 행(no_transition 404, 전체 이력 기준) | P1 간주 404 · P2 18 · T1 10 · T2 7 · scope 149 · T-A 0 · T-D거래량 4 |
| 변경 전 §6.1 결합식 후보(P1∧P2∧T∧scope, E1 미고려) | **9행** |
| 변경 후 §6.1 결합식 | **404행 전부 발화 불가**(P1·P2·scope None) — 구 후보 9행 소멸 |
| 변경 전 §6.2 G0∧(T-A∨T-B∨T-D거래량∨분배일) | 3행 |
| 변경 후 §6.2 G0∧(T-B∨분배일) | **3행(동일)** — T-A/T-D거래량만으로 발화하던 행 **0** |
| 잔여 no_transition 차단 사유(C1∧C2 후보 주 기준) | Stage 1/평탄 부재 78 · **C3 단독 313** · C3+C5 13 — #158 B5(78 / 93.9% / 6.1%)와 정합. C3 단일 실효 게이트 사실 재확인 |

스크립트·원자료: 스크래치패드 `measure_169.py`·`measure_169.json`(행별 s61/s62/차단 사유).

## 4. 사전등록(배포 전 기록)

1. 변경 성격: book-fidelity 정합(governance 3-5). 성과 목적 아님.
2. 기대 방향: §6.1 climax_run 발화 **소폭 감소**(no_transition 행에서 P1∧P2 불가). 폭 미예측.
   §6.2 는 저장본 기준 변동 0(T-A/T-D거래량 단독 발화 행 없음).
3. 사전 기준선(저장본 §3 표). LLM 발화 기준선은 #158 §6-3 과 동일 시점 값 유지.
4. 성과 판정: P0 재수집 후 **holdout 으로만**(governance 3-2). 재실행 비교 금지(3-1).
5. 프롬프트 행 A·행 B 는 분류 변동 귀속 후보로 별도 기록 — 드리프트 관측 시 두 행을 분리 귀속.
6. 결측 처리 규약: governance 4-2(null = 보수).

## 5. 백테스트 불변 확인(armA-prod 표본 A+B, climax_sell=ON 기본)

배포 전 기준(항목 ③ §6-3/4): exits 37 = stop8 23 · sma50_trail 11 · floor 3, final_multiple 1.0185.
변경 후 실행 결과는 PR 회신에 기록(no_transition 판정 45건은 이미 fired=None 이라 불변 예상;
변동 시 사실 보고).
