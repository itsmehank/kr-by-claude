"""#21 parity 검증 — 구 프롬프트(LLM) vs 결정론 함수, 필드별 대조 (D4a).

실DB trigger_evaluation_log 행으로 build_for_6 payload 를 구성해 양쪽을 실행.
LLM 출력은 전체 저장(재실행 비교 금지 규율 — 생성 시점 보존). 불일치는 자동
불합격이 아니라 건별 §11 충실성 판정 대상(01편)으로 리포트에만 기록한다.
"""
import argparse, json, os, sys
from datetime import datetime, timezone

import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kr_pipeline.llm_runner.compute.payload_lite import build_for_6
from kr_pipeline.llm_runner.compute.entry_params_calc import (
    CALC_VERSION, EntryParamsRejected, calculate_entry_params)
from kr_pipeline.llm_runner.llm.claude_cli import call_claude

FIELDS = ["entry_mode","pivot_price","trigger_price","current_price","stop_loss_price",
          "stop_loss_pct_from_pivot","stop_loss_pct_from_current_price","suggested_weight_pct",
          "expected_target_price","expected_target_pct","pattern_basis","entry_window_days",
          "max_chase_pct_from_pivot","breakout_volume_requirement","observed_breakout_volume_ratio"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    url = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")
    cases = []
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, evaluated_at
                             FROM trigger_evaluation_log ORDER BY symbol, evaluated_at DESC""")
            pool = cur.fetchall()[: a.limit]
        for sym, ev in pool:
            rec = {"symbol": sym, "evaluated_at": ev.isoformat()}
            try:
                payload = build_for_6(conn, sym, evaluation_at=ev)
            except Exception as e:
                rec["error"] = f"payload: {e}"; cases.append(rec); continue
            try:
                rec["calc"] = calculate_entry_params(payload)
            except EntryParamsRejected as e:
                rec["calc_rejected"] = str(e)
            try:
                rec["llm"] = call_claude(prompt_file="calculate_entry_params_v2_0.md",
                                         attachments=[], payload_inline=payload)
            except Exception as e:
                rec["llm_error"] = str(e)[:300]
            if "calc" in rec and "llm" in rec:
                rec["diffs"] = {f: {"llm": rec["llm"].get(f), "calc": rec["calc"].get(f)}
                                for f in FIELDS if rec["llm"].get(f) != rec["calc"].get(f)}
            cases.append(rec)
            print(f"[{len(cases)}/{len(pool)}] {sym}: "
                  f"{'REJECTED' if 'calc_rejected' in rec else ('diffs=' + str(len(rec.get('diffs', {}))) if 'llm' in rec else 'LLM_ERR')}",
                  flush=True)
    out = a.out or f"data/verification/entry_params_parity_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
    json.dump({"calc_version": CALC_VERSION, "n": len(cases), "cases": cases},
              open(out, "w"), ensure_ascii=False, indent=1, default=str)
    print("saved:", out)


if __name__ == "__main__":
    main()
