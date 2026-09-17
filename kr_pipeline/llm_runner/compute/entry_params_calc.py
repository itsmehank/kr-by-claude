"""C 단계(entry params) 결정론 산출 — 구 calculate_entry_params_v2_0.md §0.5~§11 이식 (#21).

같은 payload(build_for_6) → 항상 같은 §9 17필드. LLM 호출 대체.
결정 조합(사용자 확정 2026-07-12):
  D1(a) 3c_cheat 세분 포기 — pivot 은 항상 prior_analysis.pivot_price(§1.1 Scope v2.1).
        단 상류가 pattern='3c_cheat' 로 준 경우의 §2/§3/§4/§5 특칙은 유지.
  D2(a) pattern=none 은 EntryParamsRejected(fail-loud) — 폴백 규칙 폐기(실측 0건·규율 위반 신호).
  D3(a) VCP chase 는 일괄 3.0 (final-T 측정 폐기, 보수 방향).
§8.3 의 ≤6 경고 예산은 LLM 출력 억제용이었고 저장 계층에 상한이 없다 — 결정론 경로는
의무(auto-emit) 경고를 절단하지 않는다(발행 지점이 코드 경로상 각 1회로 유한).
(#153 2026-09-08) §2 stop·§3 size 는 **리스크 역산(Minervini TTLC Ch.8)** 으로 교체 —
stop = pivot × (1 − TRADE_STOP_INITIAL_PCT), full = min(SIZING_RISK_PER_TRADE / stop, MAX),
size = full × SIZING_PILOT_FRAC. entry_mode·flag·confidence·패턴 무관(플래그는 사이징에서
완전 제거 — 진입 게이트 역할은 불변). 구 티어(_SIZE_*)·배수(_FLAG_MULT)·no_flags 자격·
confidence ×0.7·3.0 바닥·absolute/logical/sma50 스탑 후보·클램프는 폐기(#80 superseded).
정의 원문 보존 = docs/superpowers/plans/2026-09-08-issue153-risk-backed-sizing.md §2.
"""
from __future__ import annotations

from kr_pipeline.common.thresholds import (
    BREAKOUT_VOL_FLOOR,
    BREAKOUT_VOL_PREFERRED,
    ENTRY_TARGET_PCT_MAX,
    ENTRY_TARGET_PCT_MIN,
    ENTRY_TRIGGER_BUFFER_MAX,
    ENTRY_WEIGHT_PCT_MAX,
    SIZING_PILOT_FRAC,
    SIZING_RISK_PER_TRADE,
    TRADE_STOP_INITIAL_PCT,
)

CALC_VERSION = "deterministic:entry_params_calc/v1"  # entry_params.llm_model 컬럼 표기

_STANDARD_PATTERNS = {"flat_base", "cup_with_handle", "double_bottom"}
_PP_BASE_PATTERNS = {"flat_base", "cup_with_handle", "vcp", "double_bottom"}

# §2/§3 (#153) 리스크 역산 — 상수는 전부 thresholds.py SSOT(SIZING_*·TRADE_STOP_INITIAL_PCT·
# ENTRY_WEIGHT_PCT_MAX). 모듈 사설 상수 없음.
_SIZING_METHOD = "risk_backed"

