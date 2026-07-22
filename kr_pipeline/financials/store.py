"""(#68 2단계) dart_financials 저장 + as-of 조회 chokepoint (스펙 §5).

look-ahead 방지 규약: 소비자는 반드시 get_financials_asof 만 사용 —
disclosed_at(원공시 접수일) 기준, NULL 행 제외(보수).
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection

_COLS = ("ticker", "bsns_year", "reprt_code", "status", "fs_div",
         "fiscal_start", "fiscal_end", "revenue", "operating_income",
         "net_income", "shares_outstanding", "eps_derived", "rcept_no",
         "disclosed_at")


def upsert_financial(conn: Connection, rec: dict) -> None:
    """(ticker, bsns_year, reprt_code) upsert — 멱등 재개·재적재 갱신."""
    vals = [rec.get(c) for c in _COLS]
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLS[3:])
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO dart_financials ({', '.join(_COLS)}, fetched_at)
            VALUES ({', '.join(['%s'] * len(_COLS))}, NOW())
            ON CONFLICT (ticker, bsns_year, reprt_code)
            DO UPDATE SET {sets}, fetched_at = NOW()
            """,
            vals,
        )


def get_financials_asof(conn: Connection, ticker: str, *, as_of: date,
                        limit: int = 12) -> list[dict]:
    """as_of 시점에 **공시돼 있던** 실적만 — fiscal_end 최신 순.

    - disclosed_at IS NULL(원공시 매칭 실패)은 제외: look-ahead 0 보장이
      커버리지보다 우선(스펙 §4·§5).
    - 경계 규약 = **strict < (T+1 가용)**: 공시는 통상 장마감 후 접수되므로
      공시 당일 as_of 에는 미노출(리뷰 Important-4 결정 — 보수 방향).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticker, bsns_year, reprt_code, status, fs_div,
                   fiscal_start, fiscal_end, revenue, operating_income,
                   net_income, shares_outstanding, eps_derived, disclosed_at
              FROM dart_financials
             WHERE ticker = %s AND status = 'ok'
               AND disclosed_at IS NOT NULL AND disclosed_at < %s
             ORDER BY fiscal_end DESC NULLS LAST, reprt_code
             LIMIT %s
            """,
            (ticker, as_of, limit),
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
