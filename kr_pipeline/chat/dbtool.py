"""(#281) 채팅 전문가의 DB 조회 도구 본체 — describe / query.

방어는 두 겹이다. ① DB 계정(kr_chat_ro)이 SELECT 권한만 가진다(핵심). ② 여기서 문장을 검사하고
읽기 전용·시간 상한·결과 크기 상한을 건다(보조). MCP 포장은 mcp_server.py.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

import psycopg

RO_ROLE = "kr_chat_ro"
STATEMENT_TIMEOUT_MS = 5000
MAX_ROWS = 200
MAX_CHARS = 20_000
CELL_CHARS = 2000  # 한 칸 상한(reasoning 같은 긴 글 열)
TRUNCATED_ROWS = "…(결과가 {n}행을 넘어 잘랐습니다. 조건을 좁히거나 LIMIT·집계를 쓰세요.)"
TRUNCATED_CHARS = "…(결과가 {n}자를 넘어 잘랐습니다. 열을 줄이거나 조건을 좁히세요.)"

_ALLOWED_HEAD = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class QueryRejected(ValueError):
    """문장 검사에서 거부(실행하지 않았다)."""


def chat_database_url() -> str:
    """조회 전용 접속 주소. CHAT_DATABASE_URL 이 없으면 DATABASE_URL 의 계정만 kr_chat_ro 로 바꾼다."""
    explicit = os.environ.get("CHAT_DATABASE_URL")
    if explicit:
        return explicit
    return with_ro_user(os.environ["DATABASE_URL"])


def with_ro_user(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    netloc = f"{RO_ROLE}@{host}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def check_statement(sql: str) -> str:
    """SELECT/WITH 한 문장만 통과. 통과한 문장(끝 세미콜론 제거)을 돌려준다."""
    if not isinstance(sql, str):
        raise QueryRejected("sql 은 문자열이어야 합니다.")
    stmt = sql.strip().rstrip(";").strip()
    if not stmt:
        raise QueryRejected("빈 문장입니다.")
    if ";" in stmt:
        raise QueryRejected("한 번에 한 문장만 실행할 수 있습니다.")
    if not _ALLOWED_HEAD.match(stmt):
        raise QueryRejected("SELECT 또는 WITH 로 시작하는 조회 문장만 실행할 수 있습니다.")
    return stmt


def _connect(url: str) -> psycopg.Connection:
    opts = f"-c statement_timeout={STATEMENT_TIMEOUT_MS} -c default_transaction_read_only=on"
    return psycopg.connect(url, autocommit=True, options=opts, connect_timeout=5)


def _cell(v: object) -> object:
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, Decimal):
        if not v.is_finite():
            return str(v)
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s[:CELL_CHARS] + "…" if len(s) > CELL_CHARS else s


def run_query(sql: str, *, url: str | None = None) -> str:
    """조회를 실행해 글로 돌려준다(첫 줄 = 열 이름, 이후 한 줄에 한 행의 JSON 배열)."""
    try:
        stmt = check_statement(sql)
    except QueryRejected as e:
        return f"거부: {e}"
    try:
        with _connect(url or chat_database_url()) as conn, conn.cursor() as cur:
            cur.execute(stmt)  # type: ignore[arg-type]
            if cur.description is None:
                return "결과 없음(행을 돌려주지 않는 문장)"
            cols = [d.name for d in cur.description]
            rows = cur.fetchmany(MAX_ROWS + 1)
    except psycopg.Error as e:
        msg = (e.diag.message_primary if e.diag and e.diag.message_primary else str(e)).strip()
        return f"오류: {msg[:500]}"
    more = len(rows) > MAX_ROWS
    lines = [json.dumps(cols, ensure_ascii=False)]
    total = len(lines[0])
    clipped = False
    for r in rows[:MAX_ROWS]:
        line = json.dumps([_cell(v) for v in r], ensure_ascii=False, default=str)
        if total + len(line) + 1 > MAX_CHARS:
            clipped = True
            break
        lines.append(line)
        total += len(line) + 1
    if clipped:
        lines.append(TRUNCATED_CHARS.format(n=MAX_CHARS))
    elif more:
        lines.append(TRUNCATED_ROWS.format(n=MAX_ROWS))
    if len(lines) == 1:
        lines.append("(0행)")
    return "\n".join(lines)


def describe(table: str | None = None, *, url: str | None = None) -> str:
    """table 이 없으면 테이블 목록(대략 행 수), 있으면 그 테이블의 열·형태·기본 키."""
    if table is not None and not _TABLE_NAME.match(table):
        return "거부: 테이블 이름 형식이 틀렸습니다."
    try:
        with _connect(url or chat_database_url()) as conn, conn.cursor() as cur:
            if table is None:
                cur.execute(
                    "SELECT c.relname, c.reltuples::bigint FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r','v','m','p') ORDER BY 1"
                )
                rows = cur.fetchall()
                return "\n".join(["테이블 | 대략 행 수"] + [f"{n} | {max(k, 0)}" for n, k in rows])
            cur.execute(
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
                (table,),
            )
            cols = cur.fetchall()
            if not cols:
                return f"테이블 없음: {table}"
            cur.execute(
                "SELECT a.attname FROM pg_index i JOIN pg_attribute a "
                "ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = %s::regclass AND i.indisprimary ORDER BY a.attnum",
                (f"public.{table}",),
            )
            pk = [r[0] for r in cur.fetchall()]
    except psycopg.Error as e:
        msg = (e.diag.message_primary if e.diag and e.diag.message_primary else str(e)).strip()
        return f"오류: {msg[:500]}"
    out = [f"{table} — 기본 키: {', '.join(pk) if pk else '없음'}", "열 | 형태 | NULL 허용"]
    out += [f"{c} | {t} | {n}" for c, t, n in cols]
    return "\n".join(out)
