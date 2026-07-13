"""TT(Trend Template) marginal 계수의 단일 정의 — A·B 공용 (#38 재리뷰).

A §2 정의: marginal = 'PASS 하면서 margin < TT_MARGIN_MARGINAL_PCT%' 인 조건.
소비처 2곳이 같은 계산을 따로 구현하면 결측 규약이 갈라져 A 강등 ↔ B 회복의
'정확한 역' 이 깨진다(실제 발생: #37/#38 초기 구현이 상반 — margin 결측 종목을
A 는 보류, B 는 회복 허용) — 여기가 유일한 정의.

- A: api/services/payload_builder._conditions_summary (conditions_summary 선계산)
- B: kr_pipeline/llm_runner/compute/gate_precompute (tt_recovery_ok)

결측 규약(보수): passed 가 None 이거나, PASS 인데 margin_pct 가 None 인 조건이
하나라도 있으면 marginal_count = None(미확정). 확정 숫자로 내보내면 데이터 결함이
A 에선 결측 감지 능력 제거, B 에선 회복을 '허용' 쪽으로 왜곡한다.
탈락(passed=False) 조건의 margin 은 정의상 무관 — 카운트 확정 유지.
"""
from __future__ import annotations

from kr_pipeline.common.thresholds import TT_MARGIN_MARGINAL_PCT


def tt_marginal_summary(conditions_detail: dict) -> dict:
    """{all_passed, marginal_count, marginal_conditions} — 각각 3상(True/False/None) 규약.

    all_passed: False(탈락 존재 — 확정) / None(passed 미산출 존재 — 미확정) / True.
    marginal_count·marginal_conditions: 결측 규약 위반 시 둘 다 None.
    """
    passes = [c.get("passed") for c in conditions_detail.values()]
    if any(p is False for p in passes):
        all_passed = False
    elif any(p is None for p in passes):
        all_passed = None
    else:
        all_passed = True

    unmeasured = any(
        c.get("passed") is None
        or (c.get("passed") is True and c.get("margin_pct") is None)
        for c in conditions_detail.values()
    )
    if unmeasured:
        return {"all_passed": all_passed, "marginal_count": None, "marginal_conditions": None}

    marginal = sorted(
        k
        for k, c in conditions_detail.items()
        if c.get("passed") is True and c["margin_pct"] < TT_MARGIN_MARGINAL_PCT
    )
    return {
        "all_passed": all_passed,
        "marginal_count": len(marginal),
        "marginal_conditions": marginal,
    }
