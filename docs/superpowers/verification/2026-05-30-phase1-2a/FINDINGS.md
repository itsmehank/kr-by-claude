# Phase 1 2-A 회귀 마일스톤 — FINDINGS

**날짜**: 2026-05-30
**스크립트**: `scripts/regression_phase1_2a.py`
**결과**: Hard Gate 통과 — 2-B/C/D 진입 허가

---

## 005850 — entry → watch (2E_tier2)

### 입력 (weekly_classification 최신 행)

- classified_at: 2026-05-29 01:43:39 KST
- classification: **entry**
- pattern: cup_with_handle
- pivot_price: 71900.1
- pivot_basis: handle_high
- base_high: 73400.0 / base_low: 54200.0 / base_depth_pct: 26.20%
- base_start_date: 2026-02-27
- risk_flags: ['extended_from_ma']
- confidence: 0.62

### handle_quality metrics

- ratio_a (handle_depth/base_depth): **0.791** > 0.33 → deep_handle
- ratio_b (avg_handle_vol/avg_base_vol): **1.755** > 0.80 → volume_not_contracting
- distribution_days: **2** >= 1 → distribution_in_handle
- handle_window: 2026-05-15 ~ 2026-05-28
- handle_high: 71900.1 / handle_low: 57000.0
- 추가 가중치: handle_position_low
- 발화 이유 3가지: deep_handle, volume_not_contracting, distribution_in_handle

### 게이트 후 출력

- classification: entry → **watch** (강등)
- confidence: 0.62 → **0.50** (Tier2 cap)
- risk_flags: ['extended_from_ma'] → ['extended_from_ma', **'handle_quality'**]

### triggered_rules

- **2E_tier2**: fired=True, inputs=['handle_quality','extended_from_ma'], action=entry_demoted_to_watch_with_entry_params_block
- **2F_failed_breakout**: fired=True (부가), trigger=both(P1+P2), D0=2026-02-27, consecutive_below=5

---

## 037760 — 2F 발화 (watch 유지)

### 입력 (weekly_classification 최신 행)

- classified_at: 2026-05-29 03:27:29 KST
- classification: **watch**
- pattern: **flat_base** (handle_quality 스킵 — 정상)
- pivot_price: 2445.1 / base_start_date: 2026-04-06
- risk_flags: ['unfavorable_market_context']
- confidence: 0.65

### 2F failed_breakout 분석

- D0=2026-05-15 (close=2455.0 >= pivot=2445.1)
- D1~D5: 2530, 2450, 2390, 2315, 2395
- consecutive_below: 2026-05-20~2026-05-22 = **3일** >= 2 → P1 fired

### 게이트 후 출력

- classification: watch → **watch** (유지)
- triggered_rules:
  - **2F_failed_breakout**: fired=True, trigger=P1, D0_date=2026-05-15, consecutive_below=3, max_close=2530.0

---

## 룰별 독립 카운트 (weekly_classification 전체)

- 2E_tier1: 0
- 2E_tier2: 0
- 2F_failed_breakout: 0

이 회귀 스크립트는 DB 에 저장하지 않고 in-memory gate 만 돌리므로 카운트 0 이 정상.
(005850/037760 의 기존 분류 행은 gate 통합(Task 5) *이전* 에 생성돼 triggered_rules 가 NULL — 향후 재분류 시 채워짐.)

**한계**: 이 스크립트는 '현재 DB 의 005850 최신 분류 + gate' 조합을 검증한다.
005850 이 정당하게 watch 로 재분류되면 assert 가 깨지며 — 이는 false alarm 신호이니,
그때는 고정 픽스처로 교체하거나 gate 로직 자체를 단위 테스트로 재검증할 것.

---

## Hard Gate 통과 선언

