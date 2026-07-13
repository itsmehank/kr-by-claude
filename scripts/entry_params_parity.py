"""#21 parity 검증 — 구 프롬프트(LLM) vs 결정론 함수, 필드별 대조 (D4a).

실DB trigger_evaluation_log 행으로 build_for_6 payload 를 구성해 양쪽을 실행.
LLM 출력은 전체 저장(재실행 비교 금지 규율 — 생성 시점 보존). 불일치는 자동
불합격이 아니라 건별 §11 충실성 판정 대상(01편)으로 리포트에만 기록한다.

주의(run1 이후 리뷰 반영):
- 프롬프트에 RETIRED 배너가 추가됨 — 배너가 LLM 입력에 들어가면 정답 유출/거부 유도로
  parity 가 무효가 되므로 아래 가드가 실행을 막는다. run1(entry_params_parity_run1.json)
  은 배너 추가 '이전' 실행이라 유효. 재실행은 pre-banner 사본으로 교체 후에만.
- run1 의 표본 풀은 decision 무필터(wait 등 포함)였다 — 지금은 production C 입력
  분포(go_now + breakout 계열)로 필터한다.
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kr_pipeline.llm_runner.compute.payload_lite import build_for_6
from kr_pipeline.llm_runner.compute.entry_params_calc import (
    CALC_VERSION, EntryParamsRejected, calculate_entry_params)
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.store import _ENTRY_PARAMS_REQUIRED

# 대조 필드 = 저장 계약의 필수 §9 필드(store SSOT) — 하드코딩 사본을 두면 필드
# 추가 시 조용히 비교에서 빠지는 가짜-통과가 생긴다. notes 는 자유텍스트라 제외.
FIELDS = [f for f in _ENTRY_PARAMS_REQUIRED if f != "notes"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    prompt_head = (Path(__file__).resolve().parents[1]
                   / "prompts" / "calculate_entry_params_v2_0.md").read_text(encoding="utf-8")[:400]
    if "RETIRED" in prompt_head:
        sys.exit("중단: 프롬프트에 RETIRED 배너가 있어 LLM 입력이 오염됩니다(정답 유출/거부 유도). "
                 "pre-banner 사본(git show 4a978e6:prompts/calculate_entry_params_v2_0.md)으로 "
                 "임시 교체 후 실행하세요. run1 결과는 배너 이전 실행이라 유효.")
    url = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")
    cases = []
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            # production C 입력 분포와 동일 필터(_fetch_go_now_candidates 의 핵심 WHERE)
            cur.execute("""SELECT DISTINCT ON (symbol) symbol, evaluated_at
                             FROM trigger_evaluation_log
                            WHERE decision = 'go_now'
                              AND trigger_type IN ('breakout', 'breakout_from_watch')
                            ORDER BY symbol, evaluated_at DESC""")
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
