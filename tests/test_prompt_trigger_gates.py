"""B 프롬프트 게이트 규약 가드 (#19 회복 재확인 · #29 형제 분기 · #31 flag authoritative).

역류(03편 조건부모순 I) 재발 방지: 회복 판정이 status 라벨만 보지 않고
강등 원인(분배일 누적)을 재확인하는지, 그 임계가 A 의 강등 임계와 동치인지 강제.
"""
import re
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
B_PROMPT = PROMPTS / "evaluate_pivot_trigger_v1.md"
A_PROMPT = PROMPTS / "analyze_chart_v3.md"


def _b_unfavorable_block() -> str:
    """§3.5 watch_reason 게이트 목록에서 unfavorable_market bullet 만 추출."""
    text = B_PROMPT.read_text(encoding="utf-8")
    m = re.search(r"- `unfavorable_market`:(.*?)(?=\n- `|\n\n\*\*공통\*\*)", text, re.S)
    assert m, "B §3.5 에 unfavorable_market 게이트 bullet 이 없음"
    return m.group(1)


def test_unfavorable_market_recovery_rechecks_distribution_count():
    block = _b_unfavorable_block()
    assert "distribution_day_count_last_25_sessions" in block, (
        "unfavorable_market 회복 판정이 분배일 수를 재확인하지 않음 — "
        "status 라벨만으로 회복 판정 시 dist=5 역류(강등 사유 미해소 go_now) 재발"
    )


def test_recovery_threshold_matches_demotion_threshold():
    """B 회복 임계(< N)와 A 강등 임계(>= N)는 같은 N 이어야 역류가 정확히 닫힌다."""
    a_text = A_PROMPT.read_text(encoding="utf-8")
    a_35 = re.search(r"### 3\.5\..*?(?=\n### )", a_text, re.S)
    assert a_35, "A 프롬프트에 §3.5 섹션이 없음"
    a_m = re.search(r"distribution_day_count_last_25_sessions`?\s*>=\s*(\d+)", a_35.group(0))
    assert a_m, "A §3.5 강등 임계(>= N)를 찾지 못함"
    b_m = re.search(r"distribution_day_count_last_25_sessions`?\s*<\s*(\d+)", _b_unfavorable_block())
    assert b_m, "B 회복 임계(< N)를 찾지 못함"
    assert a_m.group(1) == b_m.group(1), (
        f"임계 드리프트: A 강등 >= {a_m.group(1)} vs B 회복 < {b_m.group(1)} — "
        "한쪽만 변경 시 역류 구간이 다시 열림"
    )


def _b_sibling_blocks() -> dict:
    """§3.5 형제 분기(valid_base·marginal_tt) bullet 추출."""
    text = B_PROMPT.read_text(encoding="utf-8")
    out = {}
    for name in ("valid_base_awaiting_breakout", "marginal_tt"):
        m = re.search(r"- `%s`:(.*?)(?=\n- `|\n\n\*\*공통\*\*)" % name, text, re.S)
        assert m, f"B §3.5 에 {name} 게이트 bullet 이 없음"
        out[name] = m.group(1)
    return out


def test_sibling_gates_recheck_market_when_flagged():
    """(#29) 형제 분기 — unfavorable_market_context flag 존재 시 시장 재확인 요구.

    사유(watch_reason)가 marginal_tt/valid_base 로 기록됐어도 flag 가 있으면
    unfavorable_market 게이트와 동일한 재확인을 거쳐야 역류 옆문이 닫힌다.
    """
    for name, block in _b_sibling_blocks().items():
        assert re.search(r"unfavorable_market_context.*?충족해야", block, re.S), (
            f"{name} 분기가 flag 조건부 시장 재확인을 '요구'하지 않음(문자열 존재만으론 부족 — "
            "방향성 토큰 '충족해야' 동반 필수) — #29 옆문 재개방"
        )


def test_sibling_gates_do_not_duplicate_threshold_literal():
    """(#29) 형제 분기는 임계 숫자를 재복제하지 않고 게이트를 참조해야 한다 —
    사본 증가 시 임계 변경이 한쪽만 반영되는 드리프트 통로가 생긴다."""
    for name, block in _b_sibling_blocks().items():
        assert not re.search(r"distribution_day_count_last_25_sessions`?\s*[<>=≥≤]+\s*\d", block), (
            f"{name} 분기에 임계 리터럴 사본 — unfavorable_market 게이트 참조로 대체할 것"
        )
        assert not re.search(r"분배일\s*\d+\s*개", block), (
            f"{name} 분기에 prose 임계 사본('분배일 N개') — 게이트 참조로 대체할 것"
        )


def test_b_prompt_declares_distribution_flag_authoritative():
    """(#31) B 는 종목 분배일을 payload 의 distribution_day_flag 로 판정해야 한다 —
    flag 언급 + 재계산 금지 취지가 없으면 LLM 이 자체 기준(0% 컷 등)으로 재계산(이중 정의)."""
    text = B_PROMPT.read_text(encoding="utf-8")
    assert re.search(r"distribution_day_flag.{0,300}재계산하지\s*말", text, re.S), (
        "B 프롬프트에 분배일 flag authoritative 선언('재계산하지 말 것' 금지 취지 포함) 부재 — "
        "근접 언급만으로는 규약을 정반대로 뒤집어도 통과하므로 금지 토큰 필수 (#31)"
    )
