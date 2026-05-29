# FREEZE 최소판 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal**: 분류 (weekend + daily_delta) 시점의 분석 입력 ZIP 을 사후 검증 가능하도록
재현 보존. 메커니즘 범용화 (artifact_* + content_type + stage) 로 후속 entry_params/pivot
freeze 가 한 줄 추가로 가능하게.

**Architecture**: ZIP bytes 를 로컬 디스크 (`data/freezes/{stage}/{YYYY-MM}/`) 에 저장,
DB `classification_freezes` 에 URI + 해시 + 메타. verify endpoint 가 frozen 우선 +
없으면 재빌드 + 경고. retention 은 분리 cron (90일 + 활성 보호 + stage 별 최소 1건).

**Tech Stack**: psycopg / FastAPI / pytest. 신규 모듈: `api/services/freeze_store.py`,
`kr_pipeline/llm_runner/freeze_cleanup.py`. 신규 마이그레이션 SQL.

**Spec**: `docs/superpowers/specs/2026-05-29-freeze-minimal-design.md`

**Non-goals (다시 확인)**:
- entry_params / pivot freeze 실제 구현 (한 줄 추가 가능하게만)
- S3 백엔드 구현 (`s3://` 는 NotImplementedError)
- UI diff 시각화
- Lazy cleanup (분석 경로 결합 금지)

---

## Task 1: DB 마이그레이션 — `classification_freezes` 테이블

**Files:**
- Create: `kr_pipeline/db/migrations/0XX_create_classification_freezes.sql`
- Modify (마이그레이션 runner 가 패턴 매칭이면 자동 적용. 명시적 등록 필요하면): `kr_pipeline/db/migrations/__init__.py` 등 (실제 패턴은 기존 마이그레이션 파일 확인 후 결정)

- [ ] **Step 1: 기존 마이그레이션 패턴 확인**

```bash
ls -la kr_pipeline/db/migrations/ | head -20
cat kr_pipeline/db/migrations/$(ls kr_pipeline/db/migrations/*.sql | tail -1 | xargs basename)
```

기존 파일명 규약 (번호 prefix?) 및 SQL 스타일 (BEGIN/COMMIT? IF NOT EXISTS?) 확인.

- [ ] **Step 2: 마이그레이션 SQL 작성**

```sql
-- 0XX_create_classification_freezes.sql

CREATE TABLE IF NOT EXISTS classification_freezes (
    id                  BIGSERIAL PRIMARY KEY,
    classification_id   BIGINT REFERENCES classifications(id),
    ticker              TEXT NOT NULL,
    stage               TEXT NOT NULL,
    frozen_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    artifact_uri        TEXT NOT NULL,
    artifact_sha256     TEXT NOT NULL,
    artifact_size_bytes BIGINT NOT NULL,
    content_type        TEXT NOT NULL DEFAULT 'application/zip',
    CONSTRAINT classification_freezes_uri_unique UNIQUE (artifact_uri),
    CONSTRAINT classification_freezes_stage_chk CHECK (stage IN ('weekend','daily_delta','entry_params','pivot'))
);

CREATE INDEX IF NOT EXISTS classification_freezes_ticker_frozen_at_idx
  ON classification_freezes(ticker, frozen_at DESC);

CREATE INDEX IF NOT EXISTS classification_freezes_classification_id_idx
  ON classification_freezes(classification_id)
  WHERE classification_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS classification_freezes_stage_frozen_at_idx
  ON classification_freezes(stage, frozen_at);
```

