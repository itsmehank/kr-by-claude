"""LLM risk_flags 허용 taxonomy (검증 SSOT).

prompts/analyze_chart_v3.md §taxonomy 와 수동 동기화 — 추가/삭제 시 양쪽.
"""
RISK_FLAGS_TAXONOMY = frozenset({
    "climax_run", "late_stage_base", "extended_from_ma", "faulty_pivot",
    "low_volume_breakout", "narrow_base", "wide_and_loose", "thin_liquidity_us_only",
    "prior_uptrend_insufficient", "volume_contraction_on_advance",
    "reverse_split_distortion", "unfavorable_market_context",
    "etf_methodology_mismatch", "handle_quality",
    "topping_distribution",
    # (SECUGRP 필터 2026-09-15) Pre-Check 가 security_group 기준으로 바뀌며 신설. 구 etf_methodology_mismatch 는
    # 저장본 행에 남아 있어 삭제하지 않는다.
    "security_group_not_equity",
})  # 16종
