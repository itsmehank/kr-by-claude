import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest
from dotenv import load_dotenv

load_dotenv()

# ── KRX 자격증명 무력화 (#92) ────────────────────────────────────────
# pykrx 는 import 시점에 build_krx_session() 을 호출해 KRX 로 로그인 POST 를 보낸다
# (pykrx/website/comm/webio.py:12). 자격증명이 falsy 면 HTTP 없이 None 을 반환하므로
# (comm/auth.py:176-181) 테스트 모듈 import 전에 여기서 값을 비운다. conftest 는
# 테스트 수집보다 먼저 로드되므로 순서가 보장된다.
#
# ⚠️ pop 하면 안 된다 — kr_pipeline/common/config.py:5 가 import 시 load_dotenv() 를
# 다시 돌리고, dotenv 는 "키가 os.environ 에 없을 때만" 주입하므로(dotenv/main.py:105)
# 제거한 값이 복원된다. 키는 남기고 값만 비운다.
#
# 라이브 호출이 필요한 실행만 KR_ALLOW_KRX=1 로 명시 해제한다.
if os.environ.get("KR_ALLOW_KRX") != "1":
    os.environ["KRX_ID"] = ""
    os.environ["KRX_PW"] = ""

SCHEMA_PATH = Path(__file__).parent.parent / "kr_pipeline" / "db" / "schema.sql"


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture(scope="session", autouse=True)
def _setup_schema(test_db_url):
    """세션 시작 시 스키마 완전 리셋 후 schema.sql 적용.

    리셋 이유: 테스트가 commit 한 잔존행·구버전 컬럼이 세션을 넘어 누적되면
    (schema.sql 재적용만으로는 안 지워짐) UniqueViolation/전량-SELECT 오염으로
    베이스라인 실패가 표류한다. 매 세션 빈 스키마에서 시작해 기대 실패 0 을 유지.
    """
    # DROP 안전 가드: dbname 에 'test' 가 없으면 production 오지정으로 보고 즉시 중단
    dbname = urlparse(test_db_url).path.lstrip("/")
    if "test" not in dbname:
        pytest.exit(
            f"TEST_DATABASE_URL dbname={dbname!r} 에 'test' 미포함 — DROP SCHEMA 거부",
            returncode=1,
        )
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", test_db_url, "-f", str(SCHEMA_PATH)],
        check=True, capture_output=True,
    )


@pytest.fixture(autouse=True)
def _isolate_eltd_cache(tmp_path, monkeypatch):
    """#92: ELTD 파일 캐시를 테스트별로 격리.

    필요한 이유 둘:
    ① 신규 캐시 테스트끼리 같은 키를 공유한다 — test_failure_is_not_cached 가
       "캐시 없음"을 단정하는데 test_expected_latest_writes_cache 가 먼저 같은 키
       (2026-06-10:post)를 쓰면 정의 순서상 확실히 깨진다(실행 순서 = 파일 정의 순).
    ② 격리가 없으면 suite 가 운영 캐시(~/.kr-by-claude/state/eltd.cache)를 오염시킨다.
    """
    monkeypatch.setenv("ELTD_CACHE", str(tmp_path / "eltd.cache"))


@pytest.fixture
def db(test_db_url):
    """매 테스트마다 트랜잭션 → ROLLBACK 으로 격리."""
    conn = psycopg.connect(test_db_url, autocommit=False)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
