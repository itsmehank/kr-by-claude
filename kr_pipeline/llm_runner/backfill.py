"""과거 백필/백테스트 — 단일 as_of 시점의 minervini 통과 종목 분류 → classification_backfill.

라이브와 같은 프롬프트(analyze_chart_v3.md), ②의 on_date 로 과거 차트 사용.
멱등: 이미 그 as_of 로 백필된 종목은 후보에서 제외. freeze 저장 없음.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from psycopg import Connection

from api.services.zip_builder import build_analysis_zip
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.load import get_qualifying_tickers
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
        dry_run: bool = False, limit: int | None = None) -> dict:
    """기간 × 매주 토요일 백필. 토요일마다 그 주 minervini 통과 종목(또는 지정 종목)을 분류."""
    saturdays = _enumerate_saturdays(start, end)
    agg = {
        "weeks": 0,
        "processed": 0,
        "skipped_existing": 0,
        "failures": 0,
        "failed": [],
        "start": str(start),
        "end": str(end),
    }

    for as_of in saturdays:
        candidates = get_qualifying_tickers(conn, as_of=as_of, tickers=tickers)
        done = _already_backfilled(conn, as_of)
        skipped = [c for c in candidates if c["symbol"] in done]
        candidates = [c for c in candidates if c["symbol"] not in done]
        if limit:
            candidates = candidates[:limit]

        log.info("backfill week=%s: %d candidate(s) (done %d)", as_of, len(candidates), len(done))

        for c in candidates:
            symbol = c["symbol"]
            market = c["market"]
            try:
                _process_one(conn, symbol, market, dry_run=dry_run, as_of=as_of)
                agg["processed"] += 1
                conn.commit()
            except Exception as e:  # noqa: BLE001
                log.warning("backfill %s @ %s failed: %s", symbol, as_of, e)
                agg["failed"].append([symbol, str(as_of), str(e)])
                agg["failures"] += 1
                conn.rollback()

        agg["skipped_existing"] += len(skipped)
        agg["weeks"] += 1

    return agg


def _process_one(conn: Connection, symbol: str, market: str, *, dry_run: bool, as_of: date) -> None:
    started = datetime.now(timezone.utc)
    zip_bytes = build_analysis_zip(conn, symbol, on_date=as_of, include_prior_analysis=False)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(zip_bytes)
        zip_path = f.name
    try:
        result = call_claude(
            prompt_file="analyze_chart_v3.md",
            attachments=[zip_path],
            dry_run=dry_run,
        )
    finally:
        Path(zip_path).unlink(missing_ok=True)

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
                  "input_tokens": None, "output_tokens": None},
        analyzed_for_date=as_of,
    )
