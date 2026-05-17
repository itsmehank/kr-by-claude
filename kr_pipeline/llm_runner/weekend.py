"""주말 (5) analyze_chart_v3 batch.

결정론 필터 (minervini_pass + drawdown_filter_pass) 통과 종목 전체를 LLM 분석.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.zip_builder import build_analysis_zip
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, ClaudeCLIError
from kr_pipeline.llm_runner.load import get_qualifying_tickers
from kr_pipeline.llm_runner.store import insert_classification


log = logging.getLogger("kr_pipeline.llm_runner.weekend")


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
    ticker: str | None = None,
) -> dict:
    """주말 (5) batch 실행.

    Returns: {"processed": N, "failures": N, "tickers": [...]}
    """
    if as_of is None:
        as_of = date.today()

    if ticker:
        candidates = [{"symbol": ticker, "market": "KOSPI"}]
    else:
        candidates = get_qualifying_tickers(conn, as_of=as_of)

    if limit:
        candidates = candidates[:limit]

    log.info("weekend batch: %d candidates as_of=%s dry_run=%s",
             len(candidates), as_of, dry_run)

    processed = 0
    failures: list[tuple[str, str]] = []
    failed_tickers = []

    for c in candidates:
        symbol = c["symbol"]
        market = c["market"]
        try:
            _process_one(conn, symbol, market, dry_run=dry_run)
            processed += 1
            conn.commit()
        except Exception as e:
            log.warning("ticker %s failed: %s", symbol, e)
            failures.append((symbol, str(e)))
            failed_tickers.append(symbol)
            conn.rollback()

    # End-of-run retry 1회
    retry_failures = []
    for symbol in failed_tickers:
        try:
            market = next(c["market"] for c in candidates if c["symbol"] == symbol)
            _process_one(conn, symbol, market, dry_run=dry_run)
            processed += 1
            conn.commit()
        except Exception as e:
            retry_failures.append((symbol, str(e)))
            conn.rollback()

    log.info("weekend batch done: processed=%d retry_failures=%d",
             processed, len(retry_failures))

    return {
        "processed": processed,
        "failures": len(retry_failures),
        "failed_tickers": [t for t, _ in retry_failures],
    }


def _process_one(
    conn: Connection,
    symbol: str,
    market: str,
    *,
    dry_run: bool,
) -> None:
    """단일 종목 (5) 호출 + INSERT."""
    started = datetime.now(timezone.utc)

    # ZIP 빌드 (dry-run 도 가짜 bytes 받음)
    zip_bytes = build_analysis_zip(conn, symbol)

    # ZIP 을 임시 파일로 저장 (Claude CLI attach 용)
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
    duration_s = (finished - started).total_seconds()

    insert_classification(
        conn,
        symbol=symbol,
        classified_at=finished,
        market=market,
        result=result,
        source="weekend",
        llm_meta={
            "duration_s": duration_s,
            "input_tokens": None,  # CLI 출력에서 추출 어려움
            "output_tokens": None,
        },
    )
