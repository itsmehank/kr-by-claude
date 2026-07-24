# tests/test_prompt_no_handle.py
# (#74) cup_without_handle 프롬프트 텍스트 고정 — 드리프트 방지.
# 한계: LLM 행동 검증은 재실행 비교 금지 규율상 불가 — 텍스트 검증까지(스펙 §8).
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ANALYZE = (_ROOT / "prompts" / "analyze_chart_v3.md").read_text()
_VERIFY = (_ROOT / "prompts" / "verify_analysis_v1.md").read_text()


def test_pattern_enum_contains_cup_without_handle():
    """§8.6 스키마 enum + §9 검증 목록 양쪽에 신 패턴 존재."""
    assert _ANALYZE.count("cup_without_handle") >= 6
    assert ("flat_base | cup_with_handle | cup_without_handle | vcp" in _ANALYZE), \
        "§8.6 pattern enum 누락"
    assert "`cup_with_handle`, `cup_without_handle`, `vcp`" in _ANALYZE, \
        "§9 검증 목록 누락"
    assert "10-value taxonomy" in _ANALYZE and "9-value taxonomy" not in _ANALYZE


def test_pivot_rules_cup_high():
    """§4.7 표 행 + pivot_basis enum + §7 대비 문장."""
    assert "| cup_without_handle | cup 내 절대 고점 + 0.1" in _ANALYZE
    assert "handle_high | cup_high | range_high" in _ANALYZE, "pivot_basis enum 누락"
    assert "pivot_price = high of the cup" in _ANALYZE, "§7 대비 문장 누락"


def test_gate3_recovery_boundary_and_base_forming_rewrite():
    """Gate3 0.90 래칫 분기 + §8.5 base_forming 재작성(구 문장 제거)."""
    assert "cup high × 0.90" in _ANALYZE
    assert "도달치" in _ANALYZE  # 래칫(도달치 기준) 명시
    assert "cup 우측 회복 미완" in _ANALYZE, ":540 재작성 누락"
    assert "handle shakeout 전 성급한 돌파" not in _ANALYZE, "구 근거 문장 잔존"


def test_strict_volume_footnote_scoped_to_breakout():
    """§8 각주 — '돌파를 근거로 entry 판정할 때에 한해' 스코프 한정."""
    assert "cup_without_handle 각주(#74)" in _ANALYZE
    assert "돌파를 근거로 entry 판정할 때에 한해" in _ANALYZE
    assert "strict **1.5×**" in _ANALYZE


def test_pocket_pivot_exclusion_explicit():
    """§4.5 — PP 경로로 strict 우회 불가 명기(의도적 제외)."""
    assert "pocket pivot 대체 진입 **비대상**" in _ANALYZE


def test_verify_prompt_pattern_count():
    assert "10 base 패턴" in _VERIFY and "9 base 패턴" not in _VERIFY
