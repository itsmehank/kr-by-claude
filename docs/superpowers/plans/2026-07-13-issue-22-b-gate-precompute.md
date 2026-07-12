# 이슈 #22 — B(evaluate_pivot_trigger) 정량 게이트 코드 선계산 이관 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** B 프롬프트(§3.1/§3.2/§3.3/§3.5)의 정량 게이트 판정을 코드 선계산(`computed_gates`)으로 이관하고, §3.5 를 사유-독립(reason-independent) AND 회복 게이트로 재설계하며, #31 과도기 장치를 철거한다.

**Architecture:** 새 순수 함수 모듈 `gate_precompute.py` 가 payload 구성요소(20d OHLCV·current_metrics·prior·market_context·conditions_detail)에서 게이트 측정값+boolean 을 산출 → `build_for_5b` 가 `computed_gates` 로 payload 에 포함 → 프롬프트는 계산 지시 대신 `computed_gates` 값을 authoritative 로 소비. **결정 규칙(go_now/wait/abort 매핑)과 비산술 재량(거래량 동반의 의미, squat 회복 여지, soon-after 판단, confidence)은 LLM 에 잔류** — 코드는 측정만, 결정은 LLM.

**Tech Stack:** Python (psycopg, 순수 함수), pytest, prompt markdown, thresholds.py SSOT.

## 사전 결정 사항 (브리프 4건 — 재검토 후 확정)

| 결정 | 채택안 | 근거(재검토) |
|---|---|---|
| A. 이관 철학 | **측정 전면 코드화 + 결정·재량 LLM 잔류** (브리프 '하이브리드'의 구체화) | B §3.1 의 5개 게이트는 프롬프트에 이미 재량 없는 기계 규칙으로 정의돼 있어, boolean 선계산은 판정 규칙 변경이 아니라 계산 주체 이동. trigger_gate.py 의 false-negative 우려는 "사전 필터로 후보를 잘라내는" 층의 문제 — 본 이관은 후보를 자르지 않고(LLM 호출은 그대로) 측정값만 제공하므로 철학 충돌 없음. pocket pivot 예외는 B 프롬프트에 원래 없으므로 신설하지 않음(판정 불변 원칙). |
| B. distribution_day_flag per-row 전달 | **유지 + reference-only 재정의** | 감사 가능성(사람이 로그로 재검증) 유지. authoritative 문장·가드 테스트는 철거하고 "게이트 판정은 computed_gates 가 authoritative, per-row flag 는 참고용(재판정 금지)" 규약으로 교체 — 이중 정의 재발 통로 차단. |
| C. D4 거울 갭 | **사유-독립 AND 회복 게이트** | flag taxonomy 로는 구조적 폐쇄 불가(이슈 코멘트 확정). watch 출신 go_now 는 watch_reason 무관하게 market_recovery_ok AND tt_recovery_ok 요구. valid_base 사유도 시장 재확인을 받게 되는 동작 변화는 의도된 것 — O'Neil M 기준(시장 확인 없이는 매수 금지)과 정합. #29 의 flag 조건부 문장은 supersede. |
| D. 착수 순서 | **#21 대기 없이 착수** | 사용자가 #21 을 명시 제외. 파일 겹침 없음(코드상 의존 없음, 브리프 확인). |

### 세부 결정 (구현 중 확정)

