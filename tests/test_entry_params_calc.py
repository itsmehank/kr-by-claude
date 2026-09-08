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
    # (#153) 리스크 역산: stop = pivot×0.92, size = pilot 7.8125 (full 15.625)
    assert r["stop_loss_pct_from_pivot"] == -8.0
    assert r["stop_loss_price"] == round(192.50 * (1 - 0.08), 2)  # 모듈 공식과 동일 경로(부동소수 표기 차 방지)
    assert r["suggested_weight_pct"] == 7.8125
    assert r["suggested_weight_full_pct"] == 15.625 and r["sizing_method"] == "risk_backed"
    assert r["expected_target_pct"] == 20.0
    assert r["entry_window_days"] == 3
    assert r["max_chase_pct_from_pivot"] == 5.0
    assert r["breakout_volume_requirement"] == "ge_1.5x_50day_avg"
    assert r["observed_breakout_volume_ratio"] == 1.6
    assert 50 <= len(r["notes"]) <= 600
    # (#153 Q-1 판정 B) 경고 임계 = TRADE_STOP_INITIAL_PCT(8%) — current(192.30) < pivot 인 정상
    # 케이스는 |stop_from_current| = 7.9 < 8 → 미발행.
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
         "sma_50": 180.0, "pocket_pivot_flag": False,
         "volume": 800_000, "avg_volume_50d": 1_000_000}
        for d in range(11, 20)
    ]
    rdi.append({"date": "2026-05-20", "close": 192.0, "low": 189.5,
                "sma_50": 185.0, "pocket_pivot_flag": True,
                "volume": 2_100_000, "avg_volume_50d": 1_000_000})
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
    assert r["stop_loss_pct_from_pivot"] == -8.0         # (#153) entry_mode 무관 −8%
    assert r["suggested_weight_pct"] == 7.8125            # (#153) 리스크 역산 파일럿(모드 무관)
    # §6.2: ratio 는 PP '당일' volume/50일평균 — current_state(오늘 1.6x)가 아니라 PP일 2.1x
    assert r["observed_breakout_volume_ratio"] == 2.1


def test_pocket_pivot_wide_and_loose_does_not_change_size():
    # (#153) 구 §7 표의 wide_and_loose → 3.0 floor 폐기 — 플래그는 사이징 비참여
    r = calculate_entry_params(_pp_payload(prior_analysis={
        "reasoning": "pocket_pivot_entry within flat base", "confidence": 0.8,
        "risk_flags": ["wide_and_loose"]}))
    assert r["entry_mode"] == "pocket_pivot"
    assert r["suggested_weight_pct"] == 7.8125
    assert r["entry_window_days"] == 1                   # 진입 가드(window) 역할은 불변


def test_pp_field_name_mention_does_not_trigger_pp_mode():
    # §0.5 명세는 "pocket_pivot_entry" / "pocket pivot" — 부정문의 필드명 언급
    # ("no pocket_pivot_flag ...")이 감지로 오인되면 pivot 이 PP일 close 로 뒤집힌다.
    r = calculate_entry_params(_pp_payload(prior_analysis={
        "reasoning": "no pocket_pivot_flag in window; standard breakout", "confidence": 0.8}))
    assert r["entry_mode"] == "pivot_breakout"
    assert r["pivot_price"] == 192.50


def test_rdi_order_invariance():
    # build_for_6 은 ascending 을 주지만 순수 함수 계약상 순서 의존이면 재사용 표면에서 조용히 어긋남
    p = _pp_payload()
    p_desc = _pp_payload()
    p_desc["recent_daily_indicators"] = list(reversed(p_desc["recent_daily_indicators"]))
    assert calculate_entry_params(p) == calculate_entry_params(p_desc)


def test_pocket_pivot_claimed_but_no_flag_falls_back_standard():
    p = _pp_payload()
    for row in p["recent_daily_indicators"]:
        row["pocket_pivot_flag"] = False
    r = calculate_entry_params(p)
    assert r["entry_mode"] == "pivot_breakout"
    assert any("pocket_pivot claimed" in w for w in r["other_warnings"])
    assert r["pivot_price"] == 192.50                    # prior pivot 복귀


