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


def test_a_rtc63d_advisory_neutral_exposure():
    """(rtc_63d, #118 12차 ①·14차 승인 자구) 자문 입력 중립 노출 — 유령 입력 방지:
    payload 실재 필드(recent_transition_count_63d)가 프롬프트에 14차 승인 영문
    태그('predictive power unverified, exploratory origin')와 함께 존재해야 하고,
    귀속 앵커(HMMS pp.140-143 + Minervini VCP/TLSMW — TTLC 금지)가 유지돼야 한다."""
    text = _a_text()
    m = re.search(
        r"recent_transition_count_63d.{0,120}predictive power unverified"
        r".{0,40}exploratory origin",
        text, re.S,
    )
    assert m, (
        "A 프롬프트에 recent_transition_count_63d + 'predictive power unverified, "
        "exploratory origin' 태그 부재 — 중립 노출 조건(12차 ①·14차 자구) 위반"
    )
    seg = re.search(r"recent_transition_count_63d.{0,700}", text, re.S).group(0)
    assert re.search(r"HMMS pp\.\s*140-143", seg) and "TLSMW" in seg, (
        "14차 귀속 조건 위반 — 승인 앵커(O'Neil HMMS pp.140-143 주 앵커 + "
        "Minervini VCP/TLSMW 보조) 부재"
    )
    assert "TTLC" not in seg, (
        "TTLC 귀속은 14차 반려됨(소스 미확인) — 장 단위 특정+재회부 전 병기 금지"
    )


def test_a_35_normal_max_matches_ssot():
    m = re.search(r"≤\s*(\d+)\s*distribution days", _a_text())
    assert m, "§3.5 정상 진행 상한(≤ N distribution days)을 찾지 못함"
    assert int(m.group(1)) == thresholds.MARKET_DIST_NORMAL_MAX_25S


def test_a_47_pivot_has_no_add_on():
    """§4.7 표·§7: pivot = 기준 고점 **그 자체** — +0.1·+1 tick 가산 없음(2026-11-05 폐지,
    specs/2026-11-05-pivot-offset-removal.md). 책: HMMS 4판 p.118 pivot = 손잡이 고점,
    TLSMW p.223 "trades above the high of the pivot" — 가산 서술 없음(전문가 사실 확인
    2026-11-05 #253 [Q-3]·#175 [Q-1]). 가산이 있으면 결정론 핸들 검출기(`high ≥ pivot`)가
    손잡이 고점 당일을 못 잡는다(#175 명세 §7-1: 림 미회복 124행 중 101행)."""
    text = _a_text()
    assert not re.search(
        r"(range_high|handle_high|cup_high|final_T_high|mid_W_peak|절대 고점)\s*\+\s*\d", text
    ), "§4.7 표에 pivot 가산(+N)이 남아 있음"
    assert "+ $0.10 (Minervini" not in text and "base high + 1 tick" not in text, (
        "§7 에 구 '+$0.10 (Minervini's standard add-on)' / 'base high + 1 tick' 가산 지시가 남아 있음"
    )
    assert not re.search(r"^- PIVOT_PRICE_OFFSET\s*=", text, re.M), "SSOT 블록에 폐지된 PIVOT_PRICE_OFFSET 이 남아 있음"
    assert not hasattr(thresholds, "PIVOT_PRICE_OFFSET"), "thresholds.PIVOT_PRICE_OFFSET 미삭제"
    # 표 5행이 '고점 그대로' 형태로 존재
    for basis in ("range_high", "handle_high", "final_T_high", "mid_W_peak"):
        assert re.search(rf"\|\s*{basis}\s*\|\s*{basis}\s*\|", text), f"§4.7 {basis} 행이 'basis | basis' 형태가 아님"
    # 웹 미러(LlmPipelinePage 가 §4.7 표를 그대로 보여주는 손수 작성 데이터)도 같은 가드 — 리뷰 R1 발견
    web_mirror = A_PROMPT.parents[1] / "web" / "src" / "data" / "llm-pipeline-audit" / "base-patterns.ts"
    assert not re.search(r"(range_high|handle_high|절대 고점|final_T_high|mid_W_peak)\s*\+\s*\d", web_mirror.read_text(encoding="utf-8")), (
        "web/src/data/llm-pipeline-audit/base-patterns.ts PIVOT_RULES 에 '+ 0.1' 이 남아 있음"
    )
