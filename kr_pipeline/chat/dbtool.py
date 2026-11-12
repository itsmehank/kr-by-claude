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
# MCP 서버 이름·도구 이름. 여기 두어 API(실행기)가 mcp 패키지를 import 하지 않게 한다.
SERVER_NAME = "krdb"
TOOL_NAMES = ("describe", "query")
STATEMENT_TIMEOUT_MS = 5000
MAX_ROWS = 200
MAX_CHARS = 20_000
CELL_CHARS = 2000  # 한 칸 상한(reasoning 같은 긴 글 열)
TRUNCATED_ROWS = "…(결과가 {n}행을 넘어 잘랐습니다. 조건을 좁히거나 LIMIT·집계를 쓰세요.)"
TRUNCATED_CHARS = "…(결과가 {n}자를 넘어 잘랐습니다. 열을 줄이거나 조건을 좁히세요.)"

_ALLOWED_HEAD = re.compile(r"(select|with)\b", re.IGNORECASE)
_DOLLAR_TAG = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")
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


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _skip_comment(s: str, i: int) -> int:
    """i 가 주석 시작이면 주석 끝 다음 위치, 아니면 i. 블록 주석은 겹칠 수 있다(PostgreSQL)."""
    if s.startswith("--", i):
        end = s.find("\n", i)
        return len(s) if end < 0 else end + 1
    if s.startswith("/*", i):
        depth, i = 1, i + 2
        while i < len(s) and depth:
            if s.startswith("/*", i):
                depth, i = depth + 1, i + 2
            elif s.startswith("*/", i):
                depth, i = depth - 1, i + 2
            else:
                i += 1
        return i
    return i


def _skip_blank(s: str, i: int, extra: str = "") -> int:
    """공백·주석(과 extra 글자)을 건너뛴 위치."""
    while i < len(s):
        if s[i].isspace() or s[i] in extra:
            i += 1
            continue
        j = _skip_comment(s, i)
        if j == i:
            break
        i = j
    return i


def _statement_end(s: str) -> int:
    """문자열·따옴표 이름·주석 밖에 있는 첫 세미콜론의 위치(없으면 len)."""
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == ";":
            return i
        if ch == "'":
            # E'..' 만 역슬래시가 다음 글자를 가린다(standard_conforming_strings=on)
            esc = i > 0 and s[i - 1] in "eE" and (i < 2 or not _is_word(s[i - 2]))
            i += 1
            while i < n:
                if esc and s[i] == "\\":
                    i += 2
                elif s[i] == "'":
                    if s.startswith("''", i):
                        i += 2
                    else:
                        break
                else:
                    i += 1
            i += 1
        elif ch == '"':
            end = s.find('"', i + 1)
            i = n if end < 0 else end + 1
        elif ch == "$" and (i == 0 or not _is_word(s[i - 1])) and (m := _DOLLAR_TAG.match(s, i)):
            end = s.find(m.group(0), m.end())
            i = n if end < 0 else end + len(m.group(0))
        else:
            j = _skip_comment(s, i)
            i = j if j > i else i + 1
    return n


def check_statement(sql: str) -> str:
    """SELECT/WITH 한 문장만 통과. 통과한 문장(끝 세미콜론 제거)을 돌려준다.

    문자열 안의 세미콜론, 앞머리 주석, 괄호로 시작하는 조회((SELECT …) UNION …)는 허용한다.
    """
    if not isinstance(sql, str):
        raise QueryRejected("sql 은 문자열이어야 합니다.")
    end = _statement_end(sql)
    if _skip_blank(sql, end, ";") < len(sql):
        raise QueryRejected("한 번에 한 문장만 실행할 수 있습니다.")
    stmt = sql[:end].strip()
    head = _skip_blank(stmt, 0)
    if head >= len(stmt):
        raise QueryRejected("빈 문장입니다.")
    if not _ALLOWED_HEAD.match(stmt, _skip_blank(stmt, head, "(")):
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
    if isinstance(v, (list, dict)):
        # 배열·JSON 열은 그대로 둔다(행을 JSON 으로 쓸 때 한 번만 인코딩). 너무 길 때만 글로 잘라 낸다.
        s = json.dumps(v, ensure_ascii=False, default=str)
        return s[:CELL_CHARS] + "…" if len(s) > CELL_CHARS else v
    s = v if isinstance(v, str) else str(v)
    return s[:CELL_CHARS] + "…" if len(s) > CELL_CHARS else s


def run_query(sql: str, *, url: str | None = None) -> str:
    """조회를 실행해 글로 돌려준다(첫 줄 = 열 이름, 이후 한 줄에 한 행의 JSON 배열)."""
    try:
        stmt = check_statement(sql)
    except QueryRejected as e:
        return f"거부: {e}"
    try:
        with _connect(url or chat_database_url()) as conn, conn.cursor() as cur:
            # 행 상한은 DB 에서 건다(큰 결과를 다 만들고 보내지 않게). 줄바꿈: 문장 끝의 -- 주석이 닫는 괄호를 삼키지 않게.
            cur.execute(f"SELECT * FROM (\n{stmt}\n) q LIMIT {MAX_ROWS + 1}")  # type: ignore[arg-type]
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
            if len(lines) == 1:  # 첫 행은 잘라서라도 낸다(열만 보고 "값 없음"으로 읽지 않게)
                lines.append(line[: max(MAX_CHARS - total - 2, 0)] + "…")
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
