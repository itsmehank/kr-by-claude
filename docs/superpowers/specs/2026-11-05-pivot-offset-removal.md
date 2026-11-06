# pivot "+0.1" 가산 폐지 — 의존성 맵·동작 기록 (2026-11-05)

> 트리거(threshold-change-checklist (a), governance 2-1 사실 트리거): `thresholds.py` 상수 삭제(`PIVOT_PRICE_OFFSET`)
> + 그 소비처(`store.py` 사후검증) + 연동 프롬프트 임계 텍스트(`analyze_chart_v3.md` §4.7 표·§7).
> 판정 주체(governance 2-2): 전문가 사실 확인(2026-11-05 — #253 코멘트 [Q-3] "책에 '10 cents' 가산 서술 없음",
> #175 회신 [Q-1] "`handle_high = pivot(+0.1)` 오프셋 → 고점 당일 미매칭") + 사용자 결정("+0.1 지워줘").
> 성과 목적 아님 — book-fidelity 교정(governance 3-5 예외) + 결정론 검출기 정합. #255(귀속 문구 정정)는 삭제로 superseded.

## 1. 무엇을 바꾸나 (사실)

| 위치 | 전 | 후 |
|---|---|---|
| `prompts/analyze_chart_v3.md` §4.7 표 5행 | `range_high + 0.1` 등 | `range_high` 등 — 고점 그대로. 표 아래 "가산 없음" 1문장 추가 |
| 같은 파일 §7 | `+ $0.10 (Minervini's standard add-on)` / `base high + 1 tick … base_high alone is acceptable` | pivot = 고점 **itself**, no add-on. 책 인용(HMMS p.118·TLSMW p.223) |
| 같은 파일 SSOT 블록·예시 JSON | `PIVOT_PRICE_OFFSET = 0.1`, `82500.1` | 삭제, `82500.0`. 상단 governance 4-6 변경 선언 주석 |
| `kr_pipeline/common/thresholds.py` | `PIVOT_PRICE_OFFSET = 0.1` | 삭제(묘비 주석) |
| `kr_pipeline/llm_runner/store.py` 사후검증 | 허용 {앵커, 앵커+0.1, 앵커+1 tick}, 초과 검사 `> base_high + tick` | 허용 {앵커}, 초과 검사 `> base_high`. `krx_tick_size` import 소멸(함수는 trading guard 가 계속 사용) |
| `compute/failed_breakout.py` | D0·P2 `close >= pivot`, P1 `close < pivot` | `>`·`<=` — **동작 보존 보정**(§2) |
| `compute/pivot_continuity_stats.py` | — | `_SUB_TICK_KRW = 1.0`: 1원 미만 하향은 재판독으로 안 셈(판독 전용) |
| `compute/handle_quality.py` | — | 주석만(S4 `high ≥ pivot` 이 고점 당일을 매칭하게 됨) + 테스트 `high == pivot` 매칭 |
| `backtest/recall_phase2.py` | `adj_high >= pivot` | `>` — 동작 보존 보정(리뷰 R1) |
| `llm/claude_cli.py` dry-run mock | `pivot = base_high × 1.001` | `base_high` — 가산 폐지 후 사후검증 경고 노이즈 방지(리뷰 R1) |
| `web/src/data/llm-pipeline-audit/base-patterns.ts`·`llm-pipeline-simulation.ts` | §4.7 표 미러 `"+ 0.1"` | 제거 + `test_a_47_pivot_has_no_add_on` 이 미러도 가드(리뷰 R1) |
| `common/krx.py` docstring | 소비처 = store | 소비처 = trading guard 만 |
| `web/src/data/thresholds.generated.ts` | `PIVOT_PRICE_OFFSET` | export 재실행으로 소멸 |
| 문서 | — | GLOSSARY base/pivot·wake 조건, checklist 이력, 본 스펙 |

과거 저장 행(`weekly_classification`·`backtest_classification`)의 pivot 은 +0.1 그대로 둔다(소급 없음 — 과거 트리거 로그 확정, #253 §8 과 동일 원칙).

## 2. 의존성 맵 (checklist (b))

**1단계(파생 신호)**: `PIVOT_PRICE_OFFSET` → 프롬프트가 LLM 에 지시하는 `pivot_price`(고점+0.1) → 저장 `pivot_price`
→ `effective_pivot`(#253 래칫) → `pivot_continuity.pivot_change_pct`. 폐지 후 신규 행의 `pivot_price` = 고점 H.

**2단계(소비 룰)** — `grep -rn "pivot" kr_pipeline api --include='*.py' | grep -E ">=|<=|<|>"` 전수. KRX 가격은 정수 호가라
"전 = H+0.1, 후 = H" 를 정수 종가 c 에 대해 비교한다.

| 소비 룰 | 비교식 | 전(pivot=H+0.1) | 후(pivot=H) | 동작 | 조치 |
|---|---|---|---|---|---|
| `trigger_gate` breakout·bfw | `c > pivot`, `prev_c <= pivot` | c ≥ H+1 / prev ≤ H | c ≥ H+1 / prev ≤ H | 동일 | 없음 |
| `trigger_gate` promotion | `c >= pivot×0.95` | ≥ 0.95H+0.095 | ≥ 0.95H | 경계 0.095 하향(미미, §3단계) | 없음 |
| `gate_precompute` `close > pivot` | strict | 동일 | 동일 | 동일 | 없음 |
| `evaluate_pivot` extended 인터셉트 | `c > pivot×1.05` | > 1.05H+0.105 | > 1.05H | 경계 0.105 하향(미미) | 없음 |
| `gates.py` 8_5_extended_band | 같은 식 | 동일 | 동일 | 미미 | 없음 |
| **`failed_breakout`** D0·P2 / P1 | `c >= pivot` / `c < pivot` | ≥H+0.1 ⇔ ≥H+1 / <H+0.1 ⇔ ≤H | `>=` 가 ≥H 로 바뀌어 c==H 를 돌파로 셈 | **변함** | **보정**: `>`·`<=` 로 교체 + 테스트(동치 보존) |
| **`handle_quality`** S4 | `high >= pivot` | high ≥ H+0.1 → 고점 당일(high==H) 미매칭 | high ≥ H → 고점 당일 매칭 | **변함(의도)** | 신규 행부터. 과거 행 역산(pivot−0.1 / 최근접 고가 봉)은 #175 재설계 |
| `ratchet_pivot` | `new < prev_effective` | — | 이행기: 같은 베이스 첫 재판독 H < 직전 effective H+0.1 → `kept` | effective = H+0.1 유지 → 트리거 동일(인공물) | #253 관측 SQL 에서 `prev_effective − pivot_price ≤ 0.1` kept 분리(§3) |
| `_pivot_continuity` → `downward_chains` | `pivot_change_pct < 0` | — | 이행기 −0.0004% 하향 집계 | 인공물 | `_SUB_TICK_KRW` 필터 + 테스트 |
| `entry_params_calc` trigger/stop/target | `trigger <= pivot` 가드, `× ENTRY_TRIGGER_BUFFER_MAX` | 0.1 차 | — | 중립(가드가 strict > 보장) | 없음 |
| `store` HARD `base_low > pivot` | — | 0.1 차 | — | 중립 | 없음 |
| backtest `trigger_sim`·`stop_variant_sim`·`portfolio` | `c > pivot`, `c > pivot×(1+chase)` | 동일 | 동일 | 동일. 백테스트 저장본 pivot 은 구(+0.1)·신 혼재 — 1원 미만 | 없음 |
| 웹 표시(classification 카드·review) | 표시값 | `.1` 표시 | 정수 | 중립 | 없음 |
| **`backtest/recall_phase2.find_breakout`** (리뷰 R1) | `adj_high >= pivot` | ≥H+0.1 ⇔ ≥H+1 ⇔ >H | `>=` 가 ≥H 로 바뀌어 고점 터치를 돌파로 셈 | **변함** | **보정**: `>` 로 교체(S4 와 달리 "돌파" 의미라 터치는 돌파 아님). 저장 구 행 소비 시 동작 동일 |
| `entry_params_calc` `extended_from_pivot_already` `current > pivot×1.03` (리뷰 R1) | 비율 | > 1.03H+0.103 | > 1.03H | 경계 0.103원 하향(미미) | 없음 |
| `store` `_PIVOT_CLOSE_BAND`(sanity_pivot_far_from_price) | 비율 밴드 | — | — | 미미 | 없음 |
| `store` `ENTRY_STOP_PCT_FROM_PIVOT_FLOOR` −10 (stop 경고) | 비율 | — | — | 미미 | 없음 |
| `signal_link` chase strict > 5% (#162) | 비율 | — | — | 미미 | 없음 |
| `backtest/trigger_sim` 체결 `low <= pivot×1.01` | 비율 | — | — | 미미 | 없음 |
| `store` `[pivot-continuity] same-base reread` 경고·`stored_events` | `pivot_change_pct ≠ 0` | — | 이행기 −0.0004% 가 경고·집계에 잡힘 | 인공물 | 1원 미만 하향은 경고 생략·`stored_events` 미집계(리뷰 R1 — `downward_chains` 와 같은 기준) |

**3단계(룰 내부 고정 상수) — 2축 판정**

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `PIVOT_EXTENDED_BAND_MULT` 1.05 | 불가(비율) | **미미** — 경계가 0.105원 내려감(= 보수 방향, 정수 종가가 그 틈에 걸릴 때만) | design-judgment | 모니터링 — 근거: 변화 방향이 보수(extended 판정이 아주 약간 넓어짐)이고 크기가 1원 미만 |
| `GATE_PROMOTION_PRICE_RATIO` 0.95 | 불가 | **미미** — 경계 0.095원 하향 = promotion 미세 완화 | design-judgment | 모니터링 — 근거: promotion 은 LLM 평가 호출 여부만 결정(매수 아님), 크기 1원 미만 |
| `ENTRY_TRIGGER_BUFFER_MAX` 1.005 | 불가 | 없음 — 가드 `trigger <= pivot` 이 strict 보장 | design | — |
| `FAILED_BREAKOUT_K_DAYS` 5 / `_CONSECUTIVE_BELOW` 2 | 불가(일수) | 없음 — 비교식 보정으로 D0·P1·P2 집합 동일 | design | 보정 완료(테스트 `close == pivot`) |
| `HANDLE_LEGIT_MIN_DAYS` 5 / `BASE_MIN_DAYS` | 불가(일수) | **있음** — 시작점이 고점 당일로 앞당겨져 `handle_rows` 길이·커버리지 증가(의도) | book-anchor(1~2주 이상) | **B-수치**: #175 재설계 재현 스크립트(`hq_spec_verify_175.py` 계열)로 폐지 후 첫 4주 커버리지(현 23%)·림 미회복 비율(현 33.8%) 재측정 |
| `HANDLE_VOLUME_NOT_CONTRACTING_RATIO` 0.80 / 분배일 ≥1 | 불가 | **있음** — 손잡이 구간이 달라져 (B)·(D) 발화 집합 변화 | design(책에 없음 — 회신 Q-4·Q-5) | **B-수치**(위와 같은 측정) + #175 재설계에서 수치 자체 재판정 |
| `_BASE_NEAR_DAYS` 10 (continuity) | 불가 | 없음 — `base_start_date` 비교 | design | — |
| `_SUB_TICK_KRW` 1.0 (신설, 판독 전용) + store 경고 게이트 1.0 | 불가(호가 단위) | 판독 계수·경고 로그만(저장 JSON 불변) | design(KRX 정수 호가) | — |
| `extended_from_pivot_already` 1.03 (entry_params_calc 리터럴) | 불가(비율) | **미미** — 경계 0.103원 하향(보수 방향: 창 1일 축소가 아주 약간 넓어짐) | design-judgment(§7 통합표) | 모니터링 — 근거: 1원 미만, 방향 보수 |
| `_PIVOT_CLOSE_BAND`·`ENTRY_STOP_PCT_FROM_PIVOT_FLOOR`·chase 5%·fill 1.01 | 불가(비율) | 미미 — 전부 1원 미만 경계 이동, 경고/시뮬 체결 전용 | design | — |
| `krx_tick_size` (store 소비 소멸) | — | 없음 — trading guard 소비 유지 | — | — |
| `TRADE_STOP_INITIAL_PCT` 0.08 | — | 없음 — 매입가 기준, pivot 비소비 | book | — |

**소비 경계(1줄)**: `pivot_price`/`effective_pivot` → 평일 트리거(`evaluate_pivot`·`trigger_gate`) → `entry_params` → positions(#162).
하류 깊이 추적 안 함.

## 3. 이행기 인공물과 관측 분리

- 첫 적용 주말(2026-11-08) 같은 베이스(same/near) 재판독: LLM 새 pivot H, 직전 `effective_pivot` H+0.1 →
  `ratchet_pivot` = `kept`(effective H+0.1 유지), `pivot_change_pct ≈ −0.0004%`. 매매 동작은 동일(정수 종가).
- #253 4주 관측(≈12-06) 에서 분리:
  ```sql
  SELECT count(*) FILTER (WHERE (pivot_continuity->>'prev_effective_pivot')::numeric - pivot_price <= 0.1) AS artefact_kept,
         count(*) AS kept_total
    FROM weekly_classification
   WHERE pivot_continuity->>'ratchet' = 'kept';
  ```
- `scripts/issue129_pivot_continuity_readout.py`: 하향 체인(`downward_chains`)·저장 이벤트(`stored_events`) 모두 `_SUB_TICK_KRW` 로
  1원 미만 하향을 제외(테스트 2건). store 의 `[pivot-continuity] same-base pivot reread` 경고도 같은 기준으로 생략하므로
  `parse_log_events` 로그 계수에도 인공물이 들어가지 않는다. 저장 `pivot_continuity` JSON(`pivot_change_pct ≈ −0.0004`)은 그대로 —
  H ≥ 약 250,000원이면 4자리 반올림으로 −0.0 이 되어 가격대에 따라 값이 다르게 보인다(판정 비입력).
- `ratchet=kept` 집계만은 위 SQL 로 수동 분리(래칫 순수 함수는 변경하지 않음 — #253 로직 불변).
- LLM 이 관성으로 +0.1 을 계속 적으면 `sanity_pivot_offset_rule` 경고로 드러난다(range_high basis 한정) — 11-08 뒤 발생률 1회 점검.

## 4. 검증

- 테스트(TDD, red → green): `test_prompt_a_gates`(가산 부재·상수 삭제·웹 미러), `test_prompt_threshold_drift`(목록),
  `test_llm_runner_store`(허용 집합 축소 — +0.1·+1 tick 이제 경고), `test_compute_failed_breakout`(close == pivot 동치 보존),
  `test_issue129_readout`(서브 틱 — 체인·저장 이벤트), `test_compute_handle_quality`(high == pivot 림 매칭). suite 기대 0 failed·1 skipped·1 deselected.
- 독립 리뷰 R1(2026-11-06) 반영: Important 3(웹 미러 잔존·로그/저장 계수 인공물·소비처 누락 recall_phase2/1.03 등) · Minor 4(dry-run mock·krx docstring·
  S4 테스트 부재·프롬프트 문구) 전부 수리. 검증 통과 항목: failed_breakout 동치(소수 adj 종가 (H, H+0.1) 만 책 의미로 돌파 편입), store 1e-3 허용,
  래칫 kept 가 검출기(LLM raw pivot 소비)로 전파되지 않음.
- `uv run python scripts/export_thresholds.py` → generated.ts 에서 `PIVOT_PRICE_OFFSET` 소멸(tsc 영향 없음 — 웹 소비처 0).
- 배포 후(라이브 pull): 11-08 주말 분류 저장 행 `pivot_price` 소수부 0 확인.

## 5. 규범 인용 (checklist (f))

governance 2-1(사실 트리거)·2-2(판정 분리: 전문가 사실 확인 + 사용자 결정)·3-1(재실행 비교 금지 — 과거 행 소급 없음)·
3-5(book-fidelity 교정 예외)·4-3(상수 계약)·4-6(프롬프트 SSOT·변경 선언). 신설 규칙 없음. 관련: #255(superseded)·#175·#253·#261.
