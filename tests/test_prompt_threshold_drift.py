# tests/test_prompt_threshold_drift.py
"""analyze_chart_v3.md 의 구조화 threshold 블록 ↔ thresholds.py SSOT 양방향 검증.
- 정합: prompt 의 모든 NAME=VALUE 가 thresholds.py 값과 일치.
- orphan: PROMPT_SYNCED 의 모든 상수가 prompt 블록에 실제 등장 (코드만 바뀌고 prompt 미반영 검출).
"""
from __future__ import annotations

import re
from pathlib import Path

from kr_pipeline.common import thresholds

PROMPT = Path(__file__).parent.parent / "prompts" / "analyze_chart_v3.md"

# prompt 에 반드시 동기화돼야 하는 SSOT 상수 (orphan 검출 기준).
PROMPT_SYNCED = [
    "CUP_DEPTH_MAX_NORMAL_PCT",
    "CUP_DEPTH_MAX_BEAR_RECOVERY_PCT",
    "CUP_PRIOR_UPTREND_MIN_PCT",
    "HANDLE_DEPTH_BULL_MIN_PCT",
    "HANDLE_DEPTH_BULL_MAX_PCT",
    "HANDLE_LEGIT_MIN_DAYS",
    "MEASUREMENT_TOLERANCE_PCT",
    "STOCK_DISTRIBUTION_COUNT_25D",
    "CLIMAX_GAIN_PCT",
    "CLIMAX_MATURITY_WEEKS",
    "CLIMAX_LATE_MATURITY_WEEKS",
    "CLIMAX_UP_DAYS_PCT",
    "TOPPING_BELOW_10W_WEEKS",
]

BLOCK_RE = re.compile(r"<!-- SSOT-THRESHOLDS -->(.*?)<!-- /SSOT-THRESHOLDS -->", re.S)
LINE_RE = re.compile(r"-\s*([A-Z0-9_]+)\s*=\s*([0-9.]+)")


def _parse_block() -> dict[str, float]:
    text = PROMPT.read_text(encoding="utf-8")
    m = BLOCK_RE.search(text)
    assert m, "analyze_chart_v3.md 에 <!-- SSOT-THRESHOLDS --> 블록이 없음"
    return {name: float(val) for name, val in LINE_RE.findall(m.group(1))}


def test_prompt_values_match_ssot():
    parsed = _parse_block()
    for name, val in parsed.items():
        assert hasattr(thresholds, name), f"prompt 에 SSOT 미존재 상수: {name}"
        assert float(getattr(thresholds, name)) == val, (
            f"drift: prompt {name}={val} ≠ SSOT {getattr(thresholds, name)}"
        )


def test_no_orphan_synced_constants():
    parsed = _parse_block()
    for name in PROMPT_SYNCED:
        assert name in parsed, f"orphan: SSOT {name} 이 prompt 블록에 미반영"
