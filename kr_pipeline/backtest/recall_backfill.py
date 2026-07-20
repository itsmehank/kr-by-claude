"""Phase 1 — recall 감사 표적 백필: 표본 120 에피소드의 백필 셀을 LLM 분류해
recall_audit_classification 에 멱등 적재.

spec: 2026-07-02-missed-winners-recall-audit-design.md §4.
- 셀 = (ticker, anchor) : 표본 에피소드의 [first_tt, peak_anchor] 구간 게이트 통과
  anchor, 에피소드당 상한 12 (1차 잠금) — recall_phase0 §3.3 과 동일 재계산(결정론).
- as_of = anchor(주 마지막 거래일). 페이로드는 build_analysis_inline(on_date=as_of).
- 멱등: (symbol, analyzed_for_date) 기존 행 skip → 사용량 한도 후 같은 명령 resume.
- production 테이블 쓰기 0건. 1회 실행 → 저장 → 저장본 판정(재실행 비교 금지).

실행:
  uv run python -m kr_pipeline.backtest.recall_backfill --verify-payload  # 선검증 1건
  uv run python -m kr_pipeline.backtest.recall_backfill --dry-run         # 플러밍 스모크
  uv run python -m kr_pipeline.backtest.recall_backfill                   # 본 실행
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import shutil
import sys
import threading
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import Connection

from api.services.inline_builder import build_analysis_inline
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError
from kr_pipeline.llm_runner.parallel import run_parallel_batch
from kr_pipeline.llm_runner.store import insert_backfill_classification

log = logging.getLogger(__name__)

TABLE = "recall_audit_classification"
SOURCE = "recall_audit"
CONCURRENCY = 4  # 실측(backfill.py 주석): c2=100% 안전 / c4=9.6% rc=1 실패(멱등 resume 로 회수).
BACKFILL_CAP = 12  # 1차 잠금 §3.3

CIRCUIT_BREAKER_GROUPS = 2
CIRCUIT_BREAKER_FAIL_RATE = 0.5
CIRCUIT_BREAKER_MIN_SAMPLE = 3

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "backtest"
SAMPLE_CSV = DATA_DIR / "recall_phase1_sample_20260703.csv"

LOOKBACK_START = date(2024, 1, 1)
WINDOW_END = date(2026, 6, 30)


def _connect() -> psycopg.Connection:
    load_dotenv()
    return psycopg.connect(os.environ["DATABASE_URL"])


def load_cells(conn: Connection) -> list[dict]:
    """표본 에피소드 → 백필 셀 (ticker, anchor, market) 재계산 (recall_phase0 §3.3 동일).

    셀 수는 표본 CSV 의 n_backfill_weeks 합(=1,032)과 일치해야 한다(불일치 시 abort).
    """
    with open(SAMPLE_CSV) as f:
        eps = list(csv.DictReader(f))

    with conn.cursor() as cur:
        cur.execute(
            "SELECT date FROM index_daily WHERE index_code='1001'"
            " AND date BETWEEN %s AND %s ORDER BY date",
            (LOOKBACK_START, WINDOW_END),
        )
        days = [r[0] for r in cur.fetchall()]
    by_week: dict[tuple, date] = {}
    for d in days:
        iso = d.isocalendar()
        by_week[(iso[0], iso[1])] = max(d, by_week.get((iso[0], iso[1]), d))
    anchors = sorted(by_week.values())

    tickers = sorted({e["ticker"] for e in eps})
    gate: dict[str, set[date]] = defaultdict(set)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.ticker, i.date
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.ticker = ANY(%s) AND i.date = ANY(%s)
               AND i.minervini_pass = TRUE
               AND i.rs_line_not_declining_7m = TRUE
               AND s.delisted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM daily_prices p
                    WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL)
            """,
            (tickers, anchors),
        )
        for t, d in cur.fetchall():
            gate[t].add(d)

    cells, expected = [], 0
    for e in eps:
        first_tt = date.fromisoformat(e["first_tt"])
        peak = date.fromisoformat(e["peak_date"])
        peak_anchor = next((a for a in reversed(anchors) if a <= peak), None)
        bf = [a for a in anchors if first_tt <= a <= peak_anchor and a in gate[e["ticker"]]]
        bf = bf[:BACKFILL_CAP]
        expected += int(e["n_backfill_weeks"])
        for a in bf:
            cells.append({"symbol": e["ticker"], "market": e["market"], "as_of": a})
    if len(cells) != expected:
        raise SystemExit(
            f"셀 재계산 불일치: {len(cells)} != 표본 CSV 합 {expected} — abort")
    return cells


