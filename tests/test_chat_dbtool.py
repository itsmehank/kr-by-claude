"""(#281) 채팅 DB 조회 도구 — 조회 전용 계정의 쓰기 거부, 상한, 문장 검사.

쓰기 거부 시험은 실제 테이블이 아니라 이 파일이 임시로 만든 테이블(chat_ro_probe_*)만 대상으로 한다.
"""
import uuid

import psycopg
import pytest

from kr_pipeline.chat import dbtool


@pytest.fixture
def ro_url(test_db_url):
    return dbtool.with_ro_user(test_db_url)


@pytest.fixture
def probe(test_db_url):
    """주인 계정이 만든 임시 테이블(커밋됨 — 조회 전용 계정의 다른 연결에서도 보인다). 끝나면 지운다."""
    name = f"chat_ro_probe_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute(f"CREATE TABLE {name} (id int PRIMARY KEY, note text)")
        conn.execute(f"INSERT INTO {name} VALUES (1, 'a'), (2, 'b')")
    try:
        yield name
    finally:
        with psycopg.connect(test_db_url, autocommit=True) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {name}")


def _ro_conn(ro_url, *, read_only: bool):
    # read_only=False: 계정 기본값(읽기 전용 트랜잭션)을 꺼도 권한 자체로 막히는지 본다.
    opt = "on" if read_only else "off"
    return psycopg.connect(ro_url, autocommit=True, options=f"-c default_transaction_read_only={opt}")


def test_with_ro_user_swaps_only_the_user():
    assert dbtool.with_ro_user("postgresql://localhost/kr_test") == "postgresql://kr_chat_ro@localhost/kr_test"
    assert (dbtool.with_ro_user("postgresql://me:pw@db.local:5433/kr_pipeline?sslmode=disable")
            == "postgresql://kr_chat_ro@db.local:5433/kr_pipeline?sslmode=disable")


def test_chat_database_url_prefers_explicit(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/kr_pipeline")
    monkeypatch.delenv("CHAT_DATABASE_URL", raising=False)
    assert dbtool.chat_database_url() == "postgresql://kr_chat_ro@localhost/kr_pipeline"
    monkeypatch.setenv("CHAT_DATABASE_URL", "postgresql://x@h/d")
    assert dbtool.chat_database_url() == "postgresql://x@h/d"


@pytest.mark.parametrize("sql", [
    "INSERT INTO {t} VALUES (9, 'x')",
    "UPDATE {t} SET note = 'x'",
    "DELETE FROM {t}",
    "TRUNCATE {t}",
    "DROP TABLE {t}",
    "ALTER TABLE {t} ADD COLUMN z int",
    "CREATE TABLE chat_ro_should_not_exist (id int)",
])
def test_ro_role_cannot_write_even_with_read_only_off(ro_url, probe, sql):
    with _ro_conn(ro_url, read_only=False) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql.format(t=probe))


def test_ro_role_defaults_are_read_only_and_5s(ro_url):
    with psycopg.connect(ro_url, autocommit=True) as conn:
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        assert conn.execute("SHOW statement_timeout").fetchone()[0] == "5s"


def test_ro_role_can_select_new_table(ro_url, probe):
    # ALTER DEFAULT PRIVILEGES: 계정 적용 뒤에 생긴 테이블도 읽힌다.
    out = dbtool.run_query(f"SELECT id, note FROM {probe} ORDER BY id", url=ro_url)
    assert out.splitlines() == ['["id", "note"]', '[1, "a"]', '[2, "b"]']


@pytest.mark.parametrize("sql", [
    "", "   ;  ", "DELETE FROM stocks", "select 1; select 2", "EXPLAIN ANALYZE SELECT 1",
    "SET statement_timeout = 0", "COPY stocks TO STDOUT",
])
def test_run_query_rejects_non_select(ro_url, sql):
    assert dbtool.run_query(sql, url=ro_url).startswith("거부:")


def test_run_query_write_inside_cte_is_stopped_by_db(ro_url, probe):
    out = dbtool.run_query(f"WITH d AS (DELETE FROM {probe} RETURNING id) SELECT * FROM d", url=ro_url)
    assert out.startswith("오류:")
    assert dbtool.run_query(f"SELECT count(*) FROM {probe}", url=ro_url).splitlines()[1] == "[2]"


def test_run_query_trailing_semicolon_and_zero_rows(ro_url, probe):
    out = dbtool.run_query(f"select id from {probe} where id > 100;", url=ro_url)
    assert out.splitlines() == ['["id"]', "(0행)"]


def test_run_query_row_cap(ro_url):
    out = dbtool.run_query("SELECT g FROM generate_series(1, 500) g", url=ro_url).splitlines()
    assert len(out) == 1 + dbtool.MAX_ROWS + 1
    assert out[-1] == dbtool.TRUNCATED_ROWS.format(n=dbtool.MAX_ROWS)


def test_run_query_char_cap_and_cell_cap(ro_url):
    out = dbtool.run_query("SELECT repeat('가', 5000) AS t FROM generate_series(1, 100)", url=ro_url)
    lines = out.splitlines()
    assert lines[-1] == dbtool.TRUNCATED_CHARS.format(n=dbtool.MAX_CHARS)
    assert len(out) <= dbtool.MAX_CHARS + 200
    assert lines[1].endswith('…"]') and len(lines[1]) < dbtool.CELL_CHARS + 20


def test_run_query_statement_timeout(ro_url, monkeypatch):
    monkeypatch.setattr(dbtool, "STATEMENT_TIMEOUT_MS", 200)
    out = dbtool.run_query("SELECT pg_sleep(3)", url=ro_url)
    assert out.startswith("오류:") and "statement timeout" in out


def test_run_query_sql_error_is_text_not_exception(ro_url):
    assert dbtool.run_query("SELECT * FROM no_such_table_xyz", url=ro_url).startswith("오류:")


def test_run_query_cell_types(ro_url):
    out = dbtool.run_query(
        "SELECT 1.50::numeric AS n, 3::numeric AS i, DATE '2026-11-11' AS d, NULL AS z, "
        "'{\"a\": 1}'::jsonb AS j, true AS b", url=ro_url)
    assert out.splitlines()[1] == '[1.5, 3, "2026-11-11", null, "{\\"a\\": 1}", true]'


def test_describe_lists_tables_and_columns(ro_url, probe):
    listing = dbtool.describe(url=ro_url)
    assert probe in listing and "weekly_classification" in listing
    detail = dbtool.describe(probe, url=ro_url).splitlines()
    assert detail[0] == f"{probe} — 기본 키: id"
    assert "id | integer | NO" in detail and "note | text | YES" in detail


def test_describe_rejects_bad_name_and_unknown(ro_url):
    assert dbtool.describe("stocks; drop table x", url=ro_url).startswith("거부:")
    assert dbtool.describe("no_such_table_xyz", url=ro_url) == "테이블 없음: no_such_table_xyz"


def test_mcp_server_exposes_only_two_tools():
    import asyncio

    from kr_pipeline.chat import mcp_server

    tools = asyncio.run(mcp_server.server.list_tools())
    assert sorted(t.name for t in tools) == sorted(mcp_server.TOOL_NAMES) == ["describe", "query"]
