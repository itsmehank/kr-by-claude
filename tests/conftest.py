import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest
from dotenv import load_dotenv

load_dotenv()

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


@pytest.fixture
def db(test_db_url):
    """매 테스트마다 트랜잭션 → ROLLBACK 으로 격리."""
    conn = psycopg.connect(test_db_url, autocommit=False)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
