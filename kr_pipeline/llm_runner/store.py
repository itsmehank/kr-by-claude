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
               measurements)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s,
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
                json.dumps(result.get("measurements")) if result.get("measurements") is not None else None,
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
               measurements)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s,
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
                json.dumps(result.get("measurements")) if result.get("measurements") is not None else None,
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
               prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens)
            VALUES (%s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
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
    return {
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
) -> None:
    """entry_params 에 (6) 결과 INSERT (§9 → 정규화 → 저장)."""
    n = _normalize_entry_params(result)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entry_params
              (symbol, signal_at,
               entry_mode, pivot_price, trigger_price, current_price, entry_price,
               stop_loss, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis,
               expected_target_price, expected_target_pct, risk_reward_ratio,
               position_size_pct, position_size_basis,
               pattern_basis, entry_window_days, max_chase_pct_from_pivot,
               breakout_volume_requirement, observed_breakout_volume_ratio,
               known_warnings, other_warnings, notes,
               trigger_evaluation_at, prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens)
            VALUES (%s, %s,
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
                symbol, signal_at,
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