# §8 정렬용 우선순위 (앞일수록 중요 — 표시 순서만 결정, 절단 없음).
# 구 화이트리스트 16종 중 4종은 결정론 경로에서 발행 지점 자체가 없어 목록에서 제외:
#   pattern_refined_to_3c_cheat(D1a 세분 포기) · pattern_basis_inferred_from_data(D2a 거부)
#   · breakout_volume_requirement_relaxed(ge_1.3x 폐기) · stop_buffer_increased_for_
#   shake_protection(LLM 재량 항목). (#153) 스탑 후보·티어·배수 경고 6종(stop_at_50day_ma_
#   for_pocket_pivot · absolute_stop_used_due_to_wide_handle · size_floored_due_to_multiple_
#   flags · size_reduced_due_to_{unfavorable_market,no_handle_shakeout,late_stage,thin_
#   liquidity}) 도 발행 지점 소멸. 이 목록은 '발생 가능 코드 전수'다.
_WARNING_PRIORITY = [
    "entry_mode_pocket_pivot",
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
    # (#74) cup_without_handle → 결정론 flag 주입(멱등, LLM 재량 아님).
    # 사이징 효과는 #153 리스크 역산으로 대체됨 — 수치는 trading-rules 참조.
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

    # ---- §2 stop (#153 리스크 역산) ----
    # stop = 예상 매입가(pivot) × (1 − TRADE_STOP_INITIAL_PCT). entry_mode 구분 없음.
    # 관리 단계(trade_management)는 같은 8% 를 평균매입가 앵커로 적용 — 규칙 하나, 앵커만 다름.
    stop_pct = _r1(-TRADE_STOP_INITIAL_PCT * 100)
    stop_price = _r2(pivot * (1 - TRADE_STOP_INITIAL_PCT))
    binding = "risk_backed"
    stop_from_current = _r1((stop_price - current) / current * 100)
    # (#153 Q-1 판정 B) 책 한계 = TRADE_STOP_INITIAL_PCT(8%). current > pivot(추격) 일 때만 초과.
    # current == pivot 이면 정확히 −8.0 → 미발행. 구 임계 7.5 는 −7 스탑 시대의 값.
    if abs(stop_from_current) > TRADE_STOP_INITIAL_PCT * 100:
        known.append("stop_distance_from_current_price_exceeds_book_limit")

    # ---- §3 size (#153 리스크 역산, Minervini TTLC Ch.8 "backing into risk") ----
    # full = min(R / |stop|, MAX) = min(0.0125/0.08, 0.25) = 15.625%; 출력 = pilot = full × 0.5.
    # flag·confidence·패턴·entry_mode 는 사이징에 관여하지 않는다(플래그 = 진입 게이트 전용).
    # 반올림하지 않는다(15.625 / 7.8125 — 사양 원문값). DB NUMERIC(5,2) 저장 시 15.63/7.81.
    full_size = min(SIZING_RISK_PER_TRADE / TRADE_STOP_INITIAL_PCT, ENTRY_WEIGHT_PCT_MAX / 100.0) * 100
    size = full_size * SIZING_PILOT_FRAC
    risk_pct = SIZING_RISK_PER_TRADE * 100
    # 아래 두 값은 §4 target(VCP 25% 조건) 전용 — 사이징 비참여
    no_flags = not raw_flags
    conf = pa.get("confidence")

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
    # (#153) size 는 리스크 역산 고정 — 모순 flag 도 사이징을 바꾸지 않는다(target/window 만).
    if "climax_run" in eff_flags:
        target_pct, window = 15.0, 1
        target_price = _r2(pivot * (1 + target_pct / 100))
        other.append("climax_run with classification=entry — contradiction")
    if eff_flags & {"etf_methodology_mismatch", "security_group_not_equity"}:
        target_pct, window = ENTRY_TARGET_PCT_MIN, 1
        target_price = _r2(pivot * (1 + target_pct / 100))
        other.append("security_group/etf flag reached entry params — upstream filter breach")

    # ---- §8 경고 정리 — 우선순위 정렬만. 발행 지점이 코드 경로상 각 1회라 중복 불가,
    # §8.3 의 ≤6 예산은 LLM 출력 억제용이었고 저장 계층에 상한이 없으므로
    # 의무(auto-emit) 경고를 조용히 삭제하지 않는다.
    known.sort(key=lambda w: _WARNING_PRIORITY.index(w) if w in _WARNING_PRIORITY else 99)

    # ---- notes (§10: 50–600자, entry_mode·binding·사이징 산식·양 stop_pct·auto-warnings 필수) ----
    notes = (
        f"{pattern} ({entry_mode}); pivot {pivot} -> trigger {trigger}. "
        f"Stop {stop_price}: {stop_pct}% from pivot ({binding} binding), "
        f"{stop_from_current}% from current {current}. "
        f"Size {size}% (pilot {SIZING_PILOT_FRAC:g} of full {full_size}% = "
        f"R {risk_pct}% / stop {abs(stop_pct)}%, cap {ENTRY_WEIGHT_PCT_MAX:g}%; "
        f"flags {sorted(raw_flags) if raw_flags else 'none'} not applied to sizing"
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
        "suggested_weight_full_pct": full_size,
        "sizing_method": _SIZING_METHOD,
        "sizing_risk_pct": risk_pct,
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