- [ ] **Step 3: 마이그레이션 실행 + 검증**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
uv run python -m kr_pipeline.db.migrate  # (실제 진입점은 기존 패턴 따름)
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from kr_pipeline.db.connection import connect
with connect() as conn, conn.cursor() as cur:
    cur.execute(\"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='classification_freezes' ORDER BY ordinal_position\")
    for r in cur.fetchall(): print(r)
"
```

Expected: 9 컬럼 출력 (id, classification_id, ticker, stage, frozen_at, artifact_uri, artifact_sha256, artifact_size_bytes, content_type).

- [ ] **Step 4: Commit**

```bash
git add kr_pipeline/db/migrations/0XX_create_classification_freezes.sql
git commit -m "feat(freeze): classification_freezes 테이블 마이그레이션

artifact_* 일반화 + stage CHECK + classification_id nullable.
인덱스 3개: ticker/frozen_at, classification_id (partial), stage/frozen_at."
```

---

## Task 2: `api/services/freeze_store.py` 모듈

**Files:**
- Create: `api/services/freeze_store.py`
- Test: `tests/test_api_freeze_store.py`

- [ ] **Step 1: Failing tests**

```python
# tests/test_api_freeze_store.py
from __future__ import annotations
import hashlib
from pathlib import Path
from datetime import datetime, timezone

import pytest
from api.services.freeze_store import (
    save_freeze, fetch_latest_freeze, read_artifact_from_uri,
)


def test_save_freeze_writes_file_and_db_row(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)
    artifact = b"PK\x03\x04fake zip bytes"

    rec = save_freeze(
        db_conn,
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


def test_save_freeze_fail_soft_returns_none(db_conn, monkeypatch):
    """디스크 쓰기 실패 → log + None 반환 (raise 안 함)."""
    def boom(*a, **k): raise OSError("disk full")
    monkeypatch.setattr("pathlib.Path.write_bytes", boom)

    rec = save_freeze(
        db_conn,
        artifact_bytes=b"x",
        content_type="application/zip",
        ticker="005850",
        stage="weekend",
        classification_id=None,
    )
    assert rec is None


def test_fetch_latest_freeze_returns_most_recent_for_stage(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)
    save_freeze(db_conn, artifact_bytes=b"v1", content_type="application/zip",
                ticker="005850", stage="weekend", classification_id=None)
    save_freeze(db_conn, artifact_bytes=b"v2", content_type="application/zip",
                ticker="005850", stage="weekend", classification_id=None)

    latest = fetch_latest_freeze(db_conn, "005850", "weekend")
    assert latest is not None
    assert read_artifact_from_uri(latest.artifact_uri) == b"v2"


def test_fetch_latest_freeze_none_when_missing(db_conn):
    assert fetch_latest_freeze(db_conn, "NONEXIST", "weekend") is None


def test_read_artifact_from_uri_rejects_unknown_scheme():
    with pytest.raises(NotImplementedError):
        read_artifact_from_uri("s3://bucket/key.zip")
```

- [ ] **Step 2: Run tests — verify FAIL**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
uv run pytest tests/test_api_freeze_store.py -v
```

Expected: ImportError / ModuleNotFoundError (모듈 없음).

- [ ] **Step 3: 구현**

```python
# api/services/freeze_store.py
"""Classification freeze store — ZIP 등 artifact 보존/조회.

Phase 0 Step 4 (사용자 v3 + 추가 4건):
- artifact_* 일반화 + content_type.
- save_freeze 는 *fail-soft* — 실패 시 None 반환 + log.warning.
  분석 경로가 freeze 실패로 중단되면 안 됨.
- read_artifact_from_uri 는 file:// 만 구현, s3:// 등은 NotImplementedError.
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


def _path_for(ticker: str, stage: str, frozen_at: datetime) -> Path:
    ym = frozen_at.strftime("%Y-%m")
    ts = frozen_at.strftime("%Y%m%d_%H%M%S")
    return FREEZE_ROOT / stage / ym / f"{ticker}_{ts}.zip"


def save_freeze(
    conn: Connection,
    *,
    artifact_bytes: bytes,
    content_type: str,
    ticker: str,
    stage: str,
    classification_id: Optional[int],
) -> Optional[ClassificationFreeze]:
    """Freeze artifact. *Fail-soft* — 실패 시 None 반환 + log.warning."""
    try:
        frozen_at = datetime.now(timezone.utc)
        path = _path_for(ticker, stage, frozen_at)
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
                (classification_id, ticker, stage, frozen_at,
                 uri, sha, len(artifact_bytes), content_type),
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
    except Exception as e:
        log.warning(
            "[FREEZE] save failed ticker=%s stage=%s classification_id=%s reason=%s",
            ticker, stage, classification_id, e,
        )
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def fetch_latest_freeze(
    conn: Connection, ticker: str, stage: str,
) -> Optional[ClassificationFreeze]:
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
            f"freeze_store: scheme '{parsed.scheme}' not implemented (only file:// supported)"
        )
    return Path(parsed.path).read_bytes()
```

- [ ] **Step 4: Run tests — verify PASS**

```bash
uv run pytest tests/test_api_freeze_store.py -v
```

Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add api/services/freeze_store.py tests/test_api_freeze_store.py
git commit -m "feat(freeze): freeze_store 모듈 — save/fetch/read API + fail-soft

artifact_* 일반화 + content_type. save_freeze 는 fail-soft (실패 시
None + log.warning) — 분석 경로 결합 금지.
read_artifact_from_uri 는 file:// 만, s3:// 는 NotImplementedError."
```

---

## Task 3: weekend.py / daily_delta.py 에 save_freeze 통합

**Files:**
- Modify: `kr_pipeline/llm_runner/weekend.py` — ZIP 빌드 직후 save_freeze 호출
- Modify: `kr_pipeline/llm_runner/daily_delta.py` — 동일 패턴
- Test: `tests/test_llm_runner_freeze_integration.py`

- [ ] **Step 1: 기존 ZIP 빌드 + classification 저장 흐름 확인**

```bash
grep -n "build_analysis_zip\|insert.*classifications\|classified_at" kr_pipeline/llm_runner/weekend.py
grep -n "build_analysis_zip\|insert.*classifications\|classified_at" kr_pipeline/llm_runner/daily_delta.py
```

목표: `build_analysis_zip(conn, ticker)` 호출 직후 `classification_id` 확보 가능한 지점
(classification row insert 직후) 에 `save_freeze` 삽입.

- [ ] **Step 2: Failing integration test**

```python
# tests/test_llm_runner_freeze_integration.py
"""weekend 단계가 분류 1건마다 freeze 1건을 생성하는지."""
def test_weekend_run_creates_freeze_per_classification(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)
    # ... weekend.run_once(limit=1, dry_llm=True) 호출 후
    # ... classification_freezes 행 1건 존재 확인
    # ... stage='weekend', classification_id 매칭, artifact_sha256 == sha256(빌드된 ZIP)
```

(실제 fixture/dry_llm 인터페이스는 기존 runner 테스트 확인 후 작성)

- [ ] **Step 3: Run — verify FAIL**

```bash
uv run pytest tests/test_llm_runner_freeze_integration.py -v
```

Expected: 0 freezes (아직 통합 안 됨).

- [ ] **Step 4: weekend.py 에 save_freeze 호출 추가**

기존 `build_analysis_zip(conn, symbol)` 호출부 + classification insert 직후:

```python
from api.services.freeze_store import save_freeze

# ... 기존 코드:
zip_bytes = build_analysis_zip(conn, symbol)
# ... LLM 호출 + classification row 저장 (classification_id 확보)
# ↓ 추가:
save_freeze(
    conn,
    artifact_bytes=zip_bytes,
    content_type="application/zip",
    ticker=symbol,
    stage="weekend",
    classification_id=classification_id,
)
# 반환값 무시 — fail-soft, 분석 진행 영향 없음.
```

- [ ] **Step 5: daily_delta.py 동일 적용**

`stage="daily_delta"` 만 차이.

- [ ] **Step 6: Run tests — verify PASS**

```bash
uv run pytest tests/test_llm_runner_freeze_integration.py tests/test_api_freeze_store.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add kr_pipeline/llm_runner/weekend.py kr_pipeline/llm_runner/daily_delta.py tests/test_llm_runner_freeze_integration.py
git commit -m "feat(freeze): weekend/daily_delta 가 분류 시점 ZIP 을 freeze

build_analysis_zip 직후 + classification row 저장 후 save_freeze 호출.
fail-soft — freeze 실패는 분석 진행 영향 없음.
stage='weekend' / 'daily_delta' 구분."
```

---

## Task 4: verify endpoint frozen 우선 + warning

**Files:**
- Modify: `api/routers/prompts.py` — mode=verify 시 frozen 우선
- Modify: `api/services/zip_builder.py` (필요 시) — warning 반환 인터페이스
- Test: `tests/test_api_prompts_verify_frozen.py`

- [ ] **Step 1: 기존 verify endpoint 확인**

```bash
grep -n "mode\|verify\|build_analysis_zip" api/routers/prompts.py | head -30
```

현재 verify mode 가 어떻게 분기되는지 + warning 메커니즘 (header? response field?) 결정.

- [ ] **Step 2: Failing test**

```python
def test_verify_mode_returns_frozen_when_available(client, db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)
    fake_zip = b"PK\x03\x04frozen content"
    save_freeze(db_conn, artifact_bytes=fake_zip, content_type="application/zip",
                ticker="005850", stage="weekend", classification_id=None)

    resp = client.get("/api/prompts/005850.zip?mode=verify")
    assert resp.status_code == 200
    assert resp.content == fake_zip
    assert resp.headers.get("X-Freeze-Origin") == "frozen"  # 또는 응답 body field


def test_verify_mode_falls_back_with_warning_when_no_freeze(client):
    resp = client.get("/api/prompts/UNKNOWN.zip?mode=verify")
    # frozen 없음 → 재빌드 + warning
    assert resp.status_code in (200, 404)  # ticker 자체 없으면 404
    if resp.status_code == 200:
        assert resp.headers.get("X-Freeze-Origin") == "rebuilt"
        assert "원본 아님" in resp.headers.get("X-Freeze-Warning", "")
```

- [ ] **Step 3: Run — verify FAIL**

```bash
uv run pytest tests/test_api_prompts_verify_frozen.py -v
```

- [ ] **Step 4: prompts.py 구현**

```python
from api.services.freeze_store import fetch_latest_freeze, read_artifact_from_uri

# verify mode 분기 (mode='verify' 인 경우):
if mode == "verify":
    for stage in ("weekend", "daily_delta"):
        frozen = fetch_latest_freeze(conn, ticker, stage)
        if frozen:
            zip_bytes = read_artifact_from_uri(frozen.artifact_uri)
            return Response(
                content=zip_bytes,
                media_type="application/zip",
                headers={
                    "X-Freeze-Origin": "frozen",
                    "X-Freeze-Stage": frozen.stage,
                    "X-Freeze-Frozen-At": frozen.frozen_at.isoformat(),
                },
            )
    # frozen 없음 → 재빌드 + warning header
    zip_bytes = build_analysis_zip(conn, ticker)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "X-Freeze-Origin": "rebuilt",
            "X-Freeze-Warning": "원본 아님 (재빌드됨) — 분류 시점 데이터가 freeze 되어 있지 않습니다.",
        },
    )
