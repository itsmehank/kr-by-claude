"""사전등록 동결 표본 C — 독립 검증 구간(2017-H2~2020) 100종목. **현재 미동결.**

상태: pending_draw. 사전등록 문서
(docs/superpowers/specs/2026-07-21-independent-window-backtest-prereg.md) 사용자 승인 후
`scripts/draw_sample_c.py --draw` 를 **정확히 1회** 실행해 결과를 이 목록에 붙여 넣고
FROZEN_C_STATUS 를 "frozen" 으로 바꾼다(추첨 산출물 JSON 은 data/backtest/ 에 보존).
그 전까지 CLI(profitability_cli, portfolio)는 --sample=c 실행을 거부한다.

동결 후 권위는 이 모듈 — 재추첨·라이브 재계산 금지(표본 A 드리프트 교훈,
cf. frozen_sample.py / frozen_sample_b.py).
"""
from __future__ import annotations

FROZEN_SEED_C = 20260721

FROZEN_C_STATUS = "pending_draw"   # 동결 시 "frozen"

FROZEN_SAMPLE_C: list[str] = []
