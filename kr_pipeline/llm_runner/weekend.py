"""주말 (5) analyze_chart_v3 batch.

결정론 필터 (minervini_pass) 통과 종목 전체를 LLM 분석.
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
    integrity_skipped: list[dict] = []

    from api.services.integrity_guard import DataIntegrityError

    for c in candidates:
        symbol = c["symbol"]
        market = c["market"]
        try:
            _process_one(conn, symbol, market, dry_run=dry_run, as_of=as_of)
            processed += 1
            conn.commit()
        except DataIntegrityError as e:
            log.warning("[INTEGRITY GUARD] %s skipped: %s", symbol, e)
            integrity_skipped.append({
                "symbol": symbol,
                "date": e.on_date.isoformat(),
                "column": e.column,
                "p_value": e.p_value,
                "i_value": e.i_value,
                "ratio": e.ratio,
            })
            conn.rollback()
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
            _process_one(conn, symbol, market, dry_run=dry_run, as_of=as_of)
            processed += 1
            conn.commit()
        except DataIntegrityError as e:
            log.warning("[INTEGRITY GUARD] retry: %s skipped: %s", symbol, e)
            integrity_skipped.append({
                "symbol": symbol,
                "date": e.on_date.isoformat(),
                "column": e.column,
                "p_value": e.p_value,
                "i_value": e.i_value,
                "ratio": e.ratio,
            })
            conn.rollback()
        except Exception as e:
            retry_failures.append((symbol, str(e)))
            conn.rollback()

    if integrity_skipped:
        log.warning("[INTEGRITY GUARD] %d tickers skipped due to data integrity issues",
                    len(integrity_skipped))

    log.info("weekend batch done: processed=%d retry_failures=%d integrity_skipped=%d",
             processed, len(retry_failures), len(integrity_skipped))

    return {
        "processed": processed,
        "candidates": len(candidates),
        "failures": len(retry_failures),
        "failed_tickers": [t for t, _ in retry_failures],
        "integrity_skipped": integrity_skipped,
    }


def _process_one(
    conn: Connection,
    symbol: str,
    market: str,
    *,
    dry_run: bool,
    as_of: date,
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

    if dry_run:
        log.info("dry-run: skipping DB insert for %s (mock result %s)",
                 symbol, result.get("classification"))
        return

    insert_classification(
        conn,
        symbol=symbol,
        classified_at=finished,
        market=market,
        result=result,
        source="weekend",
        llm_meta={
            "duration_s": duration_s,
            "input_tokens": None,
            "output_tokens": None,
        },
        analyzed_for_date=as_of,
    )
