"""0단계 층① — #38 A 선계산(conditions_summary·market_direction_gate) 과거 재생.

backtest_classification 의 (symbol, analyzed_for_date) 전 행 — 실제 A 백필이
호출된 지점 — 에서 production 과 동일한 함수를 재생한다:
  build_minervini_detail → _conditions_summary   (§2 marginal 카운트)
  build_market_context   → _market_direction_gate (§3.5 시장 하드룰 입력)
LLM 호출 없음. DB read-only.

집계: marginal_count null 비율·demotion_trigger 발화율,
market gate 3필드(force_watch/confidence_penalty/normal_range)의 true/false/null,
재생 예외 건수. market gate 는 (market, date) 로 캐시(동일 입력 중복 계산 제거).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from kr_pipeline.db.connection import connect
from api.services.payload_builder import (
    _conditions_summary,
    _market_direction_gate,
    build_market_context,
    build_minervini_detail,
)

OUT_PATH = Path("data/verification/2026-07-17-stage0/a_precompute_replay.json")


def main() -> int:
    agg = {
        "rows": 0,
        "errors": Counter(),
        "marginal_count": Counter(),      # null | 0 | 1 | ...
        "demotion_trigger": Counter(),    # null | true | false
        "market_force_watch": Counter(),
        "market_confidence_penalty": Counter(),
        "market_normal_range": Counter(),
    }
    fired_demotions = []
    market_cache: dict[tuple, dict] = {}

    def _b(v):
        return "null" if v is None else ("true" if v else "false")

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, analyzed_for_date, market FROM backtest_classification "
                "ORDER BY analyzed_for_date, symbol"
            )
            rows = cur.fetchall()
        for symbol, sat, market in rows:
            agg["rows"] += 1
            try:
                minervini = build_minervini_detail(conn, symbol, sat)
                cs = _conditions_summary(minervini)
            except Exception as e:
                agg["errors"][f"minervini {type(e).__name__}"] += 1
                continue
            mc_key = (market, sat)
            try:
                if mc_key not in market_cache:
                    market_cache[mc_key] = _market_direction_gate(
                        build_market_context(conn, market, sat)
                    )
                mg = market_cache[mc_key]
            except Exception as e:
                agg["errors"][f"market {type(e).__name__}"] += 1
                mg = None

            mcnt = cs["marginal_count"]
            agg["marginal_count"]["null" if mcnt is None else str(mcnt)] += 1
            agg["demotion_trigger"][_b(cs["demotion_trigger"])] += 1
            if cs["demotion_trigger"]:
                fired_demotions.append({
                    "symbol": symbol, "sat": str(sat),
                    "marginal_conditions": cs["marginal_conditions"],
                })
            if mg is not None:
                agg["market_force_watch"][_b(mg.get("force_watch"))] += 1
                agg["market_confidence_penalty"][_b(mg.get("confidence_penalty"))] += 1
                agg["market_normal_range"][_b(mg.get("normal_range"))] += 1

    out = {k: (dict(v) if isinstance(v, Counter) else v) for k, v in agg.items()}
    out["demotion_fired_records"] = fired_demotions
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items()
                      if k != "demotion_fired_records"},
                     ensure_ascii=False, indent=2))
    print(f"demotion fired: {len(fired_demotions)}건")
    print(f"saved → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
