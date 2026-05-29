"""freeze_store 모듈 — save/fetch/read TDD."""
from __future__ import annotations
import hashlib
from pathlib import Path

import pytest
from api.services.freeze_store import (
    save_freeze, fetch_latest_freeze, read_artifact_from_uri,
)


def test_save_freeze_writes_file_and_db_row(db, tmp_path, monkeypatch):
    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)
    artifact = b"PK\x03\x04fake zip bytes"

    rec = save_freeze(
        db,
        artifact_bytes=artifact,
        content_type="application/zip",
        ticker="005850",
        stage="weekend",
        classification_id=None,
    )

    assert rec is not None
    assert rec.ticker == "005850"
    assert rec.stage == "weekend"
    assert rec.artifact_sha256 == hashlib.sha256(artifact).hexdigest()
    assert rec.artifact_size_bytes == len(artifact)
    assert rec.artifact_uri.startswith("file://")

    path = Path(rec.artifact_uri.removeprefix("file://"))
    assert path.exists()
    assert path.read_bytes() == artifact


def test_save_freeze_fail_soft_returns_none(db, monkeypatch):
    """디스크 쓰기 실패 → log + None 반환 (raise 안 함)."""
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.write_bytes", boom)

    rec = save_freeze(
        db,
        artifact_bytes=b"x",
        content_type="application/zip",
        ticker="005850",
        stage="weekend",
        classification_id=None,
    )
    assert rec is None


def test_fetch_latest_freeze_returns_most_recent_for_stage(db, tmp_path, monkeypatch):
    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)
    save_freeze(db, artifact_bytes=b"v1", content_type="application/zip",
                ticker="005850", stage="weekend", classification_id=None)
    save_freeze(db, artifact_bytes=b"v2", content_type="application/zip",
                ticker="005850", stage="weekend", classification_id=None)

    latest = fetch_latest_freeze(db, "005850", "weekend")
    assert latest is not None
    assert read_artifact_from_uri(latest.artifact_uri) == b"v2"


def test_fetch_latest_freeze_none_when_missing(db):
    assert fetch_latest_freeze(db, "NONEXIST", "weekend") is None


def test_read_artifact_from_uri_rejects_unknown_scheme():
    with pytest.raises(NotImplementedError):
        read_artifact_from_uri("s3://bucket/key.zip")
