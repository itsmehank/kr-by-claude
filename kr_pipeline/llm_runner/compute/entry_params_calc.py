"""C 단계(entry params) 결정론 산출 — 구 calculate_entry_params_v2_0.md §0.5~§11 이식 (#21).

같은 payload(build_for_6) → 항상 같은 §9 17필드. LLM 호출 대체.
결정 조합(사용자 확정 2026-07-12):
  D1(a) 3c_cheat 세분 포기 — pivot 은 항상 prior_analysis.pivot_price(§1.1 Scope v2.1).
        단 상류가 pattern='3c_cheat' 로 준 경우의 §2/§3/§4/§5 특칙은 유지.
  D2(a) pattern=none 은 EntryParamsRejected(fail-loud) — 폴백 규칙 폐기(실측 0건·규율 위반 신호).
  D3(a) VCP chase 는 일괄 3.0 (final-T 측정 폐기, 보수 방향).
§8.3 의 ≤6 경고 예산은 LLM 출력 억제용이었고 저장 계층에 상한이 없다 — 결정론 경로는
의무(auto-emit) 경고를 절단하지 않는다(발행 지점이 코드 경로상 각 1회로 유한).
책 근거 값(티어/배수/absolute stop)은 아래 모듈 상수가 정의 — 출처는 은퇴한 프롬프트
(RETIRED 배너본)와 01편. SSOT 승격은 소비처가 2곳 이상 생기면(checklist 맵 예약).
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

CALC_VERSION = "deterministic:entry_params_calc/v1"  # entry_params.llm_model 컬럼 표기

_STANDARD_PATTERNS = {"flat_base", "cup_with_handle", "double_bottom"}
_PP_BASE_PATTERNS = {"flat_base", "cup_with_handle", "vcp", "double_bottom"}

# §2 absolute stop (구 프롬프트 §2.1/§2.3 — wide/unfav/3c 시 강화)
_ABS_STOP_STD, _ABS_STOP_STD_TIGHT = -7.0, -5.5
_ABS_STOP_PP, _ABS_STOP_PP_TIGHT = -5.5, -4.5
_STOP_RANGE_PP = (-8.0, -4.0)
# §3.1/§3.2 base size 티어 (구 프롬프트 표)
_SIZE_TOP_STD, _SIZE_STANDARD_STD, _SIZE_RISKY, _SIZE_FALLBACK_STD = 15.0, 10.0, 5.0, 7.0
_SIZE_TOP_PP, _SIZE_STANDARD_PP, _SIZE_FALLBACK_PP = 10.0, 7.0, 5.0
_SIZE_PP_WIDE_FLOOR = 3.0  # §7: wide_and_loose → 3.0 floor (pocket pivot)

# §3.3 배수 (책 근거: Minervini pilot buy 보수화 — 구 프롬프트 §3.3 표)
_FLAG_MULT = {
    # (#74) cup_without_handle 결정론 주입 flag — shakeout 부재 보수화.
    # 실효 = fallback 7.0 × 0.7 = 4.9pp (이중 페널티 수용 — 사용자 결정 07-24,
    # 구조 재검토는 #80). specs/2026-07-24-issue74-cup-without-handle.md §4.
    "no_handle_shakeout_absent": 0.7,
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
    "no_handle_shakeout_absent": "size_reduced_due_to_no_handle_shakeout",
    "late_stage_base": "size_reduced_due_to_late_stage",
    "thin_liquidity_us_only": "size_reduced_due_to_thin_liquidity",
    "unfavorable_market_context": "size_reduced_due_to_unfavorable_market",
}

# §8 정렬용 우선순위 (앞일수록 중요 — 표시 순서만 결정, 절단 없음).
# 구 화이트리스트 16종 중 4종은 결정론 경로에서 발행 지점 자체가 없어 목록에서 제외:
#   pattern_refined_to_3c_cheat(D1a 세분 포기) · pattern_basis_inferred_from_data(D2a 거부)
#   · breakout_volume_requirement_relaxed(ge_1.3x 폐기) · stop_buffer_increased_for_
#   shake_protection(LLM 재량 항목). 이 목록은 '발생 가능 코드 전수'다.
_WARNING_PRIORITY = [
    "entry_mode_pocket_pivot",
    "stop_at_50day_ma_for_pocket_pivot",
    "absolute_stop_used_due_to_wide_handle",
    "size_floored_due_to_multiple_flags",
    "size_reduced_due_to_unfavorable_market",
    "size_reduced_due_to_no_handle_shakeout",
    "size_reduced_due_to_late_stage",
    "size_reduced_due_to_thin_liquidity",
    "breakout_volume_below_requirement",
    "breakout_volume_below_preferred_50pct",
    "extended_from_pivot_already",
    "stop_distance_from_current_price_exceeds_book_limit",
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
    # build_for_6 은 ascending 이지만 순수 함수 계약상 정렬을 자체 보장 —
    # '최근 5세션'·'최신 행' 선택이 호출자 구현 디테일에 암묵 의존하지 않게.
    rdi = sorted(payload.get("recent_daily_indicators") or [],
                 key=lambda r: r.get("date") or "")

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
    # (#74) cup_without_handle → 결정론 flag 주입(멱등, LLM 재량 아님) — 티어
    # no_flags 판정과 _FLAG_MULT 둘 다에 작용(이중 페널티 수용, 실효 4.9pp)
    if pa.get("pattern") == "cup_without_handle" \
            and "no_handle_shakeout_absent" not in raw_flags:
        raw_flags.append("no_handle_shakeout_absent")
    # §7 breakout_from_watch 예외 — stale unfavorable 의 '완화 효과 4개(size×0.5 /
    # target cap / window=1 / stop 강화)'만 미적용 (#29/#34 로 전제 성립). 예외는
    # 열거된 효과에 한정: §3 티어 조건("no risk flags")과 chase=2.0 은 raw 기준 그대로 —
    # "Never widen parameters because of a flag" (승격으로 확장 금지).
    eff_flags = set(raw_flags)
    if trig.get("trigger_type") == "breakout_from_watch":
        eff_flags.discard("unfavorable_market_context")

    known: list[str] = []
    other: list[str] = []

    # ---- §0.5 entry mode ----
    reasoning = (pa.get("reasoning") or "")
    # §0.5 명세 그대로: "pocket_pivot_entry" / "pocket pivot" 만 감지.
    # 더 넓은 "pocket_pivot" 은 부정문의 필드명 언급("no pocket_pivot_flag ...")까지
    # 매치해 pivot 이 PP일 close 로 뒤집히는 오탐을 만든다 (§11 요약문이 아니라 §0.5 가 규범).
    pp_claimed = ("pocket_pivot_entry" in reasoning) or ("pocket pivot" in reasoning)
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
        absolute = _ABS_STOP_PP_TIGHT if (wide or unfav) else _ABS_STOP_PP
        candidates = {"absolute": absolute}
        pp_low = pp_row.get("low")
        if pp_low:
            candidates["logical"] = (float(pp_low) * 0.995 - pivot) / pivot * 100
        sma50 = (rdi[-1].get("sma_50") if rdi else None)
        if sma50:
            sma50_buf = float(sma50) * 0.995
            if pivot >= sma50_buf:  # pivot < SMA-50 이면 후보 제외(fall through)
                candidates["sma50"] = (sma50_buf - pivot) / pivot * 100
        # 동률 시 sma50 우선 — §2.3 "sma50 binding 이면 경고 발행" 조문 보존
        # (max 는 첫 최대값 유지 → 우선순위 순서로 순회)
        order = [k for k in ("sma50", "logical", "absolute") if k in candidates]
        binding = max(order, key=lambda k: candidates[k])
        stop_pct = candidates[binding]
        lo, hi = _STOP_RANGE_PP
        if binding == "sma50":
            known.append("stop_at_50day_ma_for_pocket_pivot")
    else:
        absolute = _ABS_STOP_STD_TIGHT if (wide or unfav or is_3c) else _ABS_STOP_STD
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
        # §2.2 의 logical_stop_exceeded_absolute_floor 는 발행 지점이 없다(의도):
        # logical < floor(−10) < absolute 면 위 분기가 항상 absolute 를 택하므로
        # 'logical 이 −10 으로 clamp 된 경우' 자체가 도달 불능 — max() 선택 구조의 귀결.
        lo, hi = ENTRY_STOP_PCT_FROM_PIVOT_FLOOR, -5.0

    stop_clamped = not (lo <= stop_pct <= hi)  # notes 라벨용 — binding 값이 clamp 로 대체됨
    stop_pct = _r1(min(max(stop_pct, lo), hi))
    stop_price = _r2(pivot * (1 + stop_pct / 100))
    stop_from_current = _r1((stop_price - current) / current * 100)
    if abs(stop_from_current) > 7.5:
        known.append("stop_distance_from_current_price_exceeds_book_limit")

    # ---- §3 size ----
    # 티어 조건 "no risk flags" 는 raw 기준 — §7 watch 예외는 완화 4효과 미적용까지만
    # 허용하고 티어 '승격'(15/25)은 허용하지 않는다.
    no_flags = not raw_flags
    # confidence None(레거시 행): 승격 조건(≥0.8/0.85) 불충족 처리 + <0.7 감산도 미적용 —
    # '모름'은 보수(승격 없음) 쪽으로만 작용하고 벌점 근거로는 쓰지 않는다.
    conf = pa.get("confidence")
    if entry_mode == "pocket_pivot":
        if wide:
            size, tier = _SIZE_PP_WIDE_FLOOR, "pocket wide floor"  # §7 표
        elif pattern == "vcp" and conf is not None and conf >= 0.85 and no_flags:
            size, tier = _SIZE_TOP_PP, "pocket top-tier"
        elif pattern in _STANDARD_PATTERNS and no_flags:
            size, tier = _SIZE_STANDARD_PP, "pocket standard tier"
        else:
            size, tier = _SIZE_FALLBACK_PP, "pocket fallback tier"
    else:
        if pattern == "vcp" and conf is not None and conf >= 0.8 and no_flags:
            size, tier = _SIZE_TOP_STD, "top-tier"
        elif pattern in _STANDARD_PATTERNS and no_flags:
            size, tier = _SIZE_STANDARD_STD, "standard tier"
        elif is_3c or wide:
            size, tier = _SIZE_RISKY, "risky tier"
        else:
            size, tier = _SIZE_FALLBACK_STD, "fallback tier"

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
    # chase=2.0 은 §7 watch 예외 열거(4효과)에 없음 — raw 기준 그대로 적용
    if "unfavorable_market_context" in raw_flags:
        chase = min(chase, 2.0)
    chase = _r1(min(max(chase, 0.0), 5.0))

    # ---- §6 volume ----
    if entry_mode == "pocket_pivot":
        # §6.2: ratio 는 'PP 당일' volume / 50일평균 — current_state(오늘)가 아니다.
        # PP일이 최대 5세션 전일 수 있어 오늘 수치로 대체하면 시그니처 근거가 왜곡된다.
        vol, avg = pp_row.get("volume"), pp_row.get("avg_volume_50d")
    else:
        vol, avg = cs.get("volume"), cs.get("avg_volume_50d")
    ratio = None
    # vol=0 은 '검증 불능(None)'이 아니라 최악 케이스 0.0x — falsy 로 삼키지 않는다
    if vol is not None and avg is not None and float(avg) > 0:
        ratio = min(round(float(vol) / float(avg), 2), 20.0)
    if entry_mode == "pocket_pivot":
        vol_req = "pocket_pivot_signature"  # flag 산출이 signature 를 결정론 보증 — 재검증 없음
    else:
        # (#74) cup_without_handle 은 strict 표기 — 실제 차단은 B 인터셉트
        # (evaluate_pivot)가 선행하므로 여기 도달분은 이미 ≥1.5x
        vol_req = ("ge_1.5x_strict" if pattern == "cup_without_handle"
                   else "ge_1.5x_50day_avg")  # 기본 v2.1. ge_1.3x 완화 분기는 폐기
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

    # ---- §8 경고 정리 — 우선순위 정렬만. 발행 지점이 코드 경로상 각 1회라 중복 불가,
    # §8.3 의 ≤6 예산은 LLM 출력 억제용이었고 저장 계층에 상한이 없으므로
    # 의무(auto-emit) 경고를 조용히 삭제하지 않는다.
    known.sort(key=lambda w: _WARNING_PRIORITY.index(w) if w in _WARNING_PRIORITY else 99)

    # ---- notes (§10: 50–600자, entry_mode·binding·tier·양 stop_pct·auto-warnings 필수) ----
    notes = (
        f"{pattern} ({entry_mode}); pivot {pivot} -> trigger {trigger}. "
        f"Stop {stop_price}: {stop_pct}% from pivot ({binding} binding"
        + (", clamped" if stop_clamped else "")
        + f"), {stop_from_current}% from current {current}. "
        f"Size {size}% ({tier}"
        + (f"; multipliers: {', '.join(mults)}" if mults else "")
        + f"). Target {target_pct}%. Volume req {vol_req}, observed "
        + (f"{ratio}x." if ratio is not None else "n/a.")
        + (f" Auto-warnings: {', '.join(known)}." if known else " No auto-warnings.")
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