```

- [ ] **Step 5: Run — verify PASS**

```bash
uv run pytest tests/test_api_prompts_verify_frozen.py -v
```

- [ ] **Step 6: Commit**

```bash
git add api/routers/prompts.py tests/test_api_prompts_verify_frozen.py
git commit -m "feat(freeze): verify endpoint 가 frozen 우선 + warning 헤더

mode=verify 시:
- weekend → daily_delta 순으로 fetch_latest_freeze 시도.
- 있으면 file:// 에서 읽어 그대로 반환 + X-Freeze-Origin=frozen.
- 없으면 build_analysis_zip 재빌드 + X-Freeze-Origin=rebuilt
  + X-Freeze-Warning='원본 아님 (재빌드됨)…'."
```

---

## Task 5: UI — PromptPage 가 warning 표시

**Files:**
- Modify: `web/src/pages/PromptPage.tsx`

- [ ] **Step 1: 기존 ZIP 다운로드 흐름 확인**

```bash
grep -n "verify\|/api/prompts\|fetch\|zip" web/src/pages/PromptPage.tsx | head -20
```

verify mode 진입점 (URL param? 버튼?) 확인.

- [ ] **Step 2: warning 표시 컴포넌트 추가**

verify 모드 ZIP 다운로드 시 응답 헤더 검사:

```tsx
const resp = await fetch(`/api/prompts/${ticker}.zip?mode=verify`);
const origin = resp.headers.get("X-Freeze-Origin");
const warning = resp.headers.get("X-Freeze-Warning");

