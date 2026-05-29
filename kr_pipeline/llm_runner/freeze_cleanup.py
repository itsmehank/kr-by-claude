"""Freeze retention cron — 90일 + 활성 보호 + stage 별 최근 1건 보존.

분리 cron — lazy cleanup 금지 (분석 경로 결합 → cleanup 실패가 분석 실패 유발).

삭제 기준 (AND):
  1. frozen_at < NOW() - retention_days days
  2. 활성 분류 보호:
     - classification_id IS NULL → 자동 통과 (분류와 연결 없음)
     - classification_id IS NOT NULL → 미구현 (weekly_classification 에 BIGINT id 없어
       현재 항상 NULL, 후속 사이클에서 id 컬럼 추가 시 구현)
  3. (ticker, stage) 그룹의 MAX(frozen_at) 행은 항상 보존 — classification_id
     NULL/NOT NULL 무관.

CLI: uv run python -m kr_pipeline.llm_runner.freeze_cleanup [--apply] [--days N]
     기본 dry-run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from psycopg import Connection

log = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    candidates: int
    deleted: int
    bytes_freed: int


def cleanup(
    conn: Connection,
    *,
    dry_run: bool = True,
    retention_days: int = 90,
) -> CleanupResult:
    """삭제 기준 3-AND 적용. dry_run=True 이면 후보 계산만.

    Note: classification_id 가 현재 항상 NULL 이므로 활성 보호 sub-rule 은
    자동 통과. 후속 사이클에서 weekly_classification 에 BIGINT id 추가 시
    JOIN 조건을 확장.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest AS (
                SELECT DISTINCT ON (ticker, stage) id
                  FROM classification_freezes
                 ORDER BY ticker, stage, frozen_at DESC
            )
            SELECT f.id, f.artifact_uri, f.artifact_size_bytes
              FROM classification_freezes f
             WHERE f.frozen_at < NOW() - INTERVAL '1 day' * %s
               AND f.classification_id IS NULL   -- 활성 보호 자동 통과 (NULL 케이스)
               AND f.id NOT IN (SELECT id FROM latest)
            """,
            (retention_days,),
        )
        rows = cur.fetchall()

    candidates = len(rows)
    deleted = 0
    bytes_freed = 0

    if dry_run:
        log.info("[FREEZE_CLEANUP] dry_run candidates=%d", candidates)
        return CleanupResult(candidates=candidates, deleted=0, bytes_freed=0)

    for row_id, uri, size in rows:
        try:
            parsed = urlparse(uri)
            if parsed.scheme == "file":
                p = Path(parsed.path)
                if p.exists():
                    p.unlink()
                # 월별 디렉토리 비면 정리 (cron prune 효과)
                try:
                    p.parent.rmdir()
                except OSError:
                    pass
            else:
                log.warning(
                    "[FREEZE_CLEANUP] unsupported scheme %s id=%d — skip",
                    parsed.scheme, row_id,
                )
                continue

            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM classification_freezes WHERE id = %s",
                    (row_id,),
                )
            conn.commit()
            deleted += 1
            bytes_freed += size or 0
        except Exception as exc:
            log.warning(
                "[FREEZE_CLEANUP] delete failed id=%d uri=%s reason=%s",
                row_id, uri, exc,
            )
            try:
                conn.rollback()
            except Exception:
                pass

    log.info(
        "[FREEZE_CLEANUP] candidates=%d deleted=%d bytes_freed=%d",
        candidates, deleted, bytes_freed,
    )
    return CleanupResult(candidates=candidates, deleted=deleted, bytes_freed=bytes_freed)


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv

    load_dotenv()

    from kr_pipeline.db.connection import connect

    ap = argparse.ArgumentParser(description="Freeze retention cleanup")
    ap.add_argument("--apply", action="store_true", help="실제 삭제 (기본 dry-run)")
    ap.add_argument("--days", type=int, default=90, help="보존 기간 (일)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO)
    with connect() as conn:
        result = cleanup(conn, dry_run=not args.apply, retention_days=args.days)
    print(f"candidates={result.candidates} deleted={result.deleted} bytes_freed={result.bytes_freed}")
