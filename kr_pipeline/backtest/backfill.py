"""수익성·강건성 백테스트 백필 — 전용 테이블 backtest_classification 에 멱등 적재.

production backfill(kr_pipeline/llm_runner/backfill.py)과 격리된 드라이버.
공유 building block(토요일 열거·qualifying 조회·병렬·인라인 빌드·call_claude·insert)을
재사용하되, 적재·resume 는 backtest_classification 만 본다(spec §5). 읽기전용 분석.
"""
from __future__ import annotations

import logging
import shutil
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.inline_builder import build_analysis_inline
from kr_pipeline.llm_runner.backfill import _enumerate_saturdays
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError
from kr_pipeline.llm_runner.load import get_qualifying_tickers
from kr_pipeline.llm_runner.parallel import run_parallel_batch
from kr_pipeline.llm_runner.store import insert_backfill_classification

log = logging.getLogger(__name__)

BT_TABLE = "backtest_classification"
BT_SOURCE = "backtest"
BT_CONCURRENCY = 2   # 실측 안전 동시성 상한 (c1·c2=100%, c4=9.6% rc=1 실패). 한 건 ≈103s.

CIRCUIT_BREAKER_WEEKS = 2        # 나쁜 주 K연속 시 클린 중단
CIRCUIT_BREAKER_FAIL_RATE = 0.5  # 한 주 실패율 >= 50% 면 '나쁜 주'
CIRCUIT_BREAKER_MIN_SAMPLE = 3   # 시도수 < 3 인 주는 판정 보류(노이즈 회피)


def already_done(conn: Connection, as_of: date) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT symbol FROM {BT_TABLE} WHERE analyzed_for_date = %s", (as_of,)
        )
        return {r[0] for r in cur.fetchall()}


def _process_one(conn: Connection, symbol: str, market: str, *, dry_run: bool, as_of: date) -> None:
    started = datetime.now(timezone.utc)
    inline_text, png_paths, _ = build_analysis_inline(conn, symbol, on_date=as_of)
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
    finished = datetime.now(timezone.utc)
    if dry_run:
        log.info("dry-run: skip insert %s (%s)", symbol, result.get("classification"))
        return
    insert_backfill_classification(
        conn, symbol=symbol, classified_at=finished, market=market, result=result,
        source=BT_SOURCE,
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": llm_io.get("input_tokens"),
                  "output_tokens": llm_io.get("output_tokens"),
                  "model": llm_io.get("model")},
        analyzed_for_date=as_of, table=BT_TABLE,
    )


def run_backtest_backfill(conn: Connection, *, start: date, end: date, tickers: list[str],
                          dry_run: bool = False, concurrency: int | None = None) -> dict:
    """기간 × 매주 토요일, 지정 tickers 중 그 주 qualifying 종목을 분류해 BT_TABLE 에 적재.
    멱등: 이미 적재된 (symbol, 토요일)은 skip. 사용량 한도 시 abort(다음 실행이 이어감)."""
    saturdays = _enumerate_saturdays(start, end)
    concurrency = concurrency or BT_CONCURRENCY
    agg = {"weeks": 0, "processed": 0, "skipped_existing": 0, "failures": 0,
           "failed": [], "integrity_skipped": [], "start": str(start), "end": str(end),
           "circuit_broken": False}
    dsn = conn.info.dsn
    abort = threading.Event()
    consec_bad_weeks = 0

    for as_of in saturdays:
        if abort.is_set():
            break
        candidates = get_qualifying_tickers(conn, as_of=as_of, tickers=tickers)
        done = already_done(conn, as_of)
        skipped = [c for c in candidates if c["symbol"] in done]
        candidates = [c for c in candidates if c["symbol"] not in done]
        log.info("bt-backfill week=%s: %d candidate(s) (done %d)", as_of, len(candidates), len(done))
        r = run_parallel_batch(
            dsn=dsn, candidates=candidates, process_fn=_process_one,
            concurrency=concurrency, dry_run=dry_run, as_of=as_of, run_id=None, abort=abort,
        )
        agg["processed"] += r["processed"]
        for ft in r["failed_tickers"]:
            agg["failed"].append([ft["symbol"], str(as_of), ft.get("error", "")])
        agg["failures"] += len(r["failed_tickers"])
        agg["integrity_skipped"].extend(r["integrity_skipped"])
        agg["skipped_existing"] += len(skipped)
        agg["weeks"] += 1
        conn.commit()
        if r["usage_limited"]:
            log.warning("bt-backfill usage limit at %s (processed=%d)", as_of, agg["processed"])
            raise UsageLimitError(
                f"usage limit — bt-backfill aborted: processed={agg['processed']}, reason={r['usage_error']}"
            )
        # 서킷브레이커: 한 주 실패율이 임계 이상인 '나쁜 주'가 K연속이면 systemic 실패로
        # 클린 중단. processed==0(하드 한도)뿐 아니라 1건만 성공+대량 실패(만성 부분실패=
        # 동시성 저하 등)도 잡는다. 시도수 적은 주는 판정 보류(노이즈 회피).
        # (rc=1 빈출력 형태의 한도/장애가 UsageLimitError 로 안 잡혀도 여기서 멈춤.)
        week_total = r["processed"] + len(r["failed_tickers"])
        if week_total >= CIRCUIT_BREAKER_MIN_SAMPLE:
            fail_rate = len(r["failed_tickers"]) / week_total
            if fail_rate >= CIRCUIT_BREAKER_FAIL_RATE:
                consec_bad_weeks += 1
                if consec_bad_weeks >= CIRCUIT_BREAKER_WEEKS:
                    agg["circuit_broken"] = True
                    agg["stop_reason"] = (
                        f"{consec_bad_weeks} consecutive weeks with fail-rate "
                        f">= {CIRCUIT_BREAKER_FAIL_RATE:.0%} (likely usage limit / "
                        f"concurrency / CLI failure) — 적재분 보존, rerun=resume"
                    )
                    log.warning("bt-backfill circuit breaker: %s", agg["stop_reason"])
                    break
            else:
                consec_bad_weeks = 0
        # week_total < MIN_SAMPLE: 판정 보류(카운터 유지)
    return agg
