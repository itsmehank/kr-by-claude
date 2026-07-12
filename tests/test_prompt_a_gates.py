"""(#23) A 프롬프트 정량 선계산 규약 가드.

#37(B, test_prompt_trigger_gates.py 재작성)과의 파일 충돌을 피하기 위해 별도 파일.
- §2/§3.5: 선계산 값(conditions_summary / market_direction_gate) authoritative 선언
  (재계수/재계산 금지 토큰 필수 — 근접 언급만으로는 규약을 뒤집어도 통과하므로)
- §8.5 밴드·§4.7 오프셋 리터럴 ↔ SSOT co-anchor (store 사후검증이 같은 상수를 소비)
"""
import re
from pathlib import Path

from kr_pipeline.common import thresholds

A_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "analyze_chart_v3.md"


def _a_text() -> str:
    return A_PROMPT.read_text(encoding="utf-8")


def test_a_declares_marginal_count_precomputed():
    assert re.search(r"conditions_summary.{0,300}재계수하지\s*말", _a_text(), re.S), (
        "A §2 에 conditions_summary authoritative 선언(재계수 금지 토큰) 부재 — "
        "LLM 이 margin 을 직접 세면 이관 목적(계수 비결정성 제거)이 무효"
    )


def test_a_declares_market_gate_precomputed():
    assert re.search(r"market_direction_gate.{0,400}재계산하지\s*말", _a_text(), re.S), (
        "A §3.5 에 market_direction_gate authoritative 선언(재계산 금지 토큰) 부재"
    )


def test_a_85_band_literals_match_ssot():
    """§8.5 의 0.95/1.05 리터럴은 store 사후검증(#23)이 소비하는 SSOT 와 같아야
    프롬프트 규칙과 경고 판정이 어긋나지 않는다."""
    text = _a_text()
    lo = re.search(r"pivot\s*×\s*(0\.\d+)`?\s*→?\s*`?valid_base_awaiting_breakout", text)
    assert lo, "§8.5 하단 밴드 리터럴(pivot × 0.95 → valid_base…)을 찾지 못함"
    assert float(lo.group(1)) == thresholds.GATE_PROMOTION_PRICE_RATIO
    hi = re.search(r"current\s*>\s*pivot\s*×\s*(1\.\d+)`?\s*→?\s*`?extended", text)
    assert hi, "§8.5 상단 밴드 리터럴(current > pivot × 1.05 → extended)을 찾지 못함"
    assert float(hi.group(1)) == thresholds.PIVOT_EXTENDED_BAND_MULT


def test_a_35_normal_max_matches_ssot():
    m = re.search(r"≤\s*(\d+)\s*distribution days", _a_text())
    assert m, "§3.5 정상 진행 상한(≤ N distribution days)을 찾지 못함"
    assert int(m.group(1)) == thresholds.MARKET_DIST_NORMAL_MAX_25S


def test_a_47_offset_matches_ssot():
    """§4.7 표의 +0.1 오프셋 ↔ SSOT PIVOT_PRICE_OFFSET (store 오프셋 경고와 co-anchor)."""
    m = re.search(r"range_high \+ (\d+\.\d+)", _a_text())
    assert m, "§4.7 pivot 오프셋 리터럴(range_high + 0.1)을 찾지 못함"
    assert float(m.group(1)) == thresholds.PIVOT_PRICE_OFFSET
