"""#111 확증 판정 러너 — 전환일 4주 시장대비 초과수익. 읽기전용, 1회 실행.

사전등록(LOCKED 2026-08-18):
docs/superpowers/specs/2026-08-18-issue111-minervini-forward-return-design.md
판정(§2.4): CI 하한>0 유효 / 0 포함 미입증 / 상한<0 역효과. 실행 후 LOOK_LOG 기입.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.backtest.minervini_forward import (
    BOOT_B, HORIZONS, PRIMARY_H, SEED, horizon_stats, transition_events,
    verdict_of,
)
from kr_pipeline.db.connection import connect

SPEC = "docs/superpowers/specs/2026-08-18-issue111-minervini-forward-return-design.md"


def main() -> int:
    with connect() as conn:
        events, excluded = transition_events(conn)
    primary = horizon_stats(events, PRIMARY_H)
    verdict = verdict_of(*primary["ci95"])
    out = {
        "issue": 111, "spec": SPEC, "grade": "confirmatory",
        "seed": SEED, "b": BOOT_B,
        "n_transitions_total": len(events),
        "excluded_by_horizon": {str(h): excluded[h] for h in HORIZONS},
        "primary_h20": primary, "verdict": verdict,
        "secondary": {"h40": horizon_stats(events, 40),
                      "h65": horizon_stats(events, 65)},
    }
    path = (f"data/backtest/issue111_minervini_transition_judge_"
            f"{date.today():%Y%m%d}.json")
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: out[k] for k in
                      ("n_transitions_total", "primary_h20", "verdict")},
                     ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
