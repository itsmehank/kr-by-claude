"""B §3.5 unfavorable_market 회복 게이트 — 분배일 재확인 가드 (#19).

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
    a_m = re.search(r"distribution_day_count_last_25_sessions`?\s*>=\s*(\d+)", a_text)
    assert a_m, "A §3.5 강등 임계(>= N)를 찾지 못함"
    b_m = re.search(r"distribution_day_count_last_25_sessions`?\s*<\s*(\d+)", _b_unfavorable_block())
    assert b_m, "B 회복 임계(< N)를 찾지 못함"
    assert a_m.group(1) == b_m.group(1), (
        f"임계 드리프트: A 강등 >= {a_m.group(1)} vs B 회복 < {b_m.group(1)} — "
        "한쪽만 변경 시 역류 구간이 다시 열림"
    )
