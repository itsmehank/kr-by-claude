# kr_pipeline/llm_runner/gates.py
"""Phase 1 2-A 후처리 게이트 — handle_quality 주입 + 2-E tier + 2-F.

store.insert_classification 가 저장 직전 호출. prompt 갱신은 Phase 2 일임.
risk_flags=관찰, triggered_rules=판단 이력 (중복 저장 금지).
"""
from __future__ import annotations

from typing import Optional

from psycopg import Connection

from kr_pipeline.common.thresholds import PIVOT_EXTENDED_BAND_MULT
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

    # === §8.5 entry 밴드 강등 (#23 재리뷰·외부 설계 검토 채택안, 2026-07-13) ===
    # entry 인데 close > pivot × PIVOT_EXTENDED_BAND_MULT(1.05) 는 §8.5 자체 규칙상
    # 올바른 분류가 watch/extended (book: O'Neil 5% 추격 한계 — HMMS Ch.11).
    # SOFT 경고만으로는 하류 방어(B extended 게이트 부재, #45) 없이 매수 신호까지
    # 통과하므로 결정론 강등 — 조용한 보정이 아니라 triggered_rules 감사 기록이 남는
    # 시끄러운 보정(발생률은 triggered_rules->'8_5_extended_band' 로 측정, 높으면
    # §8.5 프롬프트 결함 신호). 결정론 산술(오탐 0)이라 관찰 기간 없이 즉시 적용.
    # 강등 목적지 watch/extended 는 §8.5 기존 enum — extended 는 ALLOWED_WATCH_REASONS
    # 밖(설계 의도: 추격 구간은 fresh cross 재트리거 비대상, 다음 주말 재분류로 복귀).
    pv = result.get("pivot_price")
    if result.get("classification") == "entry" and pv:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(adj_close, close) FROM daily_prices "
                "WHERE ticker = %s AND date <= %s ORDER BY date DESC LIMIT 1",
                (symbol, classified_at),
            )
            row = cur.fetchone()
        close = float(row[0]) if row and row[0] else None
        if close is not None and close > float(pv) * PIVOT_EXTENDED_BAND_MULT:
            prev_verdict = result.get("classification")
            result["classification"] = "watch"
            result["watch_reason"] = "extended"  # §8.5 기존 enum — 신규 발명 없음
            conf = result.get("confidence")
            result["confidence"] = (
                TIER2_CONF_CAP if conf is None else min(conf, TIER2_CONF_CAP)
            )  # extended 계열은 2E tier2 와 동일 cap — 신규 숫자 발명 없음
            triggered["8_5_extended_band"] = {
                "fired": True,
                "inputs": ["close", "pivot_price"],
                "close": close,
                "pivot_price": float(pv),
                "band_mult": PIVOT_EXTENDED_BAND_MULT,
                "verdict_floor": "watch",
                "demoted": prev_verdict != result["classification"],
                "conf_cap": TIER2_CONF_CAP,
            }

    # === 2-F failed_breakout (기록만, 강등 안 함) — base_start 범위 한정 ===
    fb = compute_failed_breakout(
        conn, symbol, classified_at,
        result.get("pivot_price"), result.get("base_start_date"),
    )
    if fb and fb.get("fired"):
        triggered["2F_failed_breakout"] = fb

    return result, (triggered or None)
