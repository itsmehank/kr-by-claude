"""freeze_cleanup cron — 90일 + 활성 보호 + 최근 1건 보존 TDD."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ── helpers ─────────────────────────────────────────────────────────────────

def _insert_freeze_direct(
    db,
    tmp_path: Path,
    ticker: str,
    stage: str,
    frozen_at: datetime,
    classification_id=None,
    suffix: str = "",
) -> int:
    """classification_freezes 에 직접 INSERT. freeze id 반환."""
    # ensure stock exists
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker, ticker),
        )

    ym = frozen_at.strftime("%Y-%m")
    ts = frozen_at.strftime("%Y%m%d_%H%M%S")
    path = tmp_path / stage / ym / f"{ticker}_{ts}{suffix}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"fake_{ticker}_{ts}{suffix}".encode())

    uri = f"file://{path}"
    sha = "00" * 32  # fake sha
    size = path.stat().st_size

    with db.cursor() as cur:
        cur.execute(
            """
            INSERT INTO classification_freezes
              (classification_id, ticker, stage, frozen_at,
               artifact_uri, artifact_sha256, artifact_size_bytes, content_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'application/zip')
            RETURNING id
            """,
            (classification_id, ticker, stage, frozen_at, uri, sha, size),
        )
        fid = cur.fetchone()[0]
    db.commit()
    return fid


# ── tests ────────────────────────────────────────────────────────────────────

def test_cleanup_dry_run_does_not_delete(db, tmp_path):
    """dry_run=True: DB/디스크 변경 없음, candidates 리스트만 반환."""
    from kr_pipeline.llm_runner.freeze_cleanup import cleanup

    now = datetime.now(timezone.utc)
    old_latest = now - timedelta(days=100)
    old_older = now - timedelta(days=120)

    # 2건: old_older 는 삭제 후보, old_latest 는 latest 보호
    f_old = _insert_freeze_direct(db, tmp_path, "CLEAN1", "weekend", old_older, suffix="a")
    f_latest = _insert_freeze_direct(db, tmp_path, "CLEAN1", "weekend", old_latest, suffix="b")

    result = cleanup(db, dry_run=True, retention_days=90)

    assert result.candidates >= 1
    assert result.deleted == 0

    # DB rows still exist
    with db.cursor() as cur:
        cur.execute("SELECT id FROM classification_freezes WHERE id = ANY(%s)", ([f_old, f_latest],))
        assert cur.rowcount == 2 or len(cur.fetchall()) == 2


def test_cleanup_deletes_only_old_inactive_non_latest(db, tmp_path):
    """삭제 기준 3-AND 모두 충족하는 행만 삭제.

    Scenario (2 tickers, ticker A has a recent entry protecting it):
    - tickerA/F1: 120일전 NULL → A 그룹의 최신 아님 (F3 가 최신) → 삭제 대상
    - tickerA/F3: 30일전 → 90일 룰 미충족 + latest → 보존
    - tickerB/F_only: 120일전 NULL → B 그룹의 유일한/최신 → latest 보호 보존
    """
    from kr_pipeline.llm_runner.freeze_cleanup import cleanup

    now = datetime.now(timezone.utc)
    old_A = now - timedelta(days=120)
    recent_A = now - timedelta(days=30)
    old_B = now - timedelta(days=120)

    # tickerA: 오래된 것 + 최신 것
    f_a_old = _insert_freeze_direct(db, tmp_path, "CLEAN2A", "weekend", old_A, suffix="a")
    f_a_new = _insert_freeze_direct(db, tmp_path, "CLEAN2A", "weekend", recent_A, suffix="b")
    # tickerB: 오래된 것 하나만 (latest 이므로 보존)
    f_b_only = _insert_freeze_direct(db, tmp_path, "CLEAN2B", "weekend", old_B, suffix="c")

    result = cleanup(db, dry_run=False, retention_days=90)

    with db.cursor() as cur:
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (f_a_old,))
        assert cur.fetchone() is None, "f_a_old (old, not latest of A) should be deleted"
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (f_a_new,))
        assert cur.fetchone() is not None, "f_a_new (recent, latest of A) should be preserved"
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (f_b_only,))
        assert cur.fetchone() is not None, "f_b_only (old but only/latest of B) should be preserved"

    assert result.deleted >= 1


def test_cleanup_preserves_latest_per_stage_per_ticker(db, tmp_path):
    """동일 ticker+stage 의 가장 최근 freeze 는 100일전이어도 항상 보존."""
    from kr_pipeline.llm_runner.freeze_cleanup import cleanup

    now = datetime.now(timezone.utc)
    only_old = now - timedelta(days=110)

    fid = _insert_freeze_direct(db, tmp_path, "CLEAN3", "weekend", only_old)

    result = cleanup(db, dry_run=False, retention_days=90)

    with db.cursor() as cur:
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (fid,))
        assert cur.fetchone() is not None, "Only/latest freeze must be preserved"


def test_cleanup_null_classification_id_passes_active_check(db, tmp_path):
    """classification_id IS NULL 인 freeze 는 활성 보호 sub-rule 자동 통과.

    즉 NULL인 freeze 는 90일 + latest 조건만 적용.
    """
    from kr_pipeline.llm_runner.freeze_cleanup import cleanup

    now = datetime.now(timezone.utc)
    old_latest = now - timedelta(days=100)
    old_older = now - timedelta(days=130)

    # 2건 모두 classification_id=NULL
    f_old = _insert_freeze_direct(db, tmp_path, "CLEAN4", "weekend", old_older, suffix="a")
    f_latest = _insert_freeze_direct(db, tmp_path, "CLEAN4", "weekend", old_latest, suffix="b")

    result = cleanup(db, dry_run=False, retention_days=90)

    with db.cursor() as cur:
        # f_old: NULL → active check 자동통과 + 90일 초과 + not latest → 삭제
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (f_old,))
        assert cur.fetchone() is None, "Old NULL freeze should be deleted"
        # f_latest: latest 이므로 보존
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (f_latest,))
        assert cur.fetchone() is not None, "Latest freeze must be preserved"
