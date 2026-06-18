"""DB 쓰기 — weekly_classification, trigger_evaluation_log, entry_params."""
from __future__ import annotations

import copy
import logging
from datetime import date, datetime, timedelta, time as dt_time
import json

from psycopg import Connection

from kr_pipeline.llm_runner.gates import apply_phase1_gates
from kr_pipeline.llm_runner.risk_flags import RISK_FLAGS_TAXONOMY

log = logging.getLogger(__name__)

_VALID_CLASSIFICATIONS = frozenset({"entry", "watch", "ignore"})
_VALID_DECISIONS = frozenset({"go_now", "wait", "abort"})


def _validate_classification(result: dict) -> str:
    c = result.get("classification")
    if c not in _VALID_CLASSIFICATIONS:
        raise ValueError(f"invalid classification: {c!r} (expected entry/watch/ignore)")
    return c


def _validate_decision(result: dict) -> str:
    d = result.get("decision")
    if d not in _VALID_DECISIONS:
        raise ValueError(f"invalid decision: {d!r} (expected go_now/wait/abort)")
    return d


def _clean_risk_flags(flags) -> list[str]:
    """RISK_FLAGS_TAXONOMY 밖 값 drop + log.warning. None/비list → []."""
    if not isinstance(flags, list):
        return []
    cleaned, dropped = [], []
    for f in flags:
        (cleaned if f in RISK_FLAGS_TAXONOMY else dropped).append(f)
    if dropped:
        log.warning("dropped unknown risk_flags: %s", dropped)
    return cleaned


def _measurements_json(result: dict) -> str | None:
    """measurements 블록에 최상위 contraction_count/contraction_depths_pct 를 병합해 JSON 문자열로.

    VCP footprint(최상위 출력)가 버려지지 않게 measurements 감사 블록에 합친다.
    measurements·contraction 둘 다 없으면 None(기존 None 동작 보존).
    """
    m = result.get("measurements")
    cc = result.get("contraction_count")
    cd = result.get("contraction_depths_pct")
    if m is None and cc is None and cd is None:
        return None
    blob = dict(m) if isinstance(m, dict) else {}
    if cc is not None:
        blob["contraction_count"] = cc
    if cd is not None:
        blob["contraction_depths_pct"] = cd
    return json.dumps(blob)


def _watch_reason(result: dict) -> str | None:
    """watch_reason 은 classification=='watch' 일 때만 저장 (그 외 None 강제).

    분류가 watch 가 아니면(혹은 phase1 게이트가 강등했으면) 사유를 비워
    'watch_reason 은 watch 일 때만' 불변식 보장 + breakout_from_watch 오발화 방지.
    """
    if result.get("classification") != "watch":
        return None
    return result.get("watch_reason")