| 검증 항목 | 결과 |
|-----------|------|
| 005850: entry → watch 강등 | PASS |
| 005850: conf <= 0.50 (Tier2 cap) | PASS (0.62 → 0.50) |
| 005850: 2E_tier2 발화 | PASS |
| 005850: handle_quality 주입 | PASS |
| 037760: 2F_failed_breakout 발화 | PASS (P1, consecutive_below=3) |
| 037760: watch 유지 (강등 없음) | PASS |

Phase 1 2-A Hard Gate 통과. 2-B/C/D 진입 허가.

---

## 전체 회귀 (Task 8 Step 1)

**실행**: `uv run pytest tests/` — 2026-05-30

**결과**: 401 passed, 26 failed (baseline 동일)

### Phase 1 신규 테스트 — 전부 PASS

| 테스트 파일 | 테스트 수 | 결과 |
|---|---|---|
| test_schema_triggered_rules.py | 2 | PASS |
| test_compute_handle_quality.py | 7 | PASS |
| test_compute_failed_breakout.py | 6 | PASS |
| test_gates_phase1.py | 7 | PASS |
| test_store_phase1_gate.py | 2 | PASS |
| test_entry_params_tier2_block.py | 1 | PASS |

**계**: 25개 신규 테스트 전부 PASS.

### 26개 실패 — 전부 pre-existing isolation/DB 격리

| 파일 | 해당 실패 |
|---|---|
| test_weekly_integration.py | 3 (DB isolation) |
| test_weekly_modes.py | 2 (DB isolation) |
| test_universe_store.py | 3 (DB isolation) |
| test_llm_store_load.py | 4 (psycopg/expires_at schema isolation) |
| test_llm_compute_delta.py | 2 (psycopg isolation) |
| test_llm_compute_payload_lite.py | 2 (DB isolation) |
| test_llm_daily_delta.py | 1 (TypeError dry_run) |
| test_llm_entry_params.py | 1 (DB isolation) |
| test_llm_weekend.py | 1 (DB isolation) |
| test_indicators_integration.py | 1 (DB isolation) |
| test_integration.py | 1 (DB isolation) |
| test_ohlcv_modes.py | 2 (AssertionError coverage) |
| test_schema_llm_runner.py | 1 (AssertionError schema) |
| test_api_runner_service.py | 1 (DB isolation) |
| test_api_zip_builder.py | 1 (DB isolation) |

Phase 1 작업이 새 실패를 추가하지 않았음 확인. 26개 모두 weekly/llm/ohlcv DB 격리·schema 불일치 계열의 pre-existing 실패.

---

## thresholds.py 미이관 — Phase 2 SSOT sync 대상

`grep -n "0.33\|handle\|failed_breakout\|DEEP_HANDLE\|K_DAYS" kr_pipeline/common/thresholds.py` 결과: 해당 없음 (K_DAYS, DEEP_HANDLE_RATIO 등 없음).

현재 Phase 1 2-A 의 compute 모듈 (`handle_quality.py`, `failed_breakout.py`) 은 아래 상수를 모듈 로컬로 보유하며 `thresholds.py` 를 소비하지 않음:

| 상수 | 값 | 위치 |
|---|---|---|
| `DEEP_HANDLE_RATIO` | 0.33 | `handle_quality.py` |
| `VOLUME_NOT_CONTRACTING_RATIO` | 0.80 | `handle_quality.py` |
| `K_DAYS` | 5 | `failed_breakout.py` |
| `CONSECUTIVE_BELOW` | 2 | `failed_breakout.py` |

**결론**: `thresholds.py` 를 소비하지 않으므로 CLAUDE.md 의 threshold-change-checklist 의존성 맵 작성 불요 (현 사이클). Phase 2 에서 위 4개 상수를 `thresholds.py` SSOT 로 이관 예정.

---

## 005850 핸들 창 실측 검증 (사용자 v6 요청 — 과확장 점검)

`pivot(handle_high)=71,900` · `base_high=73,400` · `base_low=54,200` · `base_depth=26.2%` · `base_start=2026-02-27` · `classified_at=2026-05-29`.