def test_pocket_pivot_sma50_no_longer_a_stop_candidate():
    # (#153) sma50 스탑 후보 폐기 — SMA50 이 pivot 바로 아래여도 스탑은 pivot×0.92
    p = _pp_payload()
    p["recent_daily_indicators"][-1]["sma_50"] = 191.0
    r = calculate_entry_params(p)
    assert "stop_at_50day_ma_for_pocket_pivot" not in r["known_warnings"]
    assert r["stop_loss_pct_from_pivot"] == -8.0
    assert r["stop_loss_price"] == round(192.0 * 0.92, 2)


# ---------- §2 stop ----------

def test_stop_is_fixed_8pct_from_pivot_regardless_of_base_low():
    # (#153) logical(base_low×0.995) 후보 폐기 — 얕은 베이스도 깊은 베이스도 pivot×0.92
    for bl in (188.0, 150.0):
        r = calculate_entry_params(_payload(prior_analysis={"base_low": bl}))
        assert r["stop_loss_pct_from_pivot"] == -8.0
        assert r["stop_loss_price"] == round(192.5 * 0.92, 2)
        assert "absolute_stop_used_due_to_wide_handle" not in r["known_warnings"]

def test_wide_and_loose_keeps_guards_but_not_sizing_or_stop():
    r = calculate_entry_params(_payload(prior_analysis={"risk_flags": ["wide_and_loose"], "base_low": 150.0}))
    assert r["stop_loss_pct_from_pivot"] == -8.0         # (#153) 스탑 강화(−5.5) 폐기
    assert r["suggested_weight_pct"] == 7.8125            # (#153) risky 티어 5.0 폐기
    assert r["expected_target_pct"] == 15.0              # target 규칙 불변
    assert r["entry_window_days"] == 1                   # window 가드 불변

def test_stop_distance_from_current_warning_only_when_chasing():
    # (#153 Q-1 B) current > pivot(추격) 이면 |from_current| > 8 → 발행; current == pivot 이면
    # 정확히 −8.0 → 미발행; current < pivot 이면 미발행.
    r = calculate_entry_params(_payload(current_state={"close": 208.0, "volume": 1_600_000, "avg_volume_50d": 1_000_000}))
    assert abs(r["stop_loss_pct_from_current_price"]) > 8.0
    assert "stop_distance_from_current_price_exceeds_book_limit" in r["known_warnings"]
    r_eq = calculate_entry_params(_payload(current_state={"close": 192.5, "volume": 1_600_000, "avg_volume_50d": 1_000_000}))
    assert r_eq["stop_loss_pct_from_current_price"] == -8.0
    assert "stop_distance_from_current_price_exceeds_book_limit" not in r_eq["known_warnings"]
    r_lo = calculate_entry_params(_payload(current_state={"close": 190.0, "volume": 1_600_000, "avg_volume_50d": 1_000_000}))
    assert "stop_distance_from_current_price_exceeds_book_limit" not in r_lo["known_warnings"]


# ---------- §3 size ----------

def test_vcp_top_tier_gone_but_target_25_kept():
    r = calculate_entry_params(_payload(prior_analysis={"pattern": "vcp", "pivot_basis": "final_T_high", "confidence": 0.9}))
    assert r["suggested_weight_pct"] == 7.8125            # (#153) top-tier 15 폐기
    assert r["expected_target_pct"] == 25.0              # §4 target 규칙 불변(no_flags 는 target 전용)
    assert r["max_chase_pct_from_pivot"] == 3.0          # D3(a) VCP 일괄

