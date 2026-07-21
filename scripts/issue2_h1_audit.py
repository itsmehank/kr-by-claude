"""(#2 1부) H1 이득 측정 — 동결 38셀, as_of=게이트 발화일, 이중 합격선.

준거: docs/superpowers/specs/2026-07-22-issue2-recall-experiment-prereg.md §2.
- 셀 동결: recall_funnel_20260705.csv 의 gate_anyday_fired 비어있지 않은 38건.
- 호출 1회/셀 + 요청 payload 의 computed_gates 영속(§2 확장 요구) — 완화선은
  payload 기록 기반 결정론 추론(재호출 금지).
- 멱등 재개: (ticker, gate_date) done-key, UsageLimitError 즉시 중단 → 재실행 이어가기.

실행:
  uv run python scripts/issue2_h1_audit.py --dry-run   # wiring 검증 (LLM 0회)
  uv run python scripts/issue2_h1_audit.py             # 실호출 (분할 실행 가능)
  uv run python scripts/issue2_h1_audit.py --limit 20  # 배치 상한
출력: data/backtest/issue2_h1_audit.json
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError

log = logging.getLogger("issue2_h1")

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "backtest"
FUNNEL_CSV = DATA_DIR / "recall_funnel_20260705.csv"  # 사전등록 동결 파일
OUT_PATH = DATA_DIR / "issue2_h1_audit.json"
TABLE = "recall_audit_classification"


def relaxed_go_now(decision: str | None, gates: dict | None) -> bool | None:
    """완화선(1.2×) 재판정 — 사전등록 §2 규칙 그대로 (결정론).

    완화선 go_now = 현행 go_now ∪ (LLM wait ∧ volume_band=='wait_band'
    ∧ 나머지 §3.1 go_now 게이트 전부 pass ∧ §3.4 회복 게이트 둘 다 pass).
    게이트 null 은 불충족(go_now 금지 규약과 동일 보수). gates 미기록이면 None.
    """
    if decision == "go_now":
        return True
    if gates is None:
        return None
    if decision != "wait":
        return False
    return bool(
        gates.get("volume_band") == "wait_band"
        and gates.get("price_above_pivot") is True
        and gates.get("close_upper_third") is True
        and gates.get("spread_wide_loose") is False
        and gates.get("no_dist_3d") is True
        and gates.get("market_recovery_ok") is True
        and gates.get("tt_recovery_ok") is True
    )


def load_cells() -> list[dict]:
    with open(FUNNEL_CSV) as f:
        rows = list(csv.DictReader(f))
    cells = [
        {"ticker": r["ticker"], "gate_date": r["gate_anyday_fired"],
         "anchor": r["audited_anchor"]}
        for r in rows if r["gate_anyday_fired"]
    ]
    assert len(cells) == 38, f"동결 38셀 불일치: {len(cells)} — 사전등록 위반"
    return cells


def load_prior(conn, ticker: str, anchor: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT classification, pattern, pivot_price, pivot_basis, base_high,
                       base_low, base_depth_pct, risk_flags, reasoning, watch_reason
                  FROM {TABLE} WHERE symbol = %s AND analyzed_for_date = %s""",
            (ticker, anchor),
        )
        r = cur.fetchone()
    if r is None:
        raise ValueError(f"prior row 없음: {ticker} @ {anchor}")
    f = lambda v: float(v) if v is not None else None  # noqa: E731
    return {
        "classified_at": datetime.combine(date.fromisoformat(anchor), dt_time.min),
        "classification": r[0], "pattern": r[1], "pivot_price": f(r[2]),
        "pivot_basis": r[3], "base_high": f(r[4]), "base_low": f(r[5]),
        "base_depth_pct": f(r[6]), "risk_flags": r[7], "reasoning": r[8],
        "watch_reason": r[9],
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    dry_run = "--dry-run" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    load_dotenv()
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    cells = load_cells()

    doc = (json.loads(OUT_PATH.read_text()) if OUT_PATH.exists()
           else {"prereg": "2026-07-22-issue2-recall-experiment-prereg.md §2",
                 "results": []})
    done = {(r["ticker"], r["gate_date"]) for r in doc["results"]}
    log.info("[h1] cells=38 done=%d dry_run=%s", len(done), dry_run)

    called = 0
    for c in cells:
        if (c["ticker"], c["gate_date"]) in done:
            continue
        if limit is not None and called >= limit:
            log.info("[h1] batch limit %d — 재실행이 이어감", limit)
            break
        prior = load_prior(conn, c["ticker"], c["anchor"])
        payload = build_for_5b(
            conn, c["ticker"], trigger_type="breakout_from_watch",
            as_of=date.fromisoformat(c["gate_date"]), prior_row=prior,
        )
        gates = payload.get("computed_gates")
        llm_io: dict = {}
        try:
            result = call_claude(
                prompt_file="evaluate_pivot_trigger_v1.md", attachments=[],
                payload_inline=payload, dry_run=dry_run, meta_out=llm_io,
            )
        except UsageLimitError:
            log.warning("[h1] usage limit — clean abort(%d done), 재실행 resume", len(done))
            break
        called += 1
        if dry_run:
            log.info("[h1-dry] %s %s gates_ok=%s vb=%s", c["ticker"], c["gate_date"],
                     gates is not None, (gates or {}).get("volume_band"))
            continue
        rec = {
            "ticker": c["ticker"], "gate_date": c["gate_date"], "anchor": c["anchor"],
            "decision": result.get("decision"), "confidence": result.get("confidence"),
            "abort_reason": result.get("abort_reason"),
            "reasoning": result.get("reasoning"),
            "computed_gates": gates,
            "relaxed_go_now": relaxed_go_now(result.get("decision"), gates),
            "llm_model": llm_io.get("model"),
            "input_tokens": llm_io.get("input_tokens"),
            "output_tokens": llm_io.get("output_tokens"),
        }
        doc["results"].append(rec)
        done.add((c["ticker"], c["gate_date"]))
        OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        log.info("[h1] %s %s → %s (완화선 go_now=%s) [%d/38]",
                 c["ticker"], c["gate_date"], rec["decision"],
                 rec["relaxed_go_now"], len(done))

    if not dry_run and doc["results"]:
        strict = sum(1 for r in doc["results"] if r["decision"] == "go_now")
        relaxed = sum(1 for r in doc["results"] if r.get("relaxed_go_now"))
        log.info("[h1] 진행 %d/38 — 현행 go_now=%d / 완화선 go_now=%d",
                 len(doc["results"]), strict, relaxed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
