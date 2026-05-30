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