def test_risk_backed_sizing_fields_and_arithmetic():
    # full = min(1.25/8, 25) = 15.625 → 15.625(2dp); pilot = 7.8125 → 7.81; risk = 1.25
    r = calculate_entry_params(_payload())
    assert r["suggested_weight_full_pct"] == 15.625
    assert r["suggested_weight_pct"] == 7.8125
    assert r["sizing_method"] == "risk_backed"
    assert r["sizing_risk_pct"] == 1.25
    assert r["stop_loss_pct_from_pivot"] == -8.0
    assert r["stop_loss_price"] == round(192.5 * 0.92, 2)
    assert "risk_backed binding" in r["notes"] and "pilot 0.5 of full 15.625%" in r["notes"]

def test_flags_do_not_touch_sizing_anymore():
    flags = ["late_stage_base", "narrow_base", "extended_from_ma", "reverse_split_distortion"]
    r = calculate_entry_params(_payload(prior_analysis={"risk_flags": flags}))
    assert r["suggested_weight_pct"] == 7.8125            # 구 3.0 바닥 포화 → 폐기
    for w in ("size_floored_due_to_multiple_flags", "size_reduced_due_to_late_stage"):
        assert w not in r["known_warnings"]
    assert "not applied to sizing" in r["notes"]

def test_confidence_does_not_touch_sizing():
    for conf in (0.65, 0.0, None):
        r = calculate_entry_params(_payload(prior_analysis={"confidence": conf}))
        assert r["suggested_weight_pct"] == 7.8125        # 구 ×0.7 감액 폐기


# ---------- §7 watch 예외 ----------

def test_breakout_from_watch_ignores_stale_unfavorable():
    # §7 예외는 size×0.5 / target cap / window=1 / stop 강화 4개만 열거 —
    # 티어 조건(§3.1 "no risk flags")은 raw flags 로 판정(승격 없음 → 폴백 7.0),
    # chase=2.0 은 예외 목록에 없으므로 그대로 적용.
    r = calculate_entry_params(_payload(
        prior_analysis={"risk_flags": ["unfavorable_market_context"]},
        trigger_evaluation={"trigger_type": "breakout_from_watch", "decision": "go_now"},
    ))
    assert r["suggested_weight_pct"] == 7.8125           # (#153) 사이징은 예외·flag 무관 고정
    assert r["expected_target_pct"] == 20.0              # cap 15 미적용
    assert r["entry_window_days"] == 3                   # window=1 미적용
    assert r["max_chase_pct_from_pivot"] == 2.0          # 예외 열거 밖 — 유지
    assert r["stop_loss_pct_from_pivot"] == -8.0         # (#153) 스탑 고정
    assert "size_reduced_due_to_unfavorable_market" not in r["known_warnings"]


def test_breakout_from_watch_does_not_upgrade_vcp_to_top_tier():
    # "Never widen parameters because of a flag" — 예외가 완화를 승격으로 확장하면 위반
    r = calculate_entry_params(_payload(
        prior_analysis={"pattern": "vcp", "confidence": 0.9,
                        "risk_flags": ["unfavorable_market_context"]},
        trigger_evaluation={"trigger_type": "breakout_from_watch", "decision": "go_now"},
    ))
    assert r["suggested_weight_pct"] == 7.8125            # (#153) 사이징은 flag·watch 예외 무관
    assert r["expected_target_pct"] == 20.0              # 25 승격 금지(target 규칙 불변)

def test_breakout_trigger_applies_unfavorable():
    r = calculate_entry_params(_payload(prior_analysis={"risk_flags": ["unfavorable_market_context"]}))
    assert r["suggested_weight_pct"] == 7.8125            # (#153) ×0.5 폐기
    assert r["expected_target_pct"] == 15.0              # target cap 불변
    assert r["entry_window_days"] == 1                   # window 불변
    assert r["max_chase_pct_from_pivot"] == 2.0          # chase 불변
    assert r["stop_loss_pct_from_pivot"] == -8.0         # (#153) 스탑 강화 폐기
    assert "size_reduced_due_to_unfavorable_market" not in r["known_warnings"]


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

