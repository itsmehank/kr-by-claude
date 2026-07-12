"""entry_params_calc — C 단계 결정론 함수 (#21, 구 calculate_entry_params_v2_0.md §0.5~§11 이식).

결정 조합: D1(a) 3c_cheat 세분 포기 · D2(a) none 거부 · D3(a) VCP chase 일괄 3.0 · D4(a) parity 별도.
DB 불필요 — 순수 함수.
"""
import pytest

from kr_pipeline.llm_runner.compute.entry_params_calc import (
    EntryParamsRejected,
    calculate_entry_params,
)
from kr_pipeline.llm_runner.store import _normalize_entry_params


def _payload(**over):
    """표준 케이스 기본 payload (§9 첫 예시 유사 — flat_base, 무flag)."""
    p = {
        "symbol": "TEST",
        "prior_analysis": {
            "classification": "entry",
            "pattern": "flat_base",
            "pivot_price": 192.50,
            "pivot_basis": "range_high",
            "base_high": 192.50,
            "base_low": 178.00,
            "base_depth_pct": 9.5,
            "risk_flags": [],
            "confidence": 0.8,
            "reasoning": "clean flat base",
        },
        "trigger_evaluation": {"trigger_type": "breakout", "decision": "go_now"},
        "current_state": {"close": 192.30, "volume": 1_600_000, "avg_volume_50d": 1_000_000},
        "recent_daily_indicators": [
            {"date": f"2026-05-{d:02d}", "close": 190.0, "low": 188.0,
             "sma_50": 180.0, "pocket_pivot_flag": False}
            for d in range(11, 21)
        ],
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k] = {**p[k], **v}
        else:
            p[k] = v
    return p


# ---------- §9/§10 형태 ----------

def test_standard_flat_base_happy_path_full_schema():
    r = calculate_entry_params(_payload())
    assert r["entry_mode"] == "pivot_breakout"
    assert r["pattern_basis"] == "flat_base"
    assert r["pivot_price"] == 192.50
    assert r["trigger_price"] == round(192.50 * 1.001, 2)
    assert r["trigger_price"] > r["pivot_price"]
    assert r["current_price"] == 192.30
    # logical = (178*0.995 - 192.5)/192.5*100 = -8.02.. → max(-7, -8.02) = -7 (absolute binding)
    assert r["stop_loss_pct_from_pivot"] == -7.0
    assert r["stop_loss_price"] == round(192.50 * (1 + -7.0 / 100), 2)  # 모듈 공식과 동일 경로(부동소수 표기 차 방지)
    assert r["suggested_weight_pct"] == 10.0            # 표준 티어, 무flag
    assert r["expected_target_pct"] == 20.0
    assert r["entry_window_days"] == 3
    assert r["max_chase_pct_from_pivot"] == 5.0
    assert r["breakout_volume_requirement"] == "ge_1.5x_50day_avg"
    assert r["observed_breakout_volume_ratio"] == 1.6
    assert 50 <= len(r["notes"]) <= 600
    assert r["known_warnings"] == []
    assert r["other_warnings"] == []
    # 저장 계약(§9 17필드) — _normalize 가 예외 없이 통과해야 한다
    _normalize_entry_params(dict(r))


def test_determinism_same_input_same_output():
    a = calculate_entry_params(_payload())
    b = calculate_entry_params(_payload())
    assert a == b


# ---------- D2(a): none 거부 ----------

def test_pattern_none_rejected_fail_loud():
    with pytest.raises(EntryParamsRejected):
        calculate_entry_params(_payload(prior_analysis={"pattern": "none", "pivot_price": None}))


def test_missing_pivot_rejected():
    with pytest.raises(EntryParamsRejected):
        calculate_entry_params(_payload(prior_analysis={"pivot_price": None}))


# ---------- §0.5 / §1.2 pocket pivot ----------

