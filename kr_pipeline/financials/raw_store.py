"""#186 B — DART 원본 보존 저장 + 일별 호출 계정. dart_financials 와 독립(무변경).

- dart_fin_raw: 셀(corp_code, bsns_year, reprt_code) 당 응답 원문 JSONB + 사실 컬럼. status 013 은 no_data_reason 필수
  (raw_labels 라벨, unexplained 포함) — 라벨 없는 013 적재는 거부(설명 누락 = 미완료 판정 불가).
- dart_disclosure_raw: 공시검색 정기공시 항목 원문(정정 포함) — 원공시·첫 공시일·접수 여부 근거.
- dart_batch_log: 일별 호출 수·상한·020 중단 — 러너가 상한(18,000/일) 준수·재개에 사용.
"""
from __future__ import annotations

import json
from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb

_FIN_COLS = ("corp_code", "bsns_year", "reprt_code", "ticker", "status", "rcept_no", "rcept_dt", "orig_rcept_dt",
             "is_correction", "no_data_reason", "no_data_basis", "response", "batch_date")


def upsert_fin_raw(conn: Connection, rec: dict) -> None:
    if rec.get("status") == "013" and not rec.get("no_data_reason"):
        raise ValueError("status 013 셀은 no_data_reason(라벨) 필수 — unexplained 라도 명시")
    vals = [Jsonb(rec[c]) if c == "response" else rec.get(c) for c in _FIN_COLS]
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in _FIN_COLS[3:])
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO dart_fin_raw ({', '.join(_FIN_COLS)}, fetched_at) VALUES ({', '.join(['%s'] * len(_FIN_COLS))}, NOW()) "
            f"ON CONFLICT (corp_code, bsns_year, reprt_code) DO UPDATE SET {sets}, fetched_at = NOW()",
            vals,
        )


def _to_date(s: str | None) -> date | None:
    s = (s or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def upsert_disclosures(conn: Connection, corp_code: str, items: list[dict], *, batch_date: date) -> int:
    """list.json 항목 원문 저장(정정 포함). 반환 = 신규 행 수(멱등)."""
    n = 0
    with conn.cursor() as cur:
        for it in items:
            rd = _to_date(it.get("rcept_dt"))
            if not it.get("rcept_no") or rd is None:
                continue
            cur.execute(
                "INSERT INTO dart_disclosure_raw (corp_code, rcept_no, rcept_dt, report_nm, item, batch_date) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (corp_code, rcept_no) DO NOTHING",
                (corp_code, it["rcept_no"], rd, (it.get("report_nm") or "").strip(), Jsonb(it), batch_date),
            )
            n += cur.rowcount
    return n


def load_disclosures(conn: Connection, corp_code: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT rcept_no, rcept_dt, report_nm FROM dart_disclosure_raw WHERE corp_code = %s ORDER BY rcept_dt, rcept_no", (corp_code,))
        return [{"rcept_no": r, "rcept_dt": d, "report_nm": n} for r, d, n in cur.fetchall()]


def first_filing_dt(conn: Connection, corp_code: str) -> date | None:
    with conn.cursor() as cur:
        cur.execute("SELECT min(rcept_dt) FROM dart_disclosure_raw WHERE corp_code = %s", (corp_code,))
        row = cur.fetchone()
    return row[0] if row else None


def first_daily_bar(conn: Connection, ticker: str) -> date | None:
    """첫 일봉 = 라이브·격리 일봉의 MIN(date) — 정기공시 이력 없는 종목의 상장일 대체(회신 24 Q-I)."""
    with conn.cursor() as cur:
        cur.execute("SELECT LEAST((SELECT MIN(date) FROM daily_prices WHERE ticker = %s), "
                    "(SELECT MIN(date) FROM delisted_daily_prices WHERE ticker = %s))", (ticker, ticker))
        row = cur.fetchone()
    return row[0] if row else None


def done_cells(conn: Connection, corp_codes: list[str]) -> set[tuple[str, int, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT corp_code, bsns_year, reprt_code FROM dart_fin_raw WHERE corp_code = ANY(%s)", (corp_codes,))
        return {(c, int(y), r) for c, y, r in cur.fetchall()}


def calls_today(conn: Connection, d: date) -> tuple[int, bool]:
    with conn.cursor() as cur:
        cur.execute("SELECT calls, stopped_020 FROM dart_batch_log WHERE batch_date = %s", (d,))
        row = cur.fetchone()
    return (int(row[0]), bool(row[1])) if row else (0, False)


def add_calls(conn: Connection, d: date, n: int, *, cap: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO dart_batch_log (batch_date, calls, cap) VALUES (%s, %s, %s) "
            "ON CONFLICT (batch_date) DO UPDATE SET calls = dart_batch_log.calls + EXCLUDED.calls, cap = EXCLUDED.cap, updated_at = NOW()",
            (d, n, cap),
        )


def mark_stopped_020(conn: Connection, d: date, *, cap: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO dart_batch_log (batch_date, calls, cap, stopped_020, note) VALUES (%s, 0, %s, TRUE, 'status 020 — 당일 중단') "
            "ON CONFLICT (batch_date) DO UPDATE SET stopped_020 = TRUE, note = EXCLUDED.note, updated_at = NOW()",
            (d, cap),
        )


def remaining_today(conn: Connection, d: date, *, cap: int) -> int:
    calls, stopped = calls_today(conn, d)
    return 0 if stopped else max(0, cap - calls)
