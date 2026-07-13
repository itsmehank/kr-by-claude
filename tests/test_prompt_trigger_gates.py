"""B 프롬프트 게이트 규약 가드 (#22 코드 선계산 이관 후).

계보: #19(회복 재확인) · #29(형제 분기 flag 조건부) · #31(flag authoritative) 의
문구 가드는 #22 의 computed_gates 이관으로 supersede — 이 파일이 그 후계 가드다.
- computed_gates authoritative 선언 (재계산 금지 토큰 필수 — 근접 언급만으로는
  규약을 정반대로 뒤집어도 통과하므로)
- §3.5 회복 게이트 사유-독립(AND) — D4 거울 갭(복수 사유 동시 성립 시 재확인 누락)
  재개방 방지
- A 강등 임계(텍스트) ↔ SSOT co-anchor — B 쪽은 코드(gate_precompute)가 SSOT 를
  직접 소비하므로 A 텍스트만 drift 가드하면 양쪽이 닫힌다.
"""
import re
from pathlib import Path

from kr_pipeline.common import thresholds

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
B_PROMPT = PROMPTS / "evaluate_pivot_trigger_v1.md"
A_PROMPT = PROMPTS / "analyze_chart_v3.md"


def _b_text() -> str:
    return B_PROMPT.read_text(encoding="utf-8")


def _b_35_block() -> str:
    m = re.search(r"### 3\.5 .*?(?=\n## |\Z)", _b_text(), re.S)
    assert m, "B 프롬프트에 §3.5 섹션이 없음"
    return m.group(0)


def test_b_prompt_declares_computed_gates_authoritative():
    assert re.search(r"computed_gates.{0,400}재계산하지\s*말", _b_text(), re.S), (
        "B 프롬프트에 computed_gates authoritative 선언('재계산하지 말 것' 금지 토큰 포함) "
        "부재 — LLM 이 원시 데이터로 게이트를 재판정하면 이중 정의(#31 계열) 재발"
    )


def test_b_prompt_null_gate_blocks_go_now():
    assert re.search(r"null\s*이면\s*go_now\s*금지", _b_text()), (
        "null 게이트의 보수 처리(go_now 금지) 규약 부재 — 입력 결측 시 "
        "LLM 재량 재계산으로 회귀할 통로가 열림"
    )


def test_b_recovery_gates_reason_independent():
    """(#22 결정 C) §3.5 회복 게이트는 watch_reason 무관 AND — 사유별 조건부 분기 금지."""
    block = _b_35_block()
    assert "market_recovery_ok" in block and "tt_recovery_ok" in block, (
        "§3.5 에 회복 게이트(market_recovery_ok/tt_recovery_ok) 참조 부재"
    )
    assert re.search(r"사유-독립|watch_reason\s*무관", block), (
        "§3.5 에 사유-독립 선언 부재 — 사유별 분기로 회귀 시 D4 거울 갭 재개방"
    )
    assert re.search(r"둘 다.{0,60}(요구|충족)|둘 다 충족 필수", block, re.S), (
        "§3.5 에 두 회복 게이트 동시(AND) 요구 문구 부재"
    )
    for name in ("unfavorable_market", "marginal_tt", "valid_base_awaiting_breakout"):
        assert not re.search(r"^- `%s`:" % name, block, re.M), (
            f"§3.5 에 watch_reason 별 조건부 게이트 bullet({name}) 재등장 — "
            "사유-독립 재설계(#22)를 사유별 분기로 되돌리면 거울 갭 재발"
        )


def test_b_35_does_not_gate_on_risk_flags():
    """(#29 supersede) flag 조건부 재확인 문구가 §3.5 게이트 조건으로 재등장하면 안 된다
    — 회복 게이트가 사유-독립이므로 flag 조건부는 불필요하며, 병존 시 이중 경로."""
    block = _b_35_block()
    assert not re.search(r"unfavorable_market_context.{0,200}충족해야", block, re.S), (
        "§3.5 에 risk_flags 조건부 게이트 문구 잔존/재등장 — 사유-독립 AND 와 이중 경로"
    )


def test_b_35_no_threshold_literal_duplication():
    """§3.5 는 임계 리터럴을 재복제하지 않는다 — 판정은 computed_gates, 임계는 SSOT."""
    block = _b_35_block()
    assert not re.search(
        r"distribution_day_count_last_25_sessions`?\s*[<>=≥≤]+\s*\d", block
    ), "§3.5 에 시장 분배일 임계 리터럴 사본 — computed_gates.market_recovery_ok 로 대체할 것"


def test_a_demotion_threshold_matches_ssot():
    """A §3.5 강등 임계(>= N 텍스트)와 SSOT co-anchor 상수가 같은 N 이어야
    B 회복(코드: < N)과의 역류 구간이 닫힌 상태를 유지한다."""
    a_text = A_PROMPT.read_text(encoding="utf-8")
    a_35 = re.search(r"### 3\.5\..*?(?=\n### )", a_text, re.S)
    assert a_35, "A 프롬프트에 §3.5 섹션이 없음"
    a_m = re.search(
        r"distribution_day_count_last_25_sessions`?\s*>=\s*(\d+)", a_35.group(0)
    )
    assert a_m, "A §3.5 강등 임계(>= N)를 찾지 못함"
    assert int(a_m.group(1)) == thresholds.MARKET_DIST_DEMOTION_COUNT_25S, (
        f"임계 드리프트: A 강등 >= {a_m.group(1)} vs SSOT "
        f"MARKET_DIST_DEMOTION_COUNT_25S={thresholds.MARKET_DIST_DEMOTION_COUNT_25S}"
    )


def test_a_marginal_thresholds_match_ssot():
    """A §2 marginal 정의(<3% margin)·강등 카운트(3 or more)가 SSOT 와 일치해야
    B tt_recovery_ok(코드: all pass AND marginal < 3)와 정확한 역 관계가 유지된다."""
    a_text = A_PROMPT.read_text(encoding="utf-8")
    m_pct = re.search(r"passes by <\s*(\d+(?:\.\d+)?)% margin", a_text)
    assert m_pct, "A §2 marginal 정의(< N% margin)를 찾지 못함"
    assert float(m_pct.group(1)) == thresholds.TT_MARGIN_MARGINAL_PCT, (
        f"임계 드리프트: A marginal < {m_pct.group(1)}% vs SSOT "
        f"TT_MARGIN_MARGINAL_PCT={thresholds.TT_MARGIN_MARGINAL_PCT}"
    )
    m_cnt = re.search(r"If \*\*(\d+) or more\*\* conditions pass marginally", a_text)
    assert m_cnt, "A §2 marginal 강등 카운트(N or more)를 찾지 못함"
    assert int(m_cnt.group(1)) == thresholds.TT_MARGINAL_DEMOTION_COUNT, (
        f"임계 드리프트: A '{m_cnt.group(1)} or more' vs SSOT "
        f"TT_MARGINAL_DEMOTION_COUNT={thresholds.TT_MARGINAL_DEMOTION_COUNT}"
    )
