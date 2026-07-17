"""0단계 보강 — go_now 양성 경로 단건 실측 (PR #51 리뷰 후속).

수리된 재생(전체 트리거일 + stop_loss 주입)에서 §3.1 5게이트 + §3.5 회복
2게이트를 **전부 충족**하는 컨텍스트가 정확히 1건 발견됨:
  112610, 분류 토요일 2023-04-08(watch), 발동일 2023-04-14, breakout_from_watch
프롬프트 규약상 이 입력의 유일한 정답은 go_now — "자격을 갖추면 LLM 이 실제로
go_now 를 내는가"(양성 경로)를 이 1건으로 실측한다. 판독 기준(사전 고정):
  P1  decision == go_now → 양성 경로 확인.
  P2  decision != go_now → 위반은 아니나(보수 방향) 과잉 보수 신호로 리포트에
      기록 — reasoning 이 어떤 게이트/재량 근거를 드는지 판독.
결과는 JSON 저장만(관측 전용, production 테이블 미저장).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from kr_pipeline.db.connection import connect
from kr_pipeline.backtest.trigger_audit import prior_row_for
from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.llm.claude_cli import call_claude

OUT_PATH = Path("data/verification/2026-07-17-stage0/5b_gonow_probe.json")

SYMBOL, SAT, AS_OF = "112610", date(2023, 4, 8), date(2023, 4, 14)


def main() -> int:
    with connect() as conn:
        prior = prior_row_for(conn, SYMBOL, SAT)
        payload = build_for_5b(conn, SYMBOL, trigger_type="breakout_from_watch",
                               as_of=AS_OF, prior_row=prior)
        llm_io: dict = {}
        result = call_claude(prompt_file="evaluate_pivot_trigger_v1.md",
                             attachments=[], payload_inline=payload,
                             meta_out=llm_io)
    out = {
        "symbol": SYMBOL, "sat": str(SAT), "as_of": str(AS_OF),
        "trigger": "breakout_from_watch",
        "computed_gates": payload.get("computed_gates"),
        "decision": result.get("decision"),
        "abort_reason": result.get("abort_reason"),
        "confidence": result.get("confidence"),
        "reasoning": result.get("reasoning"),
        "llm_model": llm_io.get("model"),
        "positive_path_confirmed": result.get("decision") == "go_now",
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
