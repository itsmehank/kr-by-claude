# kr_pipeline/llm_runner/gates.py
"""Phase 1 2-A 후처리 게이트 — handle_quality 주입 + 2-E tier + 2-F.

store.insert_classification 가 저장 직전 호출. prompt 갱신은 Phase 2 일임.
risk_flags=관찰, triggered_rules=판단 이력 (중복 저장 금지).
"""
from __future__ import annotations

from typing import Optional

from psycopg import Connection

from kr_pipeline.llm_runner.compute.handle_quality import compute_handle_quality
from kr_pipeline.llm_runner.compute.failed_breakout import compute_failed_breakout

TIER1_CONF_CAP = 0.60
TIER2_CONF_CAP = 0.50

VERDICT_ORDER = {"ignore": 0, "watch": 1, "entry": 2}  # 낮을수록 보수


def _most_conservative(a: str, b: str) -> str:
    return a if VERDICT_ORDER.get(a, 2) <= VERDICT_ORDER.get(b, 2) else b


def apply_phase1_gates(
    conn: Connection, symbol: str, classified_at, result: dict,
) -> tuple[dict, Optional[dict]]:
    """result 를 in-place 갱신하고 (mutated_result, triggered_rules) 반환.

    triggered_rules 는 발화 룰이 하나도 없으면 None.
    confidence 가 None 이면 강등 시 cap 값 (Tier1 0.60 / Tier2 0.50) 으로 설정된다.
    """
    triggered: dict = {}
    risk_flags = list(result.get("risk_flags", []))

    # === handle_quality (관찰 flag 주입 — classification 무관) ===
    hq = compute_handle_quality(conn, symbol, classified_at, result)
    if hq and hq.get("fired"):
        if "handle_quality" not in risk_flags:
            risk_flags.append("handle_quality")

        # === backstop 강등 패키지 (monotone-combine, spec §3.1) ===
        # verdict floor = watch (승격 절대 안 함), conf cap = tier 별.
        extended = "extended_from_ma" in risk_flags
        backstop_cap = TIER2_CONF_CAP if extended else TIER1_CONF_CAP
        tier = "2E_tier2" if extended else "2E_tier1"
        inputs = ["handle_quality", "extended_from_ma"] if extended else ["handle_quality"]

        prev_verdict = result.get("classification")
        result["classification"] = _most_conservative(prev_verdict, "watch")  # ignore→ignore, watch→watch, entry→watch
        conf = result.get("confidence")
        result["confidence"] = backstop_cap if conf is None else min(conf, backstop_cap)

        triggered[tier] = {
            "fired": True,
            "inputs": inputs,
            "verdict_floor": "watch",
            "demoted": prev_verdict != result["classification"],
            "conf_cap": backstop_cap,
            "entry_params_block": extended,
            "handle_quality_metrics": hq.get("metrics"),
        }

    result["risk_flags"] = risk_flags

    # === 2-F failed_breakout (기록만, 강등 안 함) — base_start 범위 한정 ===
    fb = compute_failed_breakout(
        conn, symbol, classified_at,
        result.get("pivot_price"), result.get("base_start_date"),
    )
    if fb and fb.get("fired"):
        triggered["2F_failed_breakout"] = fb

    return result, (triggered or None)