def verify_payload(conn: Connection, cell: dict) -> None:
    """선검증: 페이로드 텍스트의 날짜 토큰 max ≤ as_of (look-ahead 차단 확인). 실행 전 로그."""
    inline_text, png_paths, _, _gates = build_analysis_inline(
        conn, cell["symbol"], on_date=cell["as_of"])
    shutil.rmtree(str(Path(png_paths[0]).parent), ignore_errors=True)
    tokens = sorted(set(re.findall(r"\d{4}-\d{2}-\d{2}", inline_text)))
    max_tok = max(tokens)
    ok = max_tok <= cell["as_of"].isoformat()
    print(f"[verify-payload] cell={cell['symbol']}@{cell['as_of']} "
          f"date-token max={max_tok} ≤ as_of={cell['as_of']} → {'PASS' if ok else 'FAIL'} "
          f"(고유 날짜 토큰 {len(tokens)}개, min={tokens[0]})")
    if not ok:
        over = [t for t in tokens if t > cell["as_of"].isoformat()]
        raise SystemExit(f"look-ahead 검출: as_of 초과 토큰 {over[:5]} — abort")


def _process_one(conn: Connection, symbol: str, market: str, *, dry_run: bool, as_of: date) -> None:
    started = datetime.now(timezone.utc)
    inline_text, png_paths, _, climax_topping_gates = build_analysis_inline(
        conn, symbol, on_date=as_of
    )
    png_dir = str(Path(png_paths[0]).parent)
    llm_io: dict = {}
    try:
        result = call_claude(
            prompt_file="analyze_chart_v3.md",
            attachments=png_paths, payload_inline=inline_text, dry_run=dry_run,
            meta_out=llm_io,
        )
    finally:
        shutil.rmtree(png_dir, ignore_errors=True)
    # (#44 Task 7) 결정론 echo 주입 — LLM 경유 없음. gates.py §6.2 shadow backstop 소비.
    result["climax_topping_gates_echo"] = climax_topping_gates
    finished = datetime.now(timezone.utc)
    if dry_run:
        log.info("dry-run: skip insert %s@%s (%s)", symbol, as_of, result.get("classification"))
        return
    insert_backfill_classification(
        conn, symbol=symbol, classified_at=finished, market=market, result=result,
        source=SOURCE,
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": llm_io.get("input_tokens"),
                  "output_tokens": llm_io.get("output_tokens"),
                  "model": llm_io.get("model")},
        analyzed_for_date=as_of, table=TABLE,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-payload", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit-cells", type=int, default=0, help="스모크용 셀 수 제한")
    args = ap.parse_args()

    conn = _connect()
    cells = load_cells(conn)
    print(f"[phase1] 백필 셀 {len(cells)} (표본 CSV 합과 일치 검증됨)")

    if args.verify_payload:
        verify_payload(conn, cells[0])
        return

    # alias 해석 1회 로그 (spec §4): 첫 셀 처리 후 resolved llm_model 확인용 —
    # 본 실행에서는 DB 행으로 남는다. dry-run 은 mock 이라 해석 없음.
    by_date: dict[date, list[dict]] = defaultdict(list)
    for c in cells:
        by_date[c["as_of"]].append(c)

    dsn = conn.info.dsn
    abort = threading.Event()
    agg = {"groups": 0, "processed": 0, "skipped_existing": 0, "failures": 0, "failed": []}
    consec_bad = 0
    done_total = 0

    for as_of in sorted(by_date):
        if abort.is_set():
            break
        group = by_date[as_of]
        with conn.cursor() as cur:
            cur.execute(f"SELECT symbol FROM {TABLE} WHERE analyzed_for_date = %s", (as_of,))
            done = {r[0] for r in cur.fetchall()}
        todo = [c for c in group if c["symbol"] not in done]
        agg["skipped_existing"] += len(group) - len(todo)
        if args.limit_cells and done_total >= args.limit_cells:
            break
        if args.limit_cells:
            todo = todo[: max(0, args.limit_cells - done_total)]
        if not todo:
            continue
        candidates = [{"symbol": c["symbol"], "market": c["market"]} for c in todo]
        log.info("recall-backfill %s: %d cell(s) (skip %d)", as_of, len(todo), len(group) - len(todo))
        r = run_parallel_batch(
            dsn=dsn, candidates=candidates, process_fn=_process_one,
            concurrency=CONCURRENCY, dry_run=args.dry_run, as_of=as_of,
            run_id=None, abort=abort,
        )
        done_total += r["processed"]
        agg["processed"] += r["processed"]
        agg["failures"] += len(r["failed_tickers"])
        for ft in r["failed_tickers"]:
            agg["failed"].append([ft["symbol"], str(as_of), ft.get("error", "")[:200]])
        agg["groups"] += 1
        conn.commit()
        if r["usage_limited"]:
            log.warning("usage limit at %s (누적 %d) — 같은 명령 resume", as_of, agg["processed"])
            print(f"AGG {agg}")
            raise UsageLimitError(str(r["usage_error"]))
        total = r["processed"] + len(r["failed_tickers"])
        if total >= CIRCUIT_BREAKER_MIN_SAMPLE:
            if len(r["failed_tickers"]) / total >= CIRCUIT_BREAKER_FAIL_RATE:
                consec_bad += 1
                if consec_bad >= CIRCUIT_BREAKER_GROUPS:
                    log.warning("circuit breaker — systemic 실패, 적재분 보존, resume 가능")
                    break
            else:
                consec_bad = 0

    print(f"AGG {agg}")


if __name__ == "__main__":
    main()
