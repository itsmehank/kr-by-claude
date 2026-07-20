"""평일 daily-delta — 신규 후보 (5) 분석.

신규 = 오늘 결정론 통과 + 최근 7일 분류 없음.
주말 (5) 와 같은 프롬프트, 같은 출력. source='daily_delta' 마킹만 다름.
"""
from __future__ import annotations

import logging
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.freeze_store import save_freeze
from api.services.inline_builder import build_analysis_inline
from kr_pipeline.llm_runner.compute.delta import find_new_tickers
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError
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
    integrity_skipped: list[dict] = []

    from api.services.integrity_guard import DataIntegrityError

    for symbol in new_tickers:
        try:
            _process_one(conn, symbol, dry_run=dry_run, as_of=as_of)
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
        except UsageLimitError:
            # 사용량 제한(5시간) — 남은 종목 순회가 전부 헛호출이므로 즉시 중단.
            # 예외 전파 → run_tracking failed → 재실행이 중복 가드에 안 막힘.
            # 기처리분은 commit 완료 + find_new_tickers 7일 가드가 재실행 시 제외.
            conn.rollback()
            log.warning("daily_delta usage limit at %s — aborting (processed=%d/%d)",
                        symbol, processed, len(new_tickers))
            raise
        except Exception as e:
            log.warning("daily_delta %s failed: %s", symbol, e)
            failed.append(symbol)
            conn.rollback()

    if integrity_skipped:
        log.warning("[INTEGRITY GUARD] %d tickers skipped due to data integrity issues",
                    len(integrity_skipped))

    return {
        "processed": processed,
        "candidates": len(new_tickers),
        "failures": len(failed),
        "failed_tickers": failed,
        "integrity_skipped": integrity_skipped,
    }


def _process_one(conn: Connection, symbol: str, *, dry_run: bool, as_of: date) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT market FROM stocks WHERE ticker = %s", (symbol,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Stock not found: {symbol}")
    market = row[0]

    started = datetime.now(timezone.utc)
    # 인라인 입력 빌드(ZIP→텍스트 인라인 + 차트 PNG). 신규 분석은 직전 분류 미첨부
    # (anchoring 방지 — 트레이드오프·관측 로그: docs/pivot-reanalysis-tradeoff.md, #1).
    # on_date=as_of: --date 과거 재실행 look-ahead 방지.
    # freeze_bytes = 감사·재현용 ZIP(inline_input.md + 차트 2장).
    inline_text, png_paths, freeze_bytes, climax_topping_gates = build_analysis_inline(
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
        log.info("dry-run: skipping DB insert for %s (mock result %s)",
                 symbol, result.get("classification"))
        # dry_run 에서도 freeze 저장 — classification_id=None (분류 row 없음)
        save_freeze(
            conn,
            artifact_bytes=freeze_bytes,
            content_type="application/zip",
            ticker=symbol,
            stage="daily_delta",
            classification_id=None,
        )
        return

    insert_classification(
        conn,
        symbol=symbol,
        classified_at=finished,
        market=market,
        result=result,
        source="daily_delta",
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": llm_io.get("input_tokens"),
                  "output_tokens": llm_io.get("output_tokens"),
                  "model": llm_io.get("model")},
        analyzed_for_date=as_of,
    )

    # 분류 row 저장 후 freeze — fail-soft, 반환값 무시
    save_freeze(
        conn,
        artifact_bytes=freeze_bytes,
        content_type="application/zip",
        ticker=symbol,
        stage="daily_delta",
        classification_id=None,
    )
