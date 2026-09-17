"""SSOT security_group 계약 — 집합 분리·기준일 전진 적용·SQL 조각 파라미터.

plan: docs/superpowers/plans/2026-09-15-secugrp-universe-filter.md Task 1.
"""
from datetime import date

from kr_pipeline.common import security_group as sg


def test_sets_are_disjoint_and_unresolved_is_gated():
    assert sg.QUALIFYING_SECURITY_GROUPS == frozenset({"주권", "외국주권", "주식예탁증권"})
    assert sg.PRELOAD_EXCLUDED_SECURITY_GROUPS == frozenset({"부동산투자회사"})
    assert sg.ROW_KEPT_EXCLUDED_SECURITY_GROUPS == frozenset({"사회간접자본투융자회사", "투자회사"})
    assert not (sg.QUALIFYING_SECURITY_GROUPS & sg.PRELOAD_EXCLUDED_SECURITY_GROUPS)
    assert not (sg.QUALIFYING_SECURITY_GROUPS & sg.ROW_KEPT_EXCLUDED_SECURITY_GROUPS)
    assert not (sg.PRELOAD_EXCLUDED_SECURITY_GROUPS & sg.ROW_KEPT_EXCLUDED_SECURITY_GROUPS)
    assert sg.UNRESOLVED not in sg.QUALIFYING_SECURITY_GROUPS


def test_is_gated_out_forward_only():
    eff = sg.SECURITY_GROUP_GATE_EFFECTIVE_DATE
    assert eff == date(2026, 9, 15)
    before = date(2026, 9, 11)
    # 기준일 이전: 어떤 값이든 게이트 미적용(과거 재산출 금지)
    assert sg.is_gated_out("투자회사", before) is False
    assert sg.is_gated_out(sg.UNRESOLVED, before) is False
    # 기준일 이후: 허용 집합만 통과, UNRESOLVED·None·신설 유형은 게이트
    assert sg.is_gated_out("주권", eff) is False
    assert sg.is_gated_out("외국주권", eff) is False
    assert sg.is_gated_out("주식예탁증권", eff) is False
    assert sg.is_gated_out("투자회사", eff) is True
    assert sg.is_gated_out("사회간접자본투융자회사", eff) is True
    assert sg.is_gated_out(sg.UNRESOLVED, eff) is True
    assert sg.is_gated_out(None, eff) is True
    assert sg.is_gated_out("미래신설유형", eff) is True


def test_gate_sql_fragment_and_params():
    frag = sg.security_group_gate_sql("d", "date")
    assert "d.date >= %(gate_eff)s" in frag
    assert "%(gate_allowed)s" in frag
    assert "stocks" in frag and "d.ticker" in frag
    assert f"'{sg.UNRESOLVED}'" in frag           # 행 없음 → UNRESOLVED 로 간주(fail-closed)
    params = sg.security_group_gate_params()
    assert params["gate_eff"] == sg.SECURITY_GROUP_GATE_EFFECTIVE_DATE
    assert set(params["gate_allowed"]) == sg.QUALIFYING_SECURITY_GROUPS


def test_excluded_reason_text_mentions_group_and_noncircularity():
    t = sg.excluded_reason_text("투자회사")
    assert "security_group=투자회사" in t
    assert "book-mandated" in t
    assert "순환성 위반 아님" in t