def _pp_payload(**over):
    rdi = [
        {"date": f"2026-05-{d:02d}", "close": 190.0, "low": 188.0,
         "sma_50": 180.0, "pocket_pivot_flag": False}
        for d in range(11, 20)
    ]
    rdi.append({"date": "2026-05-20", "close": 192.0, "low": 189.5,
                "sma_50": 185.0, "pocket_pivot_flag": True})
    base = _payload(
        prior_analysis={"reasoning": "pocket_pivot_entry within flat base", "confidence": 0.8},
        recent_daily_indicators=rdi,
        current_state={"close": 192.4, "volume": 1_600_000, "avg_volume_50d": 1_000_000},
    )
    for k, v in over.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


def test_pocket_pivot_mode_pivot_is_pp_day_close():
    r = calculate_entry_params(_pp_payload())
    assert r["entry_mode"] == "pocket_pivot"
    assert r["pivot_price"] == 192.0                     # PP일 close
    assert "entry_mode_pocket_pivot" in r["known_warnings"]
    assert r["breakout_volume_requirement"] == "pocket_pivot_signature"
    assert r["expected_target_pct"] <= 18.0              # pocket cap
    assert r["entry_window_days"] <= 2
    assert r["max_chase_pct_from_pivot"] == 3.0
    assert -8.0 <= r["stop_loss_pct_from_pivot"] <= -4.0  # pocket clamp
    assert r["suggested_weight_pct"] == 7.0              # pocket 표준 티어(flat_base 무flag)


def test_pocket_pivot_claimed_but_no_flag_falls_back_standard():
    p = _pp_payload()
    for row in p["recent_daily_indicators"]:
        row["pocket_pivot_flag"] = False
    r = calculate_entry_params(p)
    assert r["entry_mode"] == "pivot_breakout"
    assert any("pocket_pivot claimed" in w for w in r["other_warnings"])
    assert r["pivot_price"] == 192.50                    # prior pivot 복귀


def test_pocket_pivot_sma50_binding_emits_warning():
    # sma50_buffered = 191.0*0.995 = 190.045 → pct = (190.045-192)/192*100 = -1.018 → clamp -4.0
    p = _pp_payload()
    p["recent_daily_indicators"][-1]["sma_50"] = 191.0
    r = calculate_entry_params(p)
    assert "stop_at_50day_ma_for_pocket_pivot" in r["known_warnings"]
    assert r["stop_loss_pct_from_pivot"] == -4.0         # pocket 상한 클램프


# ---------- §2 stop ----------

def test_logical_stop_binds_when_shallow_base():
    # base_low 188 → logical = (188*0.995-192.5)/192.5*100 = -2.83 → max(-7,-2.83) = -2.83 → clamp -5.0
    r = calculate_entry_params(_payload(prior_analysis={"base_low": 188.0}))
    assert r["stop_loss_pct_from_pivot"] == -5.0

def test_wide_and_loose_tightens_absolute_and_more():
    r = calculate_entry_params(_payload(prior_analysis={"risk_flags": ["wide_and_loose"], "base_low": 150.0}))
    assert r["stop_loss_pct_from_pivot"] == -5.5         # absolute 강화 binding
    assert r["suggested_weight_pct"] == 5.0              # risky 티어
    assert r["expected_target_pct"] == 15.0
    assert r["entry_window_days"] == 1

def test_logical_exceeds_floor_warning():
    # base_low 아주 깊음 → logical < -10 → clamp & 경고
    r = calculate_entry_params(_payload(prior_analysis={"base_low": 150.0}))
    assert r["stop_loss_pct_from_pivot"] == -7.0         # absolute binding (logical worse than -10)
    assert "absolute_stop_used_due_to_wide_handle" in r["known_warnings"]

def test_stop_distance_from_current_warning():
    # current 를 pivot 대비 높게 → from_current 확대
    r = calculate_entry_params(_payload(current_state={"close": 208.0, "volume": 1_600_000, "avg_volume_50d": 1_000_000}))
    assert abs(r["stop_loss_pct_from_current_price"]) > 7.5
    assert "stop_distance_from_current_price_exceeds_book_limit" in r["known_warnings"]


# ---------- §3 size ----------

def test_vcp_top_tier_and_target_25():
    r = calculate_entry_params(_payload(prior_analysis={"pattern": "vcp", "pivot_basis": "final_T_high", "confidence": 0.9}))
    assert r["suggested_weight_pct"] == 15.0
    assert r["expected_target_pct"] == 25.0
    assert r["max_chase_pct_from_pivot"] == 3.0          # D3(a) VCP 일괄