- 오늘의 일중값(range 위치·spread·저가)은 **20d 리스트 마지막 행**, close/volume/sma 게이트는 **current_metrics** 기준 — 각 게이트의 자연 소스. halt 직후 두 소스 날짜가 다를 수 있음(#35 리뷰)을 `ohlcv_last_date` 필드로 노출.
- spread 의 "평균 range" 는 프롬프트에 창 정의가 없었음 → **직전 19행(오늘 제외) (high−low) 평균, 최소 5행** 으로 결정론 정의.
- volume band 경계: ratio > 1.4 = pass / 1.2 ≤ ratio ≤ 1.4 = wait_band / < 1.2 = below (프롬프트 "1.2~1.4× 사이" 문구와 정합, 경계 1.4 는 wait).
- null 규약: 입력 결측 → 해당 게이트 null. **go_now 필요 게이트가 null 이면 go_now 금지(보수)** 를 프롬프트에 명시.
- tt margin null: margin_pct 가 null 인 조건은 marginal 로 계수(보수).
- 판정 불변 검사(이관 전후 LLM 판정 비교)는 ★재실행 1:1 비교 금지 규율에 따라 본 PR 에서 수행하지 않음 — 실가동 데이터 누적 후 패턴 비교(후속). 본 PR 의 검증은 단위테스트+drift 가드.

## 임계 의존성 맵 (threshold-change-checklist §b — 2축 판정)

**트리거 사실**: thresholds.py 상수 9종 추가 + B/A 프롬프트 임계 텍스트 변경 → 체크리스트 필수.

**1단계 (파생 신호)**: 신규 상수 → `computed_gates.*` (volume_band, spread_wide_loose, no_dist_3d, dist_3plus_5d, close_below_sma50_breach, market_recovery_ok, tt_recovery_ok)

**2단계 (소비 룰)**: `computed_gates` 소비처 = B 프롬프트 §3.1(go_now/wait), §3.2(invalidation abort), §3.5(표준 검증+회복 게이트). 코드 소비처는 payload_lite(전달만). grep `computed_gates` → gate_precompute.py, payload_lite.py, 프롬프트, 테스트만.

**3단계 (룰 내부 고정 상수) — 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| BREAKOUT_VOL_WAIT_FLOOR=1.2 | 가능(배수) | 미미 — 기존 프롬프트 문구(1.2~1.4)의 SSOT 승격, 값 변화 0 | EXTENDS(wait 밴드는 시스템 설계) | 모니터링(값 변화 없음 — 동작 중립 승격) |
| SPREAD_WIDE_LOOSE_MULT=1.5 | 가능(배수) | 있음 — "평균 range" 창을 20d 로 처음 고정(기존 LLM 재량) | EXTENDS(wide-and-loose 개념은 O'Neil, 1.5×는 시스템) | B-수치(발동률 관찰 후 창·배수 재검토) |
| SMA50_BREACH_RATIO=0.98 | 가능(비율) | 미미 — 기존 문구(×0.98) 승격, 값 변화 0 | EXTENDS | 모니터링(동작 중립 승격) |
| STOCK_DIST_ABORT_COUNT_5D=3 / WINDOW 5d / CLEAN 3d | 불가(카운트·일수) | 미미 — 기존 문구(최근 5일 3+/최근 3일 무) 승격, 값 변화 0. 단 null flag=미계수 규약이 코드로 고정됨(기존 프롬프트 규약과 동일) | EXTENDS(분배 개념은 O'Neil, 창·카운트는 시스템) | 모니터링(동작 중립 승격) |
| MARKET_DIST_DEMOTION_COUNT_25S=5 | 불가(카운트) | 있음 — A 강등(≥5)·B 회복(<5) co-anchor 를 SSOT 단일값으로 강제(기존 텍스트 2사본) | PRESERVES(O'Neil HMMS Ch.9 5-6 distribution days) | 임계와 함께 보정(양쪽이 SSOT 참조 — drift 통로 제거) |
| TT_MARGIN_MARGINAL_PCT=3.0, TT_MARGINAL_DEMOTION_COUNT=3 | 부분(마진 %) | 있음 — B 회복 게이트(tt_recovery_ok)가 A §2 강등 기준과 동일 임계를 코드 소비(기존 B 텍스트는 "경계 해소" 모호 — 3개 미만으로 확정) | EXTENDS(marginal 개념은 Minervini §2 해설, 3%/3개는 시스템) | B-수치(회복 게이트 발동률 데이터 누적 후 재검토) |
| (기존) BREAKOUT_VOL_FLOOR=1.4 | — | 소비처 추가(gate_precompute) — 값 변화 0 | PRESERVES | 변경 없음 |
| (기존) STOCK_DISTRIBUTION_* (flag 산출) | — | 영향 없음 — flag 산출 로직 불변, 소비 방식만 코드로 이동 | PRESERVES | 변경 없음 |

**소비 경계 (1줄)**: `computed_gates` → B 프롬프트 → trigger_evaluation_log.decision → entry_params(6)/성과 기록 — LLM 결정층 이후는 기존과 동일.

**모호성 해소 기록**: B §3.5 기존 문구 "경계(마진 <3%)가 해소(clean)" 는 "전부 해소"로도 "3개 미만"으로도 읽힘 → A 강등 기준(3개 이상=강등)의 정확한 역(3개 미만=해소)으로 확정. 완전 clean(0개) 요구는 A 가 강등하지 않는 1~2개 marginal 종목의 회복을 영구 차단하는 비대칭이라 기각.

---

## File Structure

- Create: `kr_pipeline/llm_runner/compute/gate_precompute.py` — 순수 함수(DB 접근 없음)
- Create: `tests/test_compute_gate_precompute.py`
- Modify: `kr_pipeline/common/thresholds.py` — 상수 9종 추가
- Modify: `kr_pipeline/llm_runner/compute/payload_lite.py` — build_for_5b 에 computed_gates
- Modify: `prompts/evaluate_pivot_trigger_v1.md` — §2/§3/§3.1/§3.2/§3.3/§3.5/SSOT 블록
- Modify: `prompts/analyze_chart_v3.md` — SSOT 블록에 co-anchor 상수 3종 추가(텍스트 임계는 불변)
- Modify: `tests/test_prompt_trigger_gates.py` — 가드 재작성(구 #29/#31 문구 가드 → 신 규약 가드)
- Modify: `tests/test_prompt_threshold_drift.py` — PROMPT_SYNCED 갱신
- Modify: `tests/test_llm_compute_payload_lite.py` — computed_gates 존재/값 검증 추가
- Regenerate: `web/src/data/thresholds.generated.ts` (scripts/export_thresholds.py)

## Global Constraints

- 테스트: `uv run pytest tests/` 기대 실패 0 (CLAUDE.md).
- SSOT: 코드가 소비하는 임계만 프롬프트 SSOT 블록 등재. export 스크립트 재실행.
- 커밋 트레일러에 Co-Authored-By 금지(user CLAUDE.md). 스테이징은 명시 경로만(git add -A 금지).
- 프롬프트 결정 규칙(go_now/wait/abort 조건 구조) 자체는 불변 — 계산 주체만 이동. 유일한 의도적 동작 변화 = §3.5 사유-독립 회복 게이트(결정 C).

---

### Task 1: thresholds.py 상수 추가 + export 재실행

- [ ] thresholds.py 에 `# ===== (5b) B 게이트 선계산 (kr_pipeline/llm_runner/compute/gate_precompute.py) =====` 섹션 추가:
  - `BREAKOUT_VOL_WAIT_FLOOR: Final[float] = 1.2` (B wait 밴드 하한 — 기존 프롬프트 전용값 승격)
  - `SPREAD_WIDE_LOOSE_MULT: Final[float] = 1.5` (일중 range 의 20d 평균 대비 wide-and-loose 배수)
  - `SPREAD_AVG_WINDOW_DAYS: Final[int] = 19`, `SPREAD_AVG_MIN_ROWS: Final[int] = 5`
  - `SMA50_BREACH_RATIO: Final[float] = 0.98`
  - `STOCK_DIST_CLEAN_WINDOW_DAYS: Final[int] = 3`, `STOCK_DIST_ABORT_WINDOW_DAYS: Final[int] = 5`, `STOCK_DIST_ABORT_COUNT_5D: Final[int] = 3`
  - `MARKET_DIST_DEMOTION_COUNT_25S: Final[int] = 5` (A §3.5 강등 ≥N ↔ B 회복 <N co-anchor)
  - `TT_MARGIN_MARGINAL_PCT: Final[float] = 3.0`, `TT_MARGINAL_DEMOTION_COUNT: Final[int] = 3` (A §2 ↔ B tt_recovery co-anchor)
- [ ] `uv run python scripts/export_thresholds.py` 재실행 → generated.ts 갱신 확인
- [ ] Commit

### Task 2: gate_precompute.py (TDD)

- [ ] tests/test_compute_gate_precompute.py 작성 — 최소 케이스: volume band 3분기+경계(1.4→wait_band, 1.41→pass), close_range_pos/상단·중단 1/3, spread ratio(평균창·최소행 미달 null), dist 카운트(3d/5d, null flag 미계수), low_below_base_low, sma50/21 breach, market_recovery(회복/미회복/카운트 경계 5), tt_recovery(all pass+marginal 2 → ok, marginal 3 → not ok, margin null → marginal 계수), 입력 결측 → null 전파.
- [ ] 실행 — FAIL(모듈 부재) 확인.
- [ ] `compute_gates(*, ohlcv_20d: list[dict], current_metrics: dict, prior_analysis: dict, market_context: dict, conditions_detail: dict) -> dict` 구현(위 세부 결정의 필드 산출).
- [ ] 테스트 PASS 확인, Commit.

### Task 3: build_for_5b 통합

- [ ] test_llm_compute_payload_lite.py 에 computed_gates 존재+대표값(예: no_dist_3d, price_above_pivot) 검증 추가 — FAIL 확인.
- [ ] payload_lite.build_for_5b 반환 dict 에 `"computed_gates": compute_gates(...)` 추가(변환 완료된 조각들로 호출).
- [ ] payload_lite L74 부근 "(#31) … authoritative 입력" 주석을 reference-only 역할로 갱신.
- [ ] PASS 확인, Commit.

### Task 4: 프롬프트 재작성 + 가드 테스트 재작성 (단일 커밋 — 구 가드가 신 프롬프트에서 깨지므로 분리 커밋 금지)

- [ ] B §2 Inputs 에 `computed_gates` 명세 추가(필드·null 규약 포함).
- [ ] B §3 규약 교체: 기존 "분배일 판정 규약(flag authoritative)" 문단 삭제 → "**게이트 판정 규약**: 정량 게이트는 `computed_gates` 가 authoritative — OHLCV/지표로 재계산하지 말 것. per-row `distribution_day_flag` 와 원시 OHLCV 는 reasoning 서술 참고용(재판정 금지). go_now 에 필요한 게이트가 null 이면 go_now 금지."
- [ ] §3.1/§3.2/§3.3: 각 숫자 비교 지시를 computed_gates 필드 참조로 교체(결정 규칙 구조 불변, 비산술 재량 문구 유지).
- [ ] §3.5: 사유별 게이트 bullet 3개 + risk_flags 조건부 문장 2개 삭제 → 사유-독립 회복 게이트로 교체: "go_now 는 공통 표준 검증에 더해 `computed_gates.market_recovery_ok == true` **AND** `computed_gates.tt_recovery_ok == true` 필수 — watch_reason 에 무엇이 기록됐든 항상 둘 다(D4 거울 갭 폐쇄). 미충족 → wait."
- [ ] B SSOT 블록: BREAKOUT_VOL_WAIT_FLOOR, SPREAD_WIDE_LOOSE_MULT, SMA50_BREACH_RATIO, STOCK_DIST_CLEAN_WINDOW_DAYS, STOCK_DIST_ABORT_WINDOW_DAYS, STOCK_DIST_ABORT_COUNT_5D, MARKET_DIST_DEMOTION_COUNT_25S, TT_MARGIN_MARGINAL_PCT, TT_MARGINAL_DEMOTION_COUNT 추가.
- [ ] A SSOT 블록: MARKET_DIST_DEMOTION_COUNT_25S, TT_MARGIN_MARGINAL_PCT, TT_MARGINAL_DEMOTION_COUNT 추가(§2/§3.5 텍스트 임계는 이미 동일값 — 텍스트 불변).
- [ ] test_prompt_trigger_gates.py 재작성:
  - 유지 취지 계승: `test_b_prompt_declares_computed_gates_authoritative` (computed_gates…재계산하지 말 금지 토큰)
  - 신규: `test_b_recovery_gate_reason_independent` — §3.5 에 market_recovery_ok AND tt_recovery_ok 필수 문구 존재 + 사유별 조건부 게이트 bullet(`- \`unfavorable_market\`:` 등) 부재
  - 재작성: `test_a_demotion_threshold_matches_ssot` — A §3.5 `>= N` 리터럴 == thresholds.MARKET_DIST_DEMOTION_COUNT_25S
  - 신규: `test_a_marginal_thresholds_match_ssot` — A §2 의 `< 3%`·`3 or more` == TT 상수
  - 삭제: 구 #29 flag 조건부 가드 2종, #31 flag authoritative 가드(철거 목록 ②③)
- [ ] test_prompt_threshold_drift.py PROMPT_SYNCED 갱신(B +9, A +3).
- [ ] Commit (프롬프트+가드 테스트 한 커밋).

### Task 6: 전체 검증

- [ ] `uv run pytest tests/` — 0 failed 확인(실패 시 원인 수리).
- [ ] Commit(필요 시).

### Task 7: PR

- [ ] PR 생성(머지 금지): 결정 A~D + 세부 결정 + 의존성 맵 요약 포함.