if (origin === "rebuilt" && warning) {
  // 사용자에게 노출: "⚠️ 원본 아님 (재빌드됨) — 분류 시점 데이터가 freeze 되어 있지 않습니다."
}
```

기존 UI 패턴 (alert? toast? inline?) 에 맞춰 표시.

- [ ] **Step 3: 수동 검증**

```bash
# dev server 띄운 상태에서
# (a) 5/29 분류 종목 (frozen 존재) → frozen 표시 없음 또는 "원본" 표시
# (b) 5/28 이전 분류 종목 (frozen 미생성) → "원본 아님 (재빌드됨)" 표시
```

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/PromptPage.tsx
git commit -m "feat(freeze): UI 가 X-Freeze-Origin/Warning 헤더 표시

verify 모드 다운로드 시 X-Freeze-Origin=rebuilt 이면 사용자에게
'원본 아님 (재빌드됨)' 경고 노출 — 검증자가 원본 vs 재빌드본을
명시적으로 인지."
```

---

## Task 6: Retention cron — `freeze_cleanup.py`

**Files:**
- Create: `kr_pipeline/llm_runner/freeze_cleanup.py`
- Test: `tests/test_freeze_cleanup.py`
- Modify (선택): pipeline_runs 등록 부 — 기존 runner 등록 패턴 확인

