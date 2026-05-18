"""평일 daily-delta — 신규 후보 (5) 분석.

신규 = 오늘 결정론 통과 + 최근 7일 분류 없음.
주말 (5) 와 같은 프롬프트, 같은 출력. source='daily_delta' 마킹만 다름.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.zip_builder import build_analysis_zip
from kr_pipeline.llm_runner.compute.delta import find_new_tickers
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.store import insert_classification


log = logging.getLogger("kr_pipeline.llm_runner.daily_delta")


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
) -> dict:
    if as_of is None:
        as_of = date.today()

    new_tickers = find_new_tickers(conn, as_of=as_of)
    if limit:
        new_tickers = new_tickers[:limit]

    log.info("daily_delta: %d new tickers as_of=%s", len(new_tickers), as_of)

    processed = 0
    failed = []

    for symbol in new_tickers:
        try:
            _process_one(conn, symbol, dry_run=dry_run)
            processed += 1
            conn.commit()
        except Exception as e:
            log.warning("daily_delta %s failed: %s", symbol, e)
            failed.append(symbol)
            conn.rollback()

    return {
        "processed": processed,
        "candidates": len(new_tickers),
        "failures": len(failed),
        "failed_tickers": failed,
    }


def _process_one(conn: Connection, symbol: str, *, dry_run: bool) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT market FROM stocks WHERE ticker = %s", (symbol,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Stock not found: {symbol}")
    market = row[0]

    started = datetime.now(timezone.utc)
    zip_bytes = build_analysis_zip(conn, symbol)
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
    insert_classification(
        conn,
        symbol=symbol,
        classified_at=finished,
        market=market,
        result=result,
        source="daily_delta",
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": None, "output_tokens": None},
    )
