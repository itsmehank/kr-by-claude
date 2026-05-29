"""Classification freeze store — ZIP 등 artifact 보존/조회.

Phase 0 Step 4:
- artifact_* 일반화 + content_type.
- save_freeze 는 *fail-soft* — 실패 시 None 반환 + log.warning.
  분석 경로가 freeze 실패로 중단되면 안 됨.
- read_artifact_from_uri 는 file:// 만 구현, s3:// 등은 NotImplementedError.

GUARD (Step 3) 와 반대 정책:
  GUARD = fail-fast (오염 차단) / FREEZE = fail-soft (분류 결과 보존).
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from psycopg import Connection

log = logging.getLogger(__name__)

FREEZE_ROOT = Path(os.environ.get("FREEZE_ROOT", "data/freezes")).resolve()


@dataclass(frozen=True)
class ClassificationFreeze:
    id: int
    classification_id: Optional[int]
    ticker: str
    stage: str
    frozen_at: datetime
    artifact_uri: str
    artifact_sha256: str
    artifact_size_bytes: int
    content_type: str


def _path_for(root: Path, ticker: str, stage: str, frozen_at: datetime) -> Path:
    ym = frozen_at.strftime("%Y-%m")
    ts = frozen_at.strftime("%Y%m%d_%H%M%S")
    return root / stage / ym / f"{ticker}_{ts}.zip"


def save_freeze(
    conn: Connection,
    *,
    artifact_bytes: bytes,
    content_type: str,
    ticker: str,
    stage: str,
    classification_id: Optional[int],
) -> Optional[ClassificationFreeze]:
    """Freeze artifact. *Fail-soft* — 실패 시 None 반환 + log.warning.

    분석 경로 (LLM runner) 에서 freeze 실패가 분류 자체를 실패시키면 안 됨.
    GUARD = 오염 차단 위해 fail-fast / FREEZE = 분류 보존 위해 fail-soft.
    호출자는 반환값 None 을 정상 경로로 처리 (다음 종목 진행).
    """
    try:
        frozen_at = datetime.now(timezone.utc)
        path = _path_for(FREEZE_ROOT, ticker, stage, frozen_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact_bytes)
        sha = hashlib.sha256(artifact_bytes).hexdigest()
        uri = f"file://{path}"

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO classification_freezes
                  (classification_id, ticker, stage, frozen_at,
                   artifact_uri, artifact_sha256, artifact_size_bytes, content_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    classification_id, ticker, stage, frozen_at,
                    uri, sha, len(artifact_bytes), content_type,
                ),
            )
            row_id = cur.fetchone()[0]
        conn.commit()

        return ClassificationFreeze(
            id=row_id,
            classification_id=classification_id,
            ticker=ticker,
            stage=stage,
            frozen_at=frozen_at,
            artifact_uri=uri,
            artifact_sha256=sha,
            artifact_size_bytes=len(artifact_bytes),
            content_type=content_type,
        )
    except Exception as exc:
        log.warning(
            "[FREEZE] save failed ticker=%s stage=%s classification_id=%s reason=%s",
            ticker, stage, classification_id, exc,
        )
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def fetch_latest_freeze(
    conn: Connection, ticker: str, stage: str,
) -> Optional[ClassificationFreeze]:
    """해당 ticker+stage 의 가장 최근 freeze 반환. 없으면 None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, classification_id, ticker, stage, frozen_at,
                   artifact_uri, artifact_sha256, artifact_size_bytes, content_type
              FROM classification_freezes
             WHERE ticker = %s AND stage = %s
             ORDER BY frozen_at DESC
             LIMIT 1
            """,
            (ticker, stage),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return ClassificationFreeze(*row)


def read_artifact_from_uri(uri: str) -> bytes:
    """file:// scheme 만 구현. s3:// 등 미래 scheme 는 NotImplementedError."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise NotImplementedError(
            f"freeze_store: scheme '{parsed.scheme}' not implemented"
            " (only file:// supported; s3:// to be added in future cycle)"
        )
    return Path(parsed.path).read_bytes()
