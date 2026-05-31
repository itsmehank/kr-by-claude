# tests/test_gates_phase1.py
"""apply_phase1_gates — handle_quality 주입 + 2-E tier + 2-F (spec §3·§4·§5)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kr_pipeline.llm_runner import gates


def _base_result(classification="entry", confidence=0.62, risk_flags=None):
    return {
        "classification": classification,
        "confidence": confidence,
        "risk_flags": risk_flags if risk_flags is not None else [],
        "pattern": "cup_with_handle",
        "pivot_price": 100.0,
        "pivot_basis": "handle_high",
        "base_high": 100.0, "base_low": 70.0, "base_depth_pct": 30.0,
        "base_start_date": None,
    }


def test_tier1_soft_watch(monkeypatch, db):
    """handle_quality 단독 → watch 강등 + conf ≤ 0.60, entry_params 차단 없음."""
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": True, "reasons": ["deep_handle"], "weights": [], "metrics": {}})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)

    result = _base_result(classification="entry", confidence=0.80, risk_flags=[])
    out, tr = gates.apply_phase1_gates(db, "T1", datetime(2026, 1, 1, tzinfo=timezone.utc), result)

    assert out["classification"] == "watch"
    assert out["confidence"] <= 0.60
    assert "handle_quality" in out["risk_flags"]
    assert tr is not None and "2E_tier1" in tr
    assert "2E_tier2" not in tr


def test_tier2_hard_watch_with_extended(monkeypatch, db):
    """handle_quality + extended_from_ma → watch + conf ≤ 0.50."""
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": True, "reasons": ["deep_handle"], "weights": [], "metrics": {}})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)

    result = _base_result(classification="entry", confidence=0.80, risk_flags=["extended_from_ma"])
    out, tr = gates.apply_phase1_gates(db, "T2", datetime(2026, 1, 1, tzinfo=timezone.utc), result)

    assert out["classification"] == "watch"
    assert out["confidence"] <= 0.50
    assert "2E_tier2" in tr
    assert "2E_tier1" not in tr
    assert tr["2E_tier2"]["inputs"] == ["handle_quality", "extended_from_ma"]


def test_no_handle_quality_no_gate(monkeypatch, db):
    """handle_quality 미발화 → classification 변경 없음, triggered_rules 에 2-E 없음."""
    monkeypatch.setattr(gates, "compute_handle_quality", lambda *a, **k: None)
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)

    result = _base_result(classification="entry", confidence=0.80)
    out, tr = gates.apply_phase1_gates(db, "T3", datetime(2026, 1, 1, tzinfo=timezone.utc), result)

    assert out["classification"] == "entry"
    assert out["confidence"] == 0.80
    assert tr is None or "2E_tier1" not in tr and "2E_tier2" not in tr


def test_failed_breakout_recorded(monkeypatch, db):
    """2-F 발화 시 triggered_rules 에 2F_failed_breakout 기록 (classification 무관)."""
    monkeypatch.setattr(gates, "compute_handle_quality", lambda *a, **k: None)
    monkeypatch.setattr(gates, "compute_failed_breakout",
                        lambda *a, **k: {"fired": True, "K_days": 5, "trigger": "P1",
                                         "D0_date": "2026-01-01", "consecutive_below": 3,
                                         "max_close_in_window": 99.0, "pivot": 100.0})
    result = _base_result(classification="watch", confidence=0.65)
    out, tr = gates.apply_phase1_gates(db, "T4", datetime(2026, 1, 1, tzinfo=timezone.utc), result)

    assert out["classification"] == "watch"   # 2-F 는 강등 안 함, 기록만
    assert tr is not None and "2F_failed_breakout" in tr
    assert tr["2F_failed_breakout"]["trigger"] == "P1"


def test_ignore_with_handle_quality_stays_ignore(monkeypatch, db):
    """⛔ ignore + handle_quality 발화 → ignore 유지 (watch 로 승격 금지).

    monotone-combine: classification 은 most_conservative(ignore, watch) = ignore 유지.
    conf cap 은 적용됨 (min). extended_from_ma → Tier2 cap 0.50.
    """
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": True, "reasons": ["deep_handle"], "weights": [], "metrics": {}})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)

    result = _base_result(classification="ignore", confidence=0.90, risk_flags=["extended_from_ma"])
    out, tr = gates.apply_phase1_gates(db, "TIGN", datetime(2026, 1, 1, tzinfo=timezone.utc), result)

    assert out["classification"] == "ignore", "ignore 는 절대 승격 안 함"
    assert out["confidence"] <= 0.50, "extended → Tier2 conf cap 적용 (min)"
    assert "handle_quality" in out["risk_flags"], "관찰 flag 는 추가됨"
    assert tr is not None and "2E_tier2" in tr, "monotone-combine 발화 기록됨"
    assert tr["2E_tier2"]["demoted"] is False, "ignore 는 강등 아님 (verdict 그대로)"


def test_tier1_conf_none_capped(monkeypatch, db):
    """confidence=None 인 entry 도 handle_quality 발화 시 cap 값으로 설정."""
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": True, "reasons": ["deep_handle"], "weights": [], "metrics": {}})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)

    result = _base_result(classification="entry", confidence=None, risk_flags=[])
    out, tr = gates.apply_phase1_gates(db, "TCN", datetime(2026, 1, 1, tzinfo=timezone.utc), result)

    assert out["classification"] == "watch"
    assert out["confidence"] == 0.60   # Tier1 cap
    assert "2E_tier1" in tr


def test_watch_with_handle_quality_stays_watch_conf_capped(monkeypatch, db):
    """watch + handle_quality → watch 유지, conf cap 적용 (monotone-combine).

    spec §3.1: final_confidence = min(prompt_conf, backstop_cap).
    watch no-extended → Tier1 cap 0.60. 0.75 → min(0.75, 0.60) = 0.60.
    """
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": True, "reasons": ["deep_handle"], "weights": [], "metrics": {}})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)

    result = _base_result(classification="watch", confidence=0.75, risk_flags=[])
    out, tr = gates.apply_phase1_gates(db, "TWAT", datetime(2026, 1, 1, tzinfo=timezone.utc), result)

    assert out["classification"] == "watch"
    assert out["confidence"] <= 0.60, "Tier1 cap 적용: min(0.75, 0.60) = 0.60"
    assert "handle_quality" in out["risk_flags"]
    assert tr is not None and "2E_tier1" in tr, "monotone-combine 발화 기록됨"
    assert tr["2E_tier1"]["demoted"] is False, "watch 는 강등 아님 (verdict 그대로)"


def test_monotone_no_promotion_ignore_stays(monkeypatch, db):
    """ignore + handle_quality → ignore 유지 (most_conservative no-promotion)."""
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": True, "reasons": ["deep_handle"], "weights": [], "metrics": {}})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)
    result = _base_result(classification="ignore", confidence=0.90, risk_flags=[])
    out, tr = gates.apply_phase1_gates(db, "IG", datetime(2026, 1, 1, tzinfo=timezone.utc), result)
    assert out["classification"] == "ignore"          # 승격 금지
    assert out["confidence"] <= 0.60                    # conf cap 은 적용 (min)
    assert "handle_quality" in out["risk_flags"]


def test_monotone_watch_conf_capped_with_extended(monkeypatch, db):
    """LLM 이 이미 watch + handle_quality + extended → watch 유지 + conf ≤ 0.50."""
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": True, "reasons": ["deep_handle"], "weights": [], "metrics": {}})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)
    result = _base_result(classification="watch", confidence=0.80, risk_flags=["extended_from_ma"])
    out, tr = gates.apply_phase1_gates(db, "WX", datetime(2026, 1, 1, tzinfo=timezone.utc), result)
    assert out["classification"] == "watch"
    assert out["confidence"] <= 0.50
    assert "2E_tier2" in tr
