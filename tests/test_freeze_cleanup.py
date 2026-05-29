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
    """classification_id IS NULL 인 freeze 도 ticker 활성 보호 미적용 시 정상 삭제.

    weekly_classification 에 해당 ticker 의 entry/watch 행이 없으면 활성 보호
    미적용 → 90일 + latest 조건만 적용.
    """
    from kr_pipeline.llm_runner.freeze_cleanup import cleanup

    now = datetime.now(timezone.utc)
    old_latest = now - timedelta(days=100)
    old_older = now - timedelta(days=130)

    # 2건 모두 classification_id=NULL, weekly_classification 행 없음
    f_old = _insert_freeze_direct(db, tmp_path, "CLEAN4", "weekend", old_older, suffix="a")
    f_latest = _insert_freeze_direct(db, tmp_path, "CLEAN4", "weekend", old_latest, suffix="b")

    result = cleanup(db, dry_run=False, retention_days=90)

    with db.cursor() as cur:
        # f_old: ticker 활성 행 없음 + 90일 초과 + not latest → 삭제
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (f_old,))
        assert cur.fetchone() is None, "Old freeze without active classification should be deleted"
        # f_latest: latest 이므로 보존
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (f_latest,))
        assert cur.fetchone() is not None, "Latest freeze must be preserved"


def _insert_weekly_classification(db, symbol: str, classified_at: datetime, classification: str):
    """weekly_classification 행 insert (테스트 fixture). 활성 보호 검증용."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
            (symbol, symbol),
        )
        cur.execute(
            """
            INSERT INTO weekly_classification
              (symbol, classified_at, market, classification, source)
            VALUES (%s, %s, 'KOSPI', %s, 'test')
            ON CONFLICT (symbol, classified_at) DO UPDATE SET classification = EXCLUDED.classification
            """,
            (symbol, classified_at, classification),
        )
    db.commit()


def test_cleanup_protects_freezes_when_ticker_has_active_entry(db, tmp_path):
    """ticker 의 가장 최근 weekly_classification 이 'entry' 면 그 ticker 의 모든
    freeze (오래되고 not-latest 여도) 보호.
    """
    from kr_pipeline.llm_runner.freeze_cleanup import cleanup

    now = datetime.now(timezone.utc)
    old_freeze_at = now - timedelta(days=130)
    older_freeze_at = now - timedelta(days=150)
    class_at = now - timedelta(days=5)

    # 2건 freeze, 모두 100일+. 그러나 ticker 가 활성 entry → 모두 보호
    f_older = _insert_freeze_direct(db, tmp_path, "ACTIVE_E", "weekend", older_freeze_at, suffix="a")
    f_old = _insert_freeze_direct(db, tmp_path, "ACTIVE_E", "weekend", old_freeze_at, suffix="b")
    _insert_weekly_classification(db, "ACTIVE_E", class_at, "entry")

    result = cleanup(db, dry_run=False, retention_days=90)

    with db.cursor() as cur:
        cur.execute("SELECT id FROM classification_freezes WHERE id = ANY(%s)", ([f_older, f_old],))
        rows = cur.fetchall()
        assert len(rows) == 2, "Both freezes must be preserved (ticker has active entry classification)"


def test_cleanup_protects_freezes_when_ticker_has_active_watch(db, tmp_path):
    """activation = 'watch' 도 보호 대상."""
    from kr_pipeline.llm_runner.freeze_cleanup import cleanup

    now = datetime.now(timezone.utc)
    old_freeze_at = now - timedelta(days=110)
    older_freeze_at = now - timedelta(days=130)
    class_at = now - timedelta(days=3)

    f_older = _insert_freeze_direct(db, tmp_path, "ACTIVE_W", "weekend", older_freeze_at, suffix="a")
    f_old = _insert_freeze_direct(db, tmp_path, "ACTIVE_W", "weekend", old_freeze_at, suffix="b")
    _insert_weekly_classification(db, "ACTIVE_W", class_at, "watch")

    result = cleanup(db, dry_run=False, retention_days=90)

    with db.cursor() as cur:
        cur.execute("SELECT id FROM classification_freezes WHERE id = ANY(%s)", ([f_older, f_old],))
        assert len(cur.fetchall()) == 2, "Both freezes must be preserved (active watch)"


def test_cleanup_deletes_when_latest_classification_is_ignore(db, tmp_path):
    """ticker 의 가장 최근 weekly_classification 이 'ignore' (또는 entry/watch 아님)
    이면 활성 보호 미적용 → 90일+not-latest 룰로 삭제 가능.

    또한 이전에 entry 였더라도 *최신* 이 ignore 면 보호 해제됨을 확인 (latest only).
    """
    from kr_pipeline.llm_runner.freeze_cleanup import cleanup

    now = datetime.now(timezone.utc)
    old_freeze_at = now - timedelta(days=130)
    recent_freeze_at = now - timedelta(days=30)
    past_entry_at = now - timedelta(days=200)
    recent_ignore_at = now - timedelta(days=5)

    # freeze 2건: 오래된 것 + 최신 것
    f_old = _insert_freeze_direct(db, tmp_path, "WAS_ACTIVE", "weekend", old_freeze_at, suffix="a")
    f_recent = _insert_freeze_direct(db, tmp_path, "WAS_ACTIVE", "weekend", recent_freeze_at, suffix="b")
    # 과거 entry → 최신 ignore
    _insert_weekly_classification(db, "WAS_ACTIVE", past_entry_at, "entry")
    _insert_weekly_classification(db, "WAS_ACTIVE", recent_ignore_at, "ignore")

    result = cleanup(db, dry_run=False, retention_days=90)

    with db.cursor() as cur:
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (f_old,))
        assert cur.fetchone() is None, \
            "Old freeze should be deleted (latest classification is ignore, not entry/watch)"
        cur.execute("SELECT id FROM classification_freezes WHERE id = %s", (f_recent,))
        assert cur.fetchone() is not None, "Recent freeze is latest → preserved by criterion 3"
