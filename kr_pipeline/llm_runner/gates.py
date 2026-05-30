# kr_pipeline/llm_runner/gates.py
"""Phase 1 2-A 후처리 게이트 — handle_quality 주입 + 2-E tier + 2-F.

store.insert_classification 가 저장 직전 호출. prompt 갱신은 Phase 2 일임.
risk_flags=관찰, triggered_rules=판단 이력 (중복 저장 금지).
"""
from __future__ import annotations

import logging
from typing import Optional

from psycopg import Connection

from kr_pipeline.llm_runner.compute.handle_quality import compute_handle_quality
from kr_pipeline.llm_runner.compute.failed_breakout import compute_failed_breakout

log = logging.getLogger(__name__)

TIER1_CONF_CAP = 0.60
TIER2_CONF_CAP = 0.50


def apply_phase1_gates(
    conn: Connection, symbol: str, classified_at, result: dict,
) -> tuple[dict, Optional[dict]]:
    """result 를 in-place 갱신하고 (mutated_result, triggered_rules) 반환.

    triggered_rules 는 발화 룰이 하나도 없으면 None.
    """
    triggered: dict = {}
    risk_flags = list(result.get("risk_flags", []))

    # === handle_quality (관찰 flag 주입 — classification 무관) ===
    hq = compute_handle_quality(conn, symbol, classified_at, result)
    if hq and hq.get("fired"):
        if "handle_quality" not in risk_flags:
            risk_flags.append("handle_quality")

        # === 2-E two-tier 판정 — classification == 'entry' 일 때만 강등 ===
        # ⛔ entry 가 아니면 (watch/ignore) flag 만 추가하고 강등/승격 안 함.
        #    특히 ignore 를 watch 로 승격하면 안 됨 (사용자 v5 버그 수정).
        if result.get("classification") == "entry":
            extended = "extended_from_ma" in risk_flags
            conf = result.get("confidence")

            if extended:
                # Tier 2 — hard watch
                result["classification"] = "watch"
                if conf is None or conf > TIER2_CONF_CAP:
                    result["confidence"] = TIER2_CONF_CAP
                triggered["2E_tier2"] = {
                    "fired": True,
                    "inputs": ["handle_quality", "extended_from_ma"],
                    "action": "entry_demoted_to_watch_with_entry_params_block",
                    "handle_quality_metrics": hq.get("metrics"),
                }
            else:
                # Tier 1 — soft watch
                result["classification"] = "watch"
                if conf is None or conf > TIER1_CONF_CAP:
                    result["confidence"] = TIER1_CONF_CAP
                triggered["2E_tier1"] = {
                    "fired": True,
                    "inputs": ["handle_quality"],
                    "action": "entry_demoted_to_watch",
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