def insert_classification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    result: dict,
    source: str,
    llm_meta: dict,
    analyzed_for_date: date | None = None,
) -> None:
    """weekly_classification 에 분류 결과 INSERT.

    저장 직전 Phase 1 2-A 후처리 게이트 적용 (handle_quality 주입 +
    2-E tier 강등 + 2-F 기록). prompt 갱신은 Phase 2 일임.

    source: 'weekend' | 'daily_delta'
    """
    _validate_classification(result)
    _original = copy.deepcopy(result)
    try:
        # SAVEPOINT 격리: 게이트 내부 SQL 오류가 트랜잭션을 aborted 로 만들면
        # 아래 INSERT 가 InFailedSqlTransaction 으로 실패해 LLM 비용을 쓴 분류가
        # 통째로 유실된다. 중첩 transaction(=savepoint)으로 fail-soft 를 실질화.
        with conn.transaction():
            result, triggered_rules = apply_phase1_gates(conn, symbol, classified_at, result)
    except Exception as e:
        log.warning(
            "[phase1-gate] failed symbol=%s — 게이트 미적용 원본 분류 저장 (fail-soft): %s",
            symbol, e,
        )
        result = _original
        triggered_rules = None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO weekly_classification
              (symbol, classified_at, analyzed_for_date, market, classification, pattern,
               pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date,
               risk_flags, confidence, reasoning,
               source,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens,
               triggered_rules,
               measurements,
               watch_reason)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s,
                    %s,
                    %s,
                    %s)
            ON CONFLICT (symbol, classified_at) DO NOTHING
            """,
            (
                symbol,
                classified_at,
                analyzed_for_date,
                market,
                result["classification"],
                result.get("pattern"),
                result.get("pivot_price"),
                result.get("pivot_basis"),
                result.get("base_high"),
                result.get("base_low"),
                result.get("base_depth_pct"),
                result.get("base_start_date"),
                json.dumps(_clean_risk_flags(result.get("risk_flags", []))),
                result.get("confidence"),
                result.get("reasoning"),
                source,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
                json.dumps(triggered_rules) if triggered_rules is not None else None,
                _measurements_json(result),
                _watch_reason(result),
            ),
        )


def insert_backfill_classification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    result: dict,
    source: str,
    llm_meta: dict,
    analyzed_for_date: date,
) -> None:
    """백필 분류 결과를 classification_backfill 에 INSERT (멱등: symbol+analyzed_for_date).

    insert_classification 과 동일하게 Phase 1 2-A 후처리 게이트 적용. freeze 는 만들지 않음.
    """
    _validate_classification(result)
    _original = copy.deepcopy(result)
    try:
        gate_at = datetime.combine(analyzed_for_date + timedelta(days=1), dt_time.min)
        # SAVEPOINT 격리 — insert_classification 과 동일 (SQL 오류 fail-soft 실질화)
        with conn.transaction():
            result, triggered_rules = apply_phase1_gates(conn, symbol, gate_at, result)
    except Exception as e:
        log.warning(
            "[phase1-gate] backfill failed symbol=%s — 게이트 미적용 원본 저장 (fail-soft): %s",
            symbol, e,
        )
        result = _original
        triggered_rules = None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO classification_backfill
              (symbol, classified_at, analyzed_for_date, market, classification, pattern,
               pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date,
               risk_flags, confidence, reasoning,
               source,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens,
               triggered_rules,
               measurements,
               watch_reason)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s,
                    %s,
                    %s,
                    %s)
            ON CONFLICT (symbol, analyzed_for_date) DO NOTHING
            """,
            (
                symbol,
                classified_at,
                analyzed_for_date,
                market,
                result["classification"],
                result.get("pattern"),
                result.get("pivot_price"),
                result.get("pivot_basis"),
                result.get("base_high"),
                result.get("base_low"),
                result.get("base_depth_pct"),
                result.get("base_start_date"),
                json.dumps(_clean_risk_flags(result.get("risk_flags", []))),
                result.get("confidence"),
                result.get("reasoning"),
                source,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
                json.dumps(triggered_rules) if triggered_rules is not None else None,
                _measurements_json(result),
                _watch_reason(result),
            ),
        )


def insert_disqualification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    reason: str = "minervini_pass=false — 미너비니 자격 상실(시스템 강등)",
    analyzed_for_date: date | None = None,
) -> None:
    """시스템 발 강등 행 직접 INSERT (LLM/Phase1 게이트 우회).

    disqualified 는 결정론 이벤트이지 LLM 분류가 아니므로 apply_phase1_gates 를 거치지 않는다.
    pattern/pivot/confidence/triggered_rules 는 NULL.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO weekly_classification
              (symbol, classified_at, analyzed_for_date, market, classification, source, reasoning)
            VALUES (%s, %s, %s, %s, 'disqualified', 'system_disqualify', %s)
            ON CONFLICT (symbol, classified_at) DO NOTHING
            """,
            (symbol, classified_at, analyzed_for_date, market, reason),
        )