- [ ] **Step 1: Failing tests**

```python
def test_cleanup_dry_run_does_not_delete(db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)
    # 90일 초과 + ignore 상태 분류 1건 + 활성 분류 1건 + 종목별 최근 1건 보존
    # cleanup(dry_run=True) → DB/디스크 변경 없음, 후보 리스트만 반환


def test_cleanup_deletes_only_old_inactive_non_latest(db_conn, tmp_path, monkeypatch):
    """삭제 기준 3-AND 모두 충족하는 행만 삭제."""
    # 시나리오:
    #  - F1: 100일전, classification_id NULL → 후보지만 stage 최근 1건이면 보존
    #  - F2: 100일전, classification active=True → 보존 (활성 보호)
    #  - F3: 100일전, classification ignore → 삭제 대상
    #  - F4: 30일전 → 90일 룰 미충족, 보존
    # cleanup(dry_run=False) 후 F3 만 삭제 확인


def test_cleanup_preserves_latest_per_stage_per_ticker(db_conn, tmp_path, monkeypatch):
    """동일 ticker+stage 의 가장 최근 freeze 는 100일전이어도 항상 보존."""
    # ...


def test_cleanup_null_classification_id_passes_active_check(db_conn, tmp_path, monkeypatch):
    """classification_id IS NULL 인 freeze 는 활성 보호 sub-rule 자동 통과."""
    # ...
```

- [ ] **Step 2: Run — verify FAIL**

```bash
uv run pytest tests/test_freeze_cleanup.py -v
```

- [ ] **Step 3: 구현**

