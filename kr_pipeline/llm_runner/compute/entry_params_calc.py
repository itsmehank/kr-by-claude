"""C 단계(entry params) 결정론 산출 — 구 calculate_entry_params_v2_0.md §0.5~§11 이식 (#21).

같은 payload(build_for_6) → 항상 같은 §9 17필드. LLM 호출 대체.
결정 조합(사용자 확정 2026-07-12):
  D1(a) 3c_cheat 세분 포기 — pivot 은 항상 prior_analysis.pivot_price(§1.1 Scope v2.1).
        단 상류가 pattern='3c_cheat' 로 준 경우의 §2/§3/§4/§5 특칙은 유지.
  D2(a) pattern=none 은 EntryParamsRejected(fail-loud) — 폴백 규칙 폐기(실측 0건·규율 위반 신호).
  D3(a) VCP chase 는 일괄 3.0 (final-T 측정 폐기, 보수 방향).
경고 예산(§8.3 ≤6)은 우선순위 절단으로 보장(결정론 발행 지점이 유한하나 극단 조합 대비).
책 근거 값(티어 15/10/7/5, 배수 0.7/0.5, absolute −7/−5.5 등)의 출처는 은퇴한 프롬프트
(RETIRED 배너본)와 01편 참조 — SSOT 승격은 소비처가 2곳 이상 생기면(checklist 맵).
"""
from __future__ import annotations

from kr_pipeline.common.thresholds import (
    BREAKOUT_VOL_FLOOR,
    BREAKOUT_VOL_PREFERRED,
    ENTRY_STOP_PCT_FROM_PIVOT_FLOOR,
    ENTRY_TARGET_PCT_MAX,
    ENTRY_TARGET_PCT_MIN,
    ENTRY_TRIGGER_BUFFER_MAX,
    ENTRY_WEIGHT_PCT_MAX,
    ENTRY_WEIGHT_PCT_MIN,
)

_STANDARD_PATTERNS = {"flat_base", "cup_with_handle", "double_bottom"}
_PP_BASE_PATTERNS = {"flat_base", "cup_with_handle", "vcp", "double_bottom"}

# §3.3 배수 (책 근거: Minervini pilot buy 보수화 — 구 프롬프트 §3.3 표)
_FLAG_MULT = {
    "late_stage_base": 0.7,
    "narrow_base": 0.7,
    "thin_liquidity_us_only": 0.7,
    "extended_from_ma": 0.7,
    "low_volume_breakout": 0.7,
    "volume_contraction_on_advance": 0.7,
    "faulty_pivot": 0.7,
    "unfavorable_market_context": 0.5,
    "reverse_split_distortion": 0.5,
}
_MULT_WARNING = {
    "late_stage_base": "size_reduced_due_to_late_stage",
    "thin_liquidity_us_only": "size_reduced_due_to_thin_liquidity",
    "unfavorable_market_context": "size_reduced_due_to_unfavorable_market",
}

# §8.3 예산 절단용 우선순위 (앞일수록 보존)
_WARNING_PRIORITY = [
    "entry_mode_pocket_pivot",
    "stop_at_50day_ma_for_pocket_pivot",
    "absolute_stop_used_due_to_wide_handle",
    "logical_stop_exceeded_absolute_floor",
    "size_floored_due_to_multiple_flags",
    "size_reduced_due_to_unfavorable_market",
    "size_reduced_due_to_late_stage",
    "size_reduced_due_to_thin_liquidity",
    "breakout_volume_below_requirement",
    "breakout_volume_below_preferred_50pct",
    "extended_from_pivot_already",
    "stop_distance_from_current_price_exceeds_book_limit",
    "pattern_refined_to_3c_cheat",          # D1(a)로 미발행 — 화이트리스트 보존용
    "pattern_basis_inferred_from_data",     # D2(a)로 미발행 — 화이트리스트 보존용
    "breakout_volume_requirement_relaxed",  # ge_1.3x 폐기로 미발행
    "stop_buffer_increased_for_shake_protection",  # LLM 재량 항목 — 결정론에선 미발행
]