def insert_trigger_log(
    conn: Connection,
    *,
    symbol: str,
    evaluated_at: datetime,
    trigger_type: str,
    close: float,
    volume: int,
    pivot_price: float,
    result: dict,
    prior_classification_at: datetime,
    llm_meta: dict,
    analyzed_for_date: date | None = None,
) -> None:
    """trigger_evaluation_log 에 (5b) 결과 INSERT."""
    decision = _validate_decision(result)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trigger_evaluation_log
              (symbol, evaluated_at, trigger_type,
               close, volume, pivot_price,
               decision, confidence, reasoning, abort_reason,
               analyzed_for_date,
               prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens)
            VALUES (%s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s,
                    %s,
                    %s, %s, %s)
            ON CONFLICT (symbol, evaluated_at) DO NOTHING
            """,
            (
                symbol,
                evaluated_at,
                trigger_type,
                close,
                volume,
                pivot_price,
                decision,
                result.get("confidence"),
                result.get("reasoning"),
                result.get("abort_reason"),
                analyzed_for_date,
                prior_classification_at,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
            ),
        )


_ENTRY_PARAMS_REQUIRED = (
    "entry_mode", "pivot_price", "trigger_price", "current_price",
    "stop_loss_price", "stop_loss_pct_from_pivot", "stop_loss_pct_from_current_price",
    "suggested_weight_pct", "expected_target_price", "expected_target_pct",
    "pattern_basis", "entry_window_days", "max_chase_pct_from_pivot",
    "breakout_volume_requirement", "observed_breakout_volume_ratio",
)


def _normalize_entry_params(result: dict) -> dict:
    """§9 LLM 출력 → entry_params 저장용 dict.

    리네임(stop_loss_price→stop_loss, suggested_weight_pct→position_size_pct),
    파생(entry_price=trigger_price, risk_reward_ratio 계산), §9 부재 메타는 None.
    필수 §9 키 누락 시 ValueError(조용한 0행 방지).
    """
    for k in _ENTRY_PARAMS_REQUIRED:
        if k not in result:
            raise ValueError(f"entry_params schema drift: missing §9 field '{k}'")
    target_pct = result["expected_target_pct"]
    stop_pct = result["stop_loss_pct_from_current_price"]
    rr = None
    if target_pct is not None and stop_pct not in (None, 0):
        rr = target_pct / abs(stop_pct)
        if abs(rr) >= 1000:  # NUMERIC(5,2) 범위 밖 → 오버플로(=조용한 실패) 방지
            rr = None
    n = {
        "entry_mode": result["entry_mode"],
        "pivot_price": result["pivot_price"],
        "trigger_price": result["trigger_price"],
        "current_price": result["current_price"],
        "entry_price": result["trigger_price"],
        "stop_loss": result["stop_loss_price"],
        "stop_loss_pct_from_pivot": result["stop_loss_pct_from_pivot"],
        "stop_loss_pct_from_current_price": result["stop_loss_pct_from_current_price"],
        "stop_loss_basis": None,
        "expected_target_price": result["expected_target_price"],
        "expected_target_pct": result["expected_target_pct"],
        "risk_reward_ratio": rr,
        "position_size_pct": result["suggested_weight_pct"],
        "position_size_basis": None,
        "pattern_basis": result["pattern_basis"],
        "entry_window_days": result["entry_window_days"],
        "max_chase_pct_from_pivot": result["max_chase_pct_from_pivot"],
        "breakout_volume_requirement": result["breakout_volume_requirement"],
        "observed_breakout_volume_ratio": result["observed_breakout_volume_ratio"],
        "known_warnings": result.get("known_warnings", []),
        # §9 는 other_warnings 를 배열로도 낼 수 있는데 컬럼은 TEXT → list/dict 면 JSON 문자열로
        # 직렬화(PG array-literal 로 어그러지게 저장되는 것 방지, known_warnings 와 일관).
        "other_warnings": _as_text(result.get("other_warnings")),
        "notes": result.get("notes"),
    }
    return _validate_entry_params_sanity(n)


# D-3 가격/부호 sanity 검증의 책 근거 범위 (calculate_entry_params_v2_0.md).
_STOP_PCT_FROM_PIVOT_FLOOR = -10.0  # §2 floor
_TARGET_PCT_RANGE = (15.0, 50.0)    # §4 clamp
_WEIGHT_RANGE = (3.0, 25.0)         # §3 final clamp
_TRIGGER_BUFFER_MAX = 1.005         # §1.3 trigger ≤ pivot×1.005


def _validate_entry_params_sanity(n: dict) -> dict:
    """매수계획 숫자의 부호·대소·범위 sanity 검증 (D-3).

    HARD(거부, ValueError): 가격 ≤ 0 / 손절가 ≥ 진입가 / 목표가 ≤ 진입가 /
        stop_pct 양수 / target_pct ≤ 0 — long 돌파 진입에서 항상 깨지는 계획.
    SOFT(경고, known_warnings 에 sanity_* 마커): 책 권장 범위 이탈(방향은 맞음).
    None(미제공)은 비교 불가라 해당 검사 skip — scope=주어진 값의 정합성.

    entry_params 는 go_now 실매수 신호에만 저장되므로 HARD 위반은 fail-closed(저장 안 함).
    """
    entry = n.get("entry_price")
    stop = n.get("stop_loss")
    target = n.get("expected_target_price")

    hard: list[str] = []
    for k in ("pivot_price", "trigger_price", "current_price", "entry_price",
              "stop_loss", "expected_target_price"):
        v = n.get(k)
        if v is not None and v <= 0:
            hard.append(f"{k}={v} (<=0)")
    if stop is not None and entry is not None and stop >= entry:
        hard.append(f"stop_loss={stop} >= entry_price={entry}")
    if target is not None and entry is not None and target <= entry:
        hard.append(f"expected_target_price={target} <= entry_price={entry}")
    sp_pivot = n.get("stop_loss_pct_from_pivot")
    sp_cur = n.get("stop_loss_pct_from_current_price")
    tp = n.get("expected_target_pct")
    if sp_pivot is not None and sp_pivot > 0:
        hard.append(f"stop_loss_pct_from_pivot={sp_pivot} (>0)")
    if sp_cur is not None and sp_cur > 0:
        hard.append(f"stop_loss_pct_from_current_price={sp_cur} (>0)")
    if tp is not None and tp <= 0:
        hard.append(f"expected_target_pct={tp} (<=0)")
    if hard:
        raise ValueError("entry_params sanity violation: " + "; ".join(hard))

    warns: list[str] = []
    if sp_pivot is not None and not (_STOP_PCT_FROM_PIVOT_FLOOR <= sp_pivot < 0.0):
        warns.append("sanity_stop_pct_from_pivot_out_of_book_range")
    if tp is not None and not (_TARGET_PCT_RANGE[0] <= tp <= _TARGET_PCT_RANGE[1]):
        warns.append("sanity_target_pct_out_of_book_range")
    wt = n.get("position_size_pct")
    if wt is not None and not (_WEIGHT_RANGE[0] <= wt <= _WEIGHT_RANGE[1]):
        warns.append("sanity_weight_out_of_book_range")
    piv, trg = n.get("pivot_price"), n.get("trigger_price")
    if piv is not None and trg is not None and not (piv < trg <= piv * _TRIGGER_BUFFER_MAX):
        warns.append("sanity_trigger_out_of_book_range")
    win = n.get("entry_window_days")
    if win is not None and win < 1:
        warns.append("sanity_entry_window_too_short")
    if warns:
        n["known_warnings"] = list(n.get("known_warnings") or []) + warns
        log.warning("entry_params soft sanity warnings %s (entry=%s stop=%s target=%s)",
                    warns, entry, stop, target)
    return n


def _as_text(v):
    """list/dict 면 JSON 문자열로, 그 외(문자열/None)는 그대로 — TEXT 컬럼 저장용."""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


def insert_entry_params(
    conn: Connection,
    *,
    symbol: str,
    signal_at: datetime,
    result: dict,
    trigger_evaluation_at: datetime,
    prior_classification_at: datetime,
    llm_meta: dict,
    analyzed_for_date: date | None = None,
) -> None:
    """entry_params 에 (6) 결과 INSERT (§9 → 정규화 → 저장)."""
    n = _normalize_entry_params(result)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entry_params
              (symbol, signal_at, analyzed_for_date,
               entry_mode, pivot_price, trigger_price, current_price, entry_price,
               stop_loss, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis,
               expected_target_price, expected_target_pct, risk_reward_ratio,
               position_size_pct, position_size_basis,
               pattern_basis, entry_window_days, max_chase_pct_from_pivot,
               breakout_volume_requirement, observed_breakout_volume_ratio,
               known_warnings, other_warnings, notes,
               trigger_evaluation_at, prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens)
            VALUES (%s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s)
            ON CONFLICT (symbol, signal_at) DO NOTHING
            """,
            (
                symbol, signal_at, analyzed_for_date,
                n["entry_mode"], n["pivot_price"], n["trigger_price"], n["current_price"], n["entry_price"],
                n["stop_loss"], n["stop_loss_pct_from_pivot"], n["stop_loss_pct_from_current_price"], n["stop_loss_basis"],
                n["expected_target_price"], n["expected_target_pct"], n["risk_reward_ratio"],
                n["position_size_pct"], n["position_size_basis"],
                n["pattern_basis"], n["entry_window_days"], n["max_chase_pct_from_pivot"],
                n["breakout_volume_requirement"], n["observed_breakout_volume_ratio"],
                json.dumps(n["known_warnings"]), n["other_warnings"], n["notes"],
                trigger_evaluation_at, prior_classification_at,
                llm_meta.get("duration_s"), llm_meta.get("input_tokens"), llm_meta.get("output_tokens"),
            ),
        )
