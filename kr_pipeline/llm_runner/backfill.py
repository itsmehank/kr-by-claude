"""과거 백필/백테스트 — 단일 as_of 시점의 minervini 통과 종목 분류 → classification_backfill.

라이브와 같은 프롬프트(analyze_chart_v3.md), ②의 on_date 로 과거 차트 사용.
멱등: 이미 그 as_of 로 백필된 종목은 후보에서 제외. freeze 저장 없음.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from psycopg import Connection

from api.services.inline_builder import build_analysis_inline
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError
from kr_pipeline.llm_runner.load import get_qualifying_tickers
from kr_pipeline.llm_runner.parallel import run_parallel_batch
from kr_pipeline.llm_runner.store import insert_backfill_classification

log = logging.getLogger("kr_pipeline.llm_runner.backfill")


def _enumerate_saturdays(start: date, end: date) -> list[date]:
    """start~end(양끝 포함) 범위의 모든 토요일을 오름차순으로 반환.

    토요일은 weekday()==5. start>end 면 빈 리스트.
    """
    if start > end:
        return []
    # start 이상인 첫 토요일로 전진
    d = start + timedelta(days=(5 - start.weekday()) % 7)
    out: list[date] = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def _already_backfilled(conn: Connection, as_of: date) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM classification_backfill WHERE analyzed_for_date = %s",
            (as_of,),
        )
        return {r[0] for r in cur.fetchall()}


def run(conn: Connection, *, start: date, end: date, tickers: list[str] | None = None,
        dry_run: bool = False, limit: int | None = None, concurrency: int | None = None) -> dict:
    """기간 × 매주 토요일 백필(병렬). 토요일마다 그 주 minervini 통과 종목(또는 지정 종목)을 분류."""
    saturdays = _enumerate_saturdays(start, end)
    concurrency = concurrency or int(os.environ.get("BACKFILL_CONCURRENCY", "4"))
    agg = {
        "weeks": 0,
        "processed": 0,
        "skipped_existing": 0,
        "failures": 0,
        "failed": [],
        "integrity_skipped": [],
        "start": str(start),
        "end": str(end),
    }
    dsn = conn.info.dsn
    abort = threading.Event()   # 토요일을 가로지르는 단일 abort — 사용량 한도 시 전체 중단

    for as_of in saturdays:
        if abort.is_set():
            break
        candidates = get_qualifying_tickers(conn, as_of=as_of, tickers=tickers)
        done = _already_backfilled(conn, as_of)
        skipped = [c for c in candidates if c["symbol"] in done]
        candidates = [c for c in candidates if c["symbol"] not in done]
        if limit:
            candidates = candidates[:limit]

        log.info("backfill week=%s: %d candidate(s) (done %d)", as_of, len(candidates), len(done))

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
        # 토요일별 main 커넥션 스냅샷 해제(읽기 트랜잭션 정리) — 다음 토요일 _already_backfilled 가
        # 워커 commit 을 최신으로 보게 함(READ COMMITTED 라 정합하나, 긴 트랜잭션 위생).
        conn.commit()

        if r["usage_limited"]:
            log.warning("backfill usage limit at %s — aborting (processed=%d)", as_of, agg["processed"])
            raise UsageLimitError(
                f"usage limit — backfill aborted: processed={agg['processed']}, reason={r['usage_error']}"
            )

    return agg


def _process_one(conn: Connection, symbol: str, market: str, *, dry_run: bool, as_of: date) -> None:
    started = datetime.now(timezone.utc)
    # 인라인 입력 빌드(ZIP→텍스트 인라인 + 차트 PNG). backfill 은 freeze 미저장.
    inline_text, png_paths, _freeze_bytes, climax_topping_gates = build_analysis_inline(
        conn, symbol, on_date=as_of
    )
    png_dir = str(Path(png_paths[0]).parent)
    llm_io: dict = {}
    try:
        result = call_claude(
            prompt_file="analyze_chart_v3.md",
            attachments=png_paths,
            payload_inline=inline_text,
            dry_run=dry_run,
            meta_out=llm_io,
        )
    finally:
        shutil.rmtree(png_dir, ignore_errors=True)

    # (#44 Task 7) 결정론 echo 주입 — LLM 경유 없음. gates.py §6.2 shadow backstop 소비.
    result["climax_topping_gates_echo"] = climax_topping_gates

    finished = datetime.now(timezone.utc)

    if dry_run:
        log.info("dry-run: skipping backfill insert for %s (%s)", symbol, result.get("classification"))
        return

    insert_backfill_classification(
        conn,
        symbol=symbol,
        classified_at=finished,
        market=market,
        result=result,
        source="backfill",
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": llm_io.get("input_tokens"),
                  "output_tokens": llm_io.get("output_tokens"),
                  "model": llm_io.get("model")},
        analyzed_for_date=as_of,
    )