휴리스틱 출력 (61봉):
- **cup_bottom** = 2026-04-07, low **53,200** (베이스 중앙 — 정상)
- **right_rim** = 2026-05-15, high **72,600** (≥ pivot)
- **handle 창** = 2026-05-15 ~ 2026-05-28 (9봉, 우측 림 이후로 분리)
- **handle_low** = **57,000** (2026-05-20 장중 low; 그날 종가 58,900)

| 점검 | 결과 |
|---|---|
| 핸들 창이 컵 바닥으로 과확장? | **아니오** — handle_low 57,000 > cup_bottom 53,200. 창이 우측 림(5/15) 이후로 깨끗이 분리 |
| ratio_a=0.791 의 출처 | **장중 low(57,000) 기준**. 종가(58,900) 기준이면 0.690. (사용자 가설 확정) |
| 발화 견고성 | 장중/종가 모두 0.33 압도 (0.79 / 0.69) → 005850 발화는 기준 선택과 무관 |

핸들 형태: 5/15 우측 림(close 71,900=pivot) → 5/18~5/20 **~20% 눌림**(low 57,000) → 5/22~5/28 pivot 위로 돌파(high 77,300→79,500). 진짜 *결함성 깊은 핸들* — handle_quality 발화 + 2E_tier2 강등 정당.

**모델링 노트 (Phase 2 재조정 후보)**: spec §3 은 handle depth 에 *장중 low* (`min(low)`) 사용. 0.33 경계 *근처* 종목은 intraday vs close 선택이 발화를 뒤집을 수 있음 → Phase 2 에서 "handle depth 기준 = 장중 low vs 종가" 명시 결정 필요. (005850 은 무관.)

---

## ⛔ Phase 2 (verify sync) 는 *필수* — 검증 루프 가동 전 선행 (사용자 v6)

현재 2-A 는 **후처리-온리** (prompt 미갱신). 검증 루프(verify_analysis)에 쓰기 전 반드시 sync 해야 하는 이유:

1. **(a) 설명↔판정 불일치**: LLM reasoning 글은 여전히 'entry 옹호' 인데 후처리가 분류를 watch 로 강등 → 분석 패키지 안에서 *reasoning 과 classification 이 모순*. 검증자(사람/LLM)가 보면 일관성 결함으로 읽힌다. prompt 에 2-E 룰을 넣어 LLM 이 *처음부터* watch + 일관 reasoning 을 내게 해야 함 (후처리는 이중 보장으로 잔존).
2. **(b) 검증자가 handle_quality 를 모름**: `prompts/verify_analysis_v1.md` 와 평가 루프가 14번째 flag(handle_quality) 의 정의·트리거를 모른다 → 검증자가 그 flag 의 타당성을 평가할 수 없음. verify prompt 에 handle_quality 정의 + 2-E/2-F 룰 동기화 필수.

**결론**: 2-B/C/D fast-follow 후 **Phase 2 sync 를 검증 루프 사용 전 하드 선행**. (thresholds.py SSOT 이관도 Phase 2 에 포함 — 위 섹션.)

---

## 재개 시 순서 (배치)

1. **프로덕션 검증 (지금 대기)**: 다음 운영 사이클(weekend/daily_delta, gate 통합된 store 경유)이 005850 을 watch 로 *실제 재저장* 하고, triggered_rules 에 2E_tier2 가 기록되며, entry_params 후보에서 2E_tier2 차단으로 005850 이 빠지는지(=entry_params 보류 해제) 프로덕션에서 확인.
2. **2-B** (wide_and_loose KOSPI 분기) / **2-C** (분배 클러스터) / **2-D** (RS divergence) — fast-follow, 같은 후처리-온리 패턴.
3. **Phase 2 sync** (필수, 위 ⛔): prompt 텍스트 + thresholds.py SSOT + verify prompt 동기화 → 이후 검증 루프 가동 가능.
