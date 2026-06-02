"""DB 쓰기 — weekly_classification, trigger_evaluation_log, entry_params."""
from __future__ import annotations

import copy
import logging
from datetime import date, datetime
import json

from psycopg import Connection

from kr_pipeline.llm_runner.gates import apply_phase1_gates

log = logging.getLogger(__name__)


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
                json.dumps(result.get("risk_flags", [])),
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
    _original = copy.deepcopy(result)
    try:
        result, triggered_rules = apply_phase1_gates(conn, symbol, classified_at, result)
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
                json.dumps(result.get("risk_flags", [])),
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
                result["decision"],
                result.get("confidence"),
                result.get("reasoning"),
                result.get("abort_reason"),
                prior_classification_at,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
            ),
        )


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
    """entry_params 에 (6) 결과 INSERT."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entry_params
              (symbol, signal_at,
               entry_mode, trigger_price, entry_price,
               stop_loss, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis,
               expected_target_price, expected_target_pct, risk_reward_ratio,
               position_size_pct, position_size_basis,
               breakout_volume_requirement, observed_breakout_volume_ratio,
               known_warnings, other_warnings, notes,
               trigger_evaluation_at, prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens)
            VALUES (%s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s)
            ON CONFLICT (symbol, signal_at) DO NOTHING
            """,
            (
                symbol,
                signal_at,
                result["entry_mode"],
                result["trigger_price"],
                result["entry_price"],
                result["stop_loss"],
                result["stop_loss_pct_from_pivot"],
                result["stop_loss_pct_from_current_price"],
                result["stop_loss_basis"],
                result["expected_target_price"],
                result["expected_target_pct"],
                result["risk_reward_ratio"],
                result["position_size_pct"],
                result["position_size_basis"],
                result["breakout_volume_requirement"],
                result["observed_breakout_volume_ratio"],
                json.dumps(result.get("known_warnings", [])),
                result.get("other_warnings"),
                result.get("notes"),
                trigger_evaluation_at,
                prior_classification_at,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
            ),
        )