```python
# kr_pipeline/llm_runner/freeze_cleanup.py
"""Freeze retention cron — 90일 + 활성 보호 + stage별 최근 1건 보존.

분리 cron — lazy cleanup 금지 (분석 경로 결합 → cleanup 실패가 분석 실패 유발).
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import List

from psycopg import Connection

log = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    candidates: int
    deleted: int
    bytes_freed: int


def cleanup(conn: Connection, *, dry_run: bool = True, retention_days: int = 90) -> CleanupResult:
    """삭제 기준 (AND):
       1. frozen_at < NOW() - retention_days days
       2. 활성 분류 보호 — classification_id IS NULL 자동 통과,
          NOT NULL 이면 classifications.status IN ('archive','ignore')
       3. 종목별 (ticker, stage) 그룹의 MAX(frozen_at) 행은 제외.
    """
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH latest AS (
              SELECT DISTINCT ON (ticker, stage) id
                FROM classification_freezes
               ORDER BY ticker, stage, frozen_at DESC
            )
            SELECT f.id, f.artifact_uri, f.artifact_size_bytes
              FROM classification_freezes f
              LEFT JOIN classifications c ON c.id = f.classification_id
             WHERE f.frozen_at < NOW() - INTERVAL '%s days'
               AND (f.classification_id IS NULL OR c.status IN ('archive','ignore'))
               AND f.id NOT IN (SELECT id FROM latest)
        """, (retention_days,))
        rows = cur.fetchall()

    candidates = len(rows)
    deleted = 0
    bytes_freed = 0

    if dry_run:
        log.info("[FREEZE_CLEANUP] dry_run candidates=%d", candidates)
        return CleanupResult(candidates=candidates, deleted=0, bytes_freed=0)

    for row_id, uri, size in rows:
        # 파일 삭제 (file:// 만; s3:// 는 NotImplementedError 가 raise → log+skip)
        try:
            parsed = urlparse(uri)
            if parsed.scheme == "file":
                p = Path(parsed.path)
                if p.exists():
                    p.unlink()
                # 디렉토리 비면 정리 (월별 prune 효과)
                try:
                    p.parent.rmdir()
                except OSError:
                    pass
            else:
                log.warning("[FREEZE_CLEANUP] unsupported scheme %s id=%d — skip", parsed.scheme, row_id)
                continue
            with conn.cursor() as cur:
                cur.execute("DELETE FROM classification_freezes WHERE id = %s", (row_id,))
            conn.commit()
            deleted += 1
            bytes_freed += size or 0
        except Exception as e:
            log.warning("[FREEZE_CLEANUP] delete failed id=%d uri=%s reason=%s", row_id, uri, e)
            conn.rollback()

    log.info("[FREEZE_CLEANUP] candidates=%d deleted=%d bytes_freed=%d", candidates, deleted, bytes_freed)
    return CleanupResult(candidates=candidates, deleted=deleted, bytes_freed=bytes_freed)


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    from kr_pipeline.db.connection import connect

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 삭제 (기본 dry-run)")
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO)
    with connect() as conn:
        result = cleanup(conn, dry_run=not args.apply, retention_days=args.days)
    print(f"candidates={result.candidates} deleted={result.deleted} bytes_freed={result.bytes_freed}")
```

- [ ] **Step 4: Run — verify PASS**

```bash
uv run pytest tests/test_freeze_cleanup.py -v
```

- [ ] **Step 5: Dry-run on real DB**

```bash
uv run python -m kr_pipeline.llm_runner.freeze_cleanup
```

Expected: `candidates=0 deleted=0 bytes_freed=0` (방금 시작했으니 90일 초과 행 없음).

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/llm_runner/freeze_cleanup.py tests/test_freeze_cleanup.py
git commit -m "feat(freeze): freeze_cleanup cron — 90일 + 활성 보호 + 최근 1건 보존

분리 cron (lazy cleanup 금지). 삭제 기준 AND:
1) frozen_at < NOW() - 90 days
2) classification_id IS NULL 자동통과 / NOT NULL 이면 status IN (archive,ignore)
3) (ticker, stage) 그룹의 MAX(frozen_at) 보존 — 최소 1건

CLI: uv run python -m kr_pipeline.llm_runner.freeze_cleanup [--apply] [--days N]
기본 dry-run."
```

---

## Task 7: End-to-end 검증

- [ ] **Step 1: 실제 weekend run 1종목 dry_llm 실행**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
uv run python -m kr_pipeline.llm_runner.weekend --limit 1 --dry-llm 2>&1 | tail -20
```

Expected: classifications 1건 추가 + classification_freezes 1건 추가.

- [ ] **Step 2: DB 확인**

