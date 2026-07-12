# tests/test_prompt_threshold_drift.py
"""prompt 의 구조화 threshold 블록 ↔ thresholds.py SSOT 양방향 검증 (P1-7: 3개 프롬프트 전체).

- 정합: prompt 블록의 모든 NAME=VALUE 가 thresholds.py 값과 일치.
- orphan: 각 프롬프트의 PROMPT_SYNCED 상수가 블록에 실제 등장 (코드만 바뀌고 prompt 미반영 검출).

주의: 블록에는 '코드가 소비하는' 값만 나열한다 — 프롬프트 전용 판단값
(예: evaluate 의 1.2~1.4 wait 밴드, entry 의 0.995 버퍼)은 SSOT 비등재 원칙
(과등재 방지, thresholds.py docstring 참조).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from kr_pipeline.common import thresholds

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# 프롬프트별: (파일명, 블록에 반드시 동기화돼야 하는 SSOT 상수 목록)
PROMPT_SYNCED: dict[str, list[str]] = {
    "analyze_chart_v3.md": [
        "CUP_DEPTH_MAX_NORMAL_PCT",
        "CUP_DEPTH_MAX_BEAR_RECOVERY_PCT",
        "CUP_PRIOR_UPTREND_MIN_PCT",
        "HANDLE_DEPTH_BULL_MIN_PCT",
        "HANDLE_DEPTH_BULL_MAX_PCT",
        "HANDLE_LEGIT_MIN_DAYS",
        "MEASUREMENT_TOLERANCE_PCT",
        "STOCK_DISTRIBUTION_COUNT_25D",
        "STOCK_DISTRIBUTION_PCT_DOWN",
        "CLIMAX_GAIN_PCT",
        "CLIMAX_GAIN_WINDOW_WEEKS",
        "CLIMAX_MATURITY_WEEKS",
        "CLIMAX_LATE_MATURITY_WEEKS",
        "CLIMAX_UP_DAYS_PCT",
        "CLIMAX_UP_DAYS_WINDOW_MIN",
        "CLIMAX_UP_DAYS_WINDOW_MAX",
        "TOPPING_BELOW_10W_WEEKS",
        "MARKET_DIST_DEMOTION_COUNT_25S",
        "TT_MARGIN_MARGINAL_PCT",
        "TT_MARGINAL_DEMOTION_COUNT",
    ],
    "evaluate_pivot_trigger_v1.md": [
        "BREAKOUT_VOL_FLOOR",
        "GATE_PROMOTION_PRICE_RATIO",
        "BREAKOUT_VOL_WAIT_FLOOR",
        "SPREAD_WIDE_LOOSE_MULT",
        "SMA50_BREACH_RATIO",
        "STOCK_DIST_CLEAN_WINDOW_DAYS",
        "STOCK_DIST_ABORT_WINDOW_DAYS",
        "STOCK_DIST_ABORT_COUNT_5D",
        "MARKET_DIST_DEMOTION_COUNT_25S",
        "TT_MARGIN_MARGINAL_PCT",
        "TT_MARGINAL_DEMOTION_COUNT",
    ],
    "calculate_entry_params_v2_0.md": [
        "BREAKOUT_VOL_FLOOR",
        "BREAKOUT_VOL_PREFERRED",
        "ENTRY_STOP_PCT_FROM_PIVOT_FLOOR",
        "ENTRY_TARGET_PCT_MIN",
        "ENTRY_TARGET_PCT_MAX",
        "ENTRY_WEIGHT_PCT_MIN",
        "ENTRY_WEIGHT_PCT_MAX",
        "ENTRY_TRIGGER_BUFFER_MAX",
    ],
}

BLOCK_RE = re.compile(r"<!-- SSOT-THRESHOLDS -->(.*?)<!-- /SSOT-THRESHOLDS -->", re.S)
# 음수 값(예: ENTRY_STOP_PCT_FROM_PIVOT_FLOOR = -10.0) 지원
LINE_RE = re.compile(r"-\s*([A-Z0-9_]+)\s*=\s*(-?[0-9.]+)")


def _parse_block(prompt_file: str) -> dict[str, float]:
    text = (PROMPTS_DIR / prompt_file).read_text(encoding="utf-8")
    m = BLOCK_RE.search(text)
    assert m, f"{prompt_file} 에 <!-- SSOT-THRESHOLDS --> 블록이 없음"
    return {name: float(val) for name, val in LINE_RE.findall(m.group(1))}


@pytest.mark.parametrize("prompt_file", sorted(PROMPT_SYNCED))
def test_prompt_values_match_ssot(prompt_file):
    parsed = _parse_block(prompt_file)
    assert parsed, f"{prompt_file} 블록이 비어 있음"
    for name, val in parsed.items():
        assert hasattr(thresholds, name), f"{prompt_file}: prompt 에 SSOT 미존재 상수 {name}"
        assert float(getattr(thresholds, name)) == val, (
            f"drift: {prompt_file} {name}={val} ≠ SSOT {getattr(thresholds, name)}"
        )


@pytest.mark.parametrize("prompt_file", sorted(PROMPT_SYNCED))
def test_no_orphan_synced_constants(prompt_file):
    parsed = _parse_block(prompt_file)
    for name in PROMPT_SYNCED[prompt_file]:
        assert name in parsed, f"orphan: SSOT {name} 이 {prompt_file} 블록에 미반영"


def test_negative_value_parsing_supported():
    """회귀 가드: LINE_RE 가 음수 리터럴을 파싱해야 stop floor(-10.0) drift 를 잡는다."""
    assert LINE_RE.findall("- ENTRY_STOP_PCT_FROM_PIVOT_FLOOR = -10.0") == [
        ("ENTRY_STOP_PCT_FROM_PIVOT_FLOOR", "-10.0")
    ]
