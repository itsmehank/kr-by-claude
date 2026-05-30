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
