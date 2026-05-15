import os
import subprocess
from pathlib import Path

import psycopg
import pytest


SCHEMA_PATH = Path(__file__).parent.parent / "kr_pipeline" / "db" / "schema.sql"


@pytest.fixture(scope="session")
def test_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


@pytest.fixture(scope="session", autouse=True)
def _setup_schema():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return
    subprocess.run(
        ["psql", url, "-f", str(SCHEMA_PATH)],
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
