"""LLM risk_flags 허용 taxonomy (검증 SSOT).

prompts/analyze_chart_v3.md §taxonomy 와 수동 동기화 — 추가/삭제 시 양쪽.
"""
RISK_FLAGS_TAXONOMY = frozenset({
    "climax_run", "late_stage_base", "extended_from_ma", "faulty_pivot",
    "low_volume_breakout", "narrow_base", "wide_and_loose", "thin_liquidity_us_only",
    "prior_uptrend_insufficient", "volume_contraction_on_advance",
    "reverse_split_distortion", "unfavorable_market_context",
    "etf_methodology_mismatch", "handle_quality",
})  # 14종