def test_flag_multipliers_cumulative_and_floor():
    flags = ["late_stage_base", "narrow_base", "extended_from_ma", "reverse_split_distortion"]
    r = calculate_entry_params(_payload(prior_analysis={"risk_flags": flags}))
    # base 7(폴백? flat_base+flags → 표준 티어 아님) → 10? 티어 조건 '무flag' 위반 → 폴백 7
    # 7 × 0.7×0.7×0.7 × 0.5 = 1.2 → floor 3.0
    assert r["suggested_weight_pct"] == 3.0
    assert "size_floored_due_to_multiple_flags" in r["known_warnings"]
    assert "size_reduced_due_to_late_stage" in r["known_warnings"]

def test_confidence_override():
    r = calculate_entry_params(_payload(prior_analysis={"confidence": 0.65}))
    assert r["suggested_weight_pct"] == 7.0              # 10 × 0.7

def test_confidence_zero_is_not_none():
    r = calculate_entry_params(_payload(prior_analysis={"confidence": 0.0}))
    assert r["suggested_weight_pct"] == 7.0              # 0.0 < 0.7 → override 적용


# ---------- §7 watch 예외 ----------

def test_breakout_from_watch_ignores_stale_unfavorable():
    r = calculate_entry_params(_payload(
        prior_analysis={"risk_flags": ["unfavorable_market_context"]},
        trigger_evaluation={"trigger_type": "breakout_from_watch", "decision": "go_now"},
    ))
    assert r["suggested_weight_pct"] == 10.0             # ×0.5 미적용, 티어도 무flag 취급
    assert r["expected_target_pct"] == 20.0
    assert r["entry_window_days"] == 3
    assert "size_reduced_due_to_unfavorable_market" not in r["known_warnings"]

def test_breakout_trigger_applies_unfavorable():
    r = calculate_entry_params(_payload(prior_analysis={"risk_flags": ["unfavorable_market_context"]}))
    assert r["suggested_weight_pct"] == 3.5              # 폴백7 × 0.5
    assert r["expected_target_pct"] == 15.0
    assert r["entry_window_days"] == 1
    assert r["max_chase_pct_from_pivot"] == 2.0
    assert r["stop_loss_pct_from_pivot"] == -5.5
    assert "size_reduced_due_to_unfavorable_market" in r["known_warnings"]


# ---------- §5/§6 기타 ----------

def test_extended_current_shortens_window():
    r = calculate_entry_params(_payload(current_state={"close": 199.0, "volume": 1_600_000, "avg_volume_50d": 1_000_000}))
    assert r["entry_window_days"] == 1                   # current > pivot*1.03
    assert "extended_from_pivot_already" in r["known_warnings"]

def test_volume_below_preferred_and_below_requirement():
    r = calculate_entry_params(_payload(current_state={"close": 192.3, "volume": 1_450_000, "avg_volume_50d": 1_000_000}))
    assert "breakout_volume_below_preferred_50pct" in r["known_warnings"]
    r2 = calculate_entry_params(_payload(current_state={"close": 192.3, "volume": 1_000_000, "avg_volume_50d": 1_000_000}))
    assert "breakout_volume_below_requirement" in r2["known_warnings"]

def test_climax_run_clamps_minimums_with_other_warning():
    r = calculate_entry_params(_payload(prior_analysis={"risk_flags": ["climax_run"]}))
    assert r["suggested_weight_pct"] == 3.0
    assert r["expected_target_pct"] == 15.0
    assert r["entry_window_days"] == 1
    assert any("climax_run" in w for w in r["other_warnings"])

def test_warning_budget_le_6():
    flags = ["late_stage_base", "thin_liquidity_us_only", "unfavorable_market_context", "wide_and_loose"]
    r = calculate_entry_params(_payload(
        prior_analysis={"risk_flags": flags, "confidence": 0.5, "base_low": 150.0},
        current_state={"close": 208.0, "volume": 900_000, "avg_volume_50d": 1_000_000},
    ))
    assert len(r["known_warnings"]) + len(r["other_warnings"]) <= 6