class EntryParamsRejected(ValueError):
    """산출 거부 — 상류 규율 위반 입력(fail-loud). run() 루프가 종목 단위로 격리."""


def _r2(x: float) -> float:
    return round(float(x), 2)


def _r1(x: float) -> float:
    return round(float(x), 1)


def calculate_entry_params(payload: dict) -> dict:
    pa = payload.get("prior_analysis") or {}
    trig = payload.get("trigger_evaluation") or {}
    cs = payload.get("current_state") or {}
    rdi = payload.get("recent_daily_indicators") or []

    pattern = pa.get("pattern")
    pivot_prior = pa.get("pivot_price")
    if pattern in (None, "none"):
        raise EntryParamsRejected(
            f"pattern={pattern!r} — none/부재는 pivot 미확정 상태로 C 도달 자체가 상류 규율 위반 (D2a)"
        )
    if not pivot_prior or float(pivot_prior) <= 0:
        raise EntryParamsRejected(f"pivot_price={pivot_prior!r} — 산출 불가 (fail-loud)")

    current = cs.get("close")
    if not current or float(current) <= 0:
        raise EntryParamsRejected(f"current_state.close={current!r} — echo 불가 (fail-loud)")
    current = float(current)

    raw_flags = list(pa.get("risk_flags") or [])
    # §7 breakout_from_watch 예외 — stale unfavorable 미적용 (#29/#34 로 전제 성립)
    eff_flags = set(raw_flags)
    if trig.get("trigger_type") == "breakout_from_watch":
        eff_flags.discard("unfavorable_market_context")

    known: list[str] = []
    other: list[str] = []

    # ---- §0.5 entry mode ----
    reasoning = (pa.get("reasoning") or "")
    pp_claimed = ("pocket_pivot" in reasoning) or ("pocket pivot" in reasoning)
    entry_mode = "pivot_breakout"
    pp_row = None
    if pp_claimed and pattern in _PP_BASE_PATTERNS:
        recent5 = rdi[-5:]
        flagged = [r for r in recent5 if r.get("pocket_pivot_flag")]
        if flagged:
            entry_mode = "pocket_pivot"
            pp_row = flagged[-1]  # 최근 5세션 중 최신
            known.append("entry_mode_pocket_pivot")
        else:
            other.append(
                "pocket_pivot claimed in reasoning but no flag in recent indicators — "
                "using standard pivot_breakout logic"
            )

    # ---- §1 pivot / trigger ----
    if entry_mode == "pocket_pivot":
        pivot = float(pp_row.get("close") or 0)
        if pivot <= 0:
            raise EntryParamsRejected("pocket pivot day close 부재 — 산출 불가")
    else:
        pivot = float(pivot_prior)  # D1(a): 재산출 없음 — prior 그대로
    pivot = _r2(pivot)

    trigger = _r2(pivot * 1.001)
    if trigger <= pivot:  # 저가 반올림 경계 — strict > 보장
        trigger = _r2(pivot + 0.01)
    if trigger > pivot * ENTRY_TRIGGER_BUFFER_MAX:
        raise EntryParamsRejected(
            f"trigger {trigger} > pivot×{ENTRY_TRIGGER_BUFFER_MAX} — 저가 경계에서 buffer cap 위반"
        )

    is_3c = pattern == "3c_cheat"
    wide = "wide_and_loose" in eff_flags
    unfav = "unfavorable_market_context" in eff_flags

    # ---- §2 stop ----
    binding = "absolute"
    if entry_mode == "pocket_pivot":
        absolute = -4.5 if (wide or unfav) else -5.5
        candidates = {"absolute": absolute}
        pp_low = pp_row.get("low")
        if pp_low:
            candidates["logical"] = (float(pp_low) * 0.995 - pivot) / pivot * 100
        sma50 = (rdi[-1].get("sma_50") if rdi else None)
        if sma50:
            sma50_buf = float(sma50) * 0.995
            if pivot >= sma50_buf:  # pivot < SMA-50 이면 후보 제외(fall through)
                candidates["sma50"] = (sma50_buf - pivot) / pivot * 100
        binding = max(candidates, key=lambda k: candidates[k])
        stop_pct = candidates[binding]
        lo, hi = -8.0, -4.0
        if binding == "sma50":
            known.append("stop_at_50day_ma_for_pocket_pivot")
    else:
        absolute = -5.5 if (wide or unfav or is_3c) else -7.0
        base_low = pa.get("base_low")
        logical = (
            (float(base_low) * 0.995 - pivot) / pivot * 100 if base_low else None
        )  # v2.1: final_contraction_low = base_low
        if logical is not None and logical > absolute:
            binding, stop_pct = "logical", logical
        else:
            binding, stop_pct = "absolute", absolute
            if logical is not None and logical < ENTRY_STOP_PCT_FROM_PIVOT_FLOOR:
                known.append("absolute_stop_used_due_to_wide_handle")
        lo, hi = ENTRY_STOP_PCT_FROM_PIVOT_FLOOR, -5.0

    stop_pct = _r1(min(max(stop_pct, lo), hi))
    stop_price = _r2(pivot * (1 + stop_pct / 100))
    stop_from_current = _r1((stop_price - current) / current * 100)
    if abs(stop_from_current) > 7.5:
        known.append("stop_distance_from_current_price_exceeds_book_limit")

    # ---- §3 size ----
    no_flags = not eff_flags
    conf = pa.get("confidence")
    if entry_mode == "pocket_pivot":
        if pattern == "vcp" and conf is not None and conf >= 0.85 and no_flags:
            size, tier = 10.0, "pocket top-tier"
        elif pattern in _STANDARD_PATTERNS and no_flags:
            size, tier = 7.0, "pocket standard tier"
        else:
            size, tier = 5.0, "pocket fallback tier"
    else:
        if pattern == "vcp" and conf is not None and conf >= 0.8 and no_flags:
            size, tier = 15.0, "top-tier"
        elif pattern in _STANDARD_PATTERNS and no_flags:
            size, tier = 10.0, "standard tier"
        elif is_3c or wide:
            size, tier = 5.0, "risky tier"
        else:
            size, tier = 7.0, "fallback tier"

    mults = []
    for f in sorted(eff_flags):
        m = _FLAG_MULT.get(f)
        if m:
            size *= m
            mults.append(f"{f}×{m}")
            w = _MULT_WARNING.get(f)
            if w:
                known.append(w)
    if conf is not None and conf < 0.7:
        size *= 0.7
        mults.append(f"confidence {conf}×0.7")
    if size < ENTRY_WEIGHT_PCT_MIN:
        known.append("size_floored_due_to_multiple_flags")
    size = _r1(min(max(size, ENTRY_WEIGHT_PCT_MIN), ENTRY_WEIGHT_PCT_MAX))

    # ---- §4 target ----
    if (pattern == "vcp" and conf is not None and conf >= 0.85 and no_flags
            and entry_mode == "pivot_breakout"):
        target_pct = 25.0
    elif is_3c or wide:
        target_pct = 15.0
    else:
        target_pct = 20.0
    if unfav:
        target_pct = min(target_pct, 15.0)
    if entry_mode == "pocket_pivot":
        target_pct = min(target_pct, 18.0)
    bd = pa.get("base_depth_pct")
    if bd is not None and float(bd) < 8.0:
        target_pct = min(target_pct, 18.0)
    target_pct = _r1(min(max(target_pct, ENTRY_TARGET_PCT_MIN), ENTRY_TARGET_PCT_MAX))
    target_price = _r2(pivot * (1 + target_pct / 100))

    # ---- §5 window / chase ----
    window = 2 if entry_mode == "pocket_pivot" else 3
    if is_3c:
        window = min(window, 2)
    if wide:  # §7 통합표: wide_and_loose → window = 1
        window = 1
    extended_now = current > pivot * 1.03
    if "extended_from_ma" in eff_flags or extended_now:
        window = 1
        if extended_now:
            known.append("extended_from_pivot_already")
    if unfav:
        window = 1
    window = int(min(max(window, 1), 5))

    chase = 5.0
    if pattern == "vcp":
        chase = min(chase, 3.0)  # D3(a): final-T 측정 없이 일괄 보수 적용
    if "extended_from_ma" in eff_flags:
        chase = min(chase, 2.0)
    if entry_mode == "pocket_pivot":
        chase = min(chase, 3.0)
    if unfav:
        chase = min(chase, 2.0)
    chase = _r1(min(max(chase, 0.0), 5.0))

    # ---- §6 volume ----
    vol, avg = cs.get("volume"), cs.get("avg_volume_50d")
    ratio = None
    if vol and avg and float(avg) > 0:
        ratio = min(round(float(vol) / float(avg), 2), 20.0)
    if entry_mode == "pocket_pivot":
        vol_req = "pocket_pivot_signature"  # flag 산출이 signature 를 결정론 보증 — 재검증 없음
    else:
        vol_req = "ge_1.5x_50day_avg"  # v2.1 기본. ge_1.3x 완화 분기는 폐기(완화 유령 제거)
        if ratio is not None:
            if ratio < BREAKOUT_VOL_FLOOR:
                known.append("breakout_volume_below_requirement")
            elif ratio < BREAKOUT_VOL_PREFERRED:
                known.append("breakout_volume_below_preferred_50pct")

    # ---- §7 SHOULD-NOT-REACH flags ----
    if "climax_run" in eff_flags:
        size, target_pct, window = ENTRY_WEIGHT_PCT_MIN, 15.0, 1
        target_price = _r2(pivot * (1 + target_pct / 100))
        other.append("climax_run with classification=entry — contradiction")
    if "etf_methodology_mismatch" in eff_flags:
        size, target_pct, window = ENTRY_WEIGHT_PCT_MIN, ENTRY_TARGET_PCT_MIN, 1
        target_price = _r2(pivot * (1 + target_pct / 100))
        other.append("etf_methodology_mismatch reached entry params — upstream filter breach")

    # ---- §8 경고 정리 (중복 제거·우선순위·예산 ≤6) ----
    known = [w for i, w in enumerate(known) if w not in known[:i]]
    known.sort(key=lambda w: _WARNING_PRIORITY.index(w) if w in _WARNING_PRIORITY else 99)
    budget = 6 - len(other)
    known = known[: max(budget, 0)]

    # ---- notes (§10: 50–600자, entry_mode·binding·tier·양 stop_pct·auto-warnings 필수) ----
    notes = (
        f"{pattern} ({entry_mode}); pivot {pivot} -> trigger {trigger}. "
        f"Stop {stop_price}: {stop_pct}% from pivot ({binding} binding), "
        f"{stop_from_current}% from current {current}. "
        f"Size {size}% ({tier}"
        + (f"; multipliers: {', '.join(mults)}" if mults else "")
        + f"). Target {target_pct}%. Volume req {vol_req}, observed "
        + (f"{ratio}x." if ratio is not None else "n/a.")
        + (f" Auto-warnings: {', '.join(known)}." if known else " No auto-warnings.")
        + " Deterministic calc (#21) - no LLM."
    )
    notes = notes[:600]

    return {
        "entry_mode": entry_mode,
        "pivot_price": pivot,
        "trigger_price": trigger,
        "current_price": _r2(current),
        "stop_loss_price": stop_price,
        "stop_loss_pct_from_pivot": stop_pct,
        "stop_loss_pct_from_current_price": stop_from_current,
        "suggested_weight_pct": size,
        "expected_target_price": target_price,
        "expected_target_pct": target_pct,
        "pattern_basis": pattern,
        "entry_window_days": window,
        "max_chase_pct_from_pivot": chase,
        "breakout_volume_requirement": vol_req,
        "observed_breakout_volume_ratio": ratio,
        "notes": notes,
        "known_warnings": known,
        "other_warnings": other,
    }