def test_climax_run_clamps_target_window_not_size_with_other_warning():
    r = calculate_entry_params(_payload(prior_analysis={"risk_flags": ["climax_run"]}))
    assert r["suggested_weight_pct"] == 7.8125            # (#153) size 는 모순 flag 에도 고정
    assert r["expected_target_pct"] == 15.0
    assert r["entry_window_days"] == 1
    assert any("climax_run" in w for w in r["other_warnings"])

def test_volume_zero_emits_below_requirement():
    # 데이터 결함으로 volume=0 이면 '검증 불능(null)'이 아니라 최악 케이스 0.0x — 경고 필수
    r = calculate_entry_params(_payload(current_state={"close": 192.3, "volume": 0, "avg_volume_50d": 1_000_000}))
    assert r["observed_breakout_volume_ratio"] == 0.0
    assert "breakout_volume_below_requirement" in r["known_warnings"]


def test_warnings_never_silently_truncated():
    # §8.3 ≤6 은 LLM 출력 예산이었음 — 결정론 경로는 의무(auto-emit) 경고를 삭제하지 않는다.
    # (#153) 사이징·스탑 후보 경고 6종은 발행 지점 소멸 — 이 조합의 known 은 3건:
    # extended_from_pivot_already + stop_distance + below_requirement. 전부 남아야 한다.
    flags = ["late_stage_base", "thin_liquidity_us_only", "unfavorable_market_context", "wide_and_loose"]
    r = calculate_entry_params(_payload(
        prior_analysis={"risk_flags": flags, "confidence": 0.5, "base_low": 150.0},
        current_state={"close": 208.0, "volume": 900_000, "avg_volume_50d": 1_000_000},
    ))
    assert len(r["known_warnings"]) == 3
    assert "extended_from_pivot_already" in r["known_warnings"]
    assert "stop_distance_from_current_price_exceeds_book_limit" in r["known_warnings"]


# ---------- (#74) cup_without_handle 보수 장치 ----------

def test_no_handle_flag_injected_but_sizing_unchanged():
    """pattern=cup_without_handle → flag 결정론 주입은 유지(진입 게이트·strict 거래량 표기),
    (#153) 사이징 감액(구 4.9pp)은 폐기 — F1~F3 제재는 코호트 R×0.5 로 재매핑(plan §6)."""
    r = calculate_entry_params(_payload(prior_analysis={
        "pattern": "cup_without_handle", "pivot_basis": "cup_high"}))
    assert r["suggested_weight_pct"] == 7.8125
    assert "size_reduced_due_to_no_handle_shakeout" not in r["known_warnings"]
    assert r["breakout_volume_requirement"] == "ge_1.5x_strict"
    assert "no_handle_shakeout_absent" in r["notes"]     # flag 주입 사실은 notes 에 남는다


def test_no_handle_flag_injection_idempotent():
    """flag 가 이미 있어도(재실행·수동 포함) 출력 동일 — 멱등."""
    a = calculate_entry_params(_payload(prior_analysis={
        "pattern": "cup_without_handle", "pivot_basis": "cup_high"}))
    b = calculate_entry_params(_payload(prior_analysis={
        "pattern": "cup_without_handle", "pivot_basis": "cup_high",
        "risk_flags": ["no_handle_shakeout_absent"]}))
    assert a["suggested_weight_pct"] == b["suggested_weight_pct"] == 7.8125
    assert a["breakout_volume_requirement"] == b["breakout_volume_requirement"]


def test_no_handle_other_patterns_untouched():
    """타 패턴엔 flag 미주입 — 기존 vol_req 불변, 사이징은 전 패턴 동일."""
    r = calculate_entry_params(_payload())
    assert r["breakout_volume_requirement"] == "ge_1.5x_50day_avg"
    assert r["suggested_weight_pct"] == 7.8125


def test_cup_high_pivot_basis_in_store_tick_validation():
    """pivot_basis='cup_high' 가 store +tick 사후검증 대상에 등재 (#74 §2)."""
    from kr_pipeline.llm_runner.store import _PIVOT_TABLE_BASES
    assert "cup_high" in _PIVOT_TABLE_BASES