```bash
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from kr_pipeline.db.connection import connect
with connect() as conn, conn.cursor() as cur:
    cur.execute('SELECT ticker, stage, frozen_at, artifact_uri, artifact_size_bytes FROM classification_freezes ORDER BY frozen_at DESC LIMIT 5')
    for r in cur.fetchall(): print(r)
"
```

Expected: 행 1건 이상, artifact_uri 가 `file:///.../data/freezes/weekend/2026-05/...zip`.

- [ ] **Step 3: 파일 존재 + 해시 일치 확인**

```bash
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from kr_pipeline.db.connection import connect
from api.services.freeze_store import fetch_latest_freeze, read_artifact_from_uri
import hashlib
with connect() as conn:
    cur=conn.cursor(); cur.execute('SELECT ticker FROM classification_freezes ORDER BY frozen_at DESC LIMIT 1')
    t = cur.fetchone()[0]
    f = fetch_latest_freeze(conn, t, 'weekend')
    print('ticker=', t, 'uri=', f.artifact_uri)
    data = read_artifact_from_uri(f.artifact_uri)
    print('size_db=', f.artifact_size_bytes, 'size_disk=', len(data),
          'sha_match=', hashlib.sha256(data).hexdigest() == f.artifact_sha256)
"
```

Expected: `sha_match= True`.

- [ ] **Step 4: verify endpoint 호출**

```bash
curl -sI "http://localhost:8000/api/prompts/<ticker>.zip?mode=verify" | grep -i "x-freeze"
```

Expected: `X-Freeze-Origin: frozen`.

- [ ] **Step 5: fail-soft 시뮬레이션**

```bash
# data/freezes 디렉토리에서 쓰기 권한 제거 후 weekend run — 분류는 진행되어야 함
chmod -w data/freezes
uv run python -m kr_pipeline.llm_runner.weekend --limit 1 --dry-llm
chmod +w data/freezes
# log 에 '[FREEZE] save failed' 1건 + 분류 결과는 정상 저장 확인
```

- [ ] **Step 6: pytest 전체 회귀**

```bash
uv run pytest tests/ -x --ignore=tests/test_weekly --ignore=tests/test_llm --ignore=tests/test_ohlcv 2>&1 | tail -10
```

Expected: 새 작업으로 baseline isolation fail 수 (~25) 증가 없음.

- [ ] **Step 7: 종합 commit (필요 시 verification doc)**

```bash
# 검증 결과 요약을 doc 로:
# docs/superpowers/verification/2026-05-29-step4-freeze/FINDINGS.md
git add docs/superpowers/verification/2026-05-29-step4-freeze/
git commit -m "docs(p2-step4-verify): FREEZE 최소판 end-to-end 검증 결과"
```

---

## Self-Review 체크리스트

- [x] Spec 의 4건 정정 반영 (artifact_*, fail-soft, NULL retention, 150GB cadence)
- [x] artifact_uri 가 URI 추상화 (file:// scheme) — s3:// 후속 한 줄 추가 지점 명확
- [x] save_freeze 가 fail-soft (Task 2 Step 1 의 test_save_freeze_fail_soft_returns_none + Task 3 Step 4 의 "반환값 무시" 주석)
- [x] retention 의 classification_id NULL 케이스 (Task 6 Step 1 test + Step 3 SQL `OR f.classification_id IS NULL`)
- [x] stage 컬럼 → entry_params 후속 추가 한 줄 (CHECK constraint 에 미리 포함)
- [x] DB BLOB-in-Postgres 없음 (path + 해시만)
- [x] lazy cleanup 없음 (분리 cron only)
- [x] 모든 단계 TDD (failing test → impl → pass)
- [x] verify endpoint 의 warning 헤더 (X-Freeze-Origin / X-Freeze-Warning)

## 실행 종료 후 다음

본 plan 완료 시 → **Step 5 (SCOPE) 진행**: 5/28 배치 2,416 종목 분류 결과 신뢰성 +
재실행 필요 여부 판단 + 잔여 5 종목 mismatch 원인 확인. 이후 **Phase 0 종료** 선언 →
**Phase 1 (룰 강화) brainstorming** 진입.
