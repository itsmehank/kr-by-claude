"""#186 as-of 규약 (2026-09-27 전문가 회신 (a)(b)):
(a) 유효 시점 = 접수일의 **다음 거래일**(종가부터) — 접수 시각이 없어 장후 접수 look-ahead 를 막는다.
(b) as-of 입력 = 응답에 실제 담긴 rcept_no 의 접수일(보고 기간 말·원공시일 금지).
[Q-3] A 채택(09-27, design-judgment / governance 4 look-ahead 0·null=보수): 정정본만 반환되는 셀(저장본 실측 629/7,233,
    최대 2,421일 지연)도 **정정 접수일** 기준. 원공시 접수일(orig_rcept_dt)은 저장만 하고 유효 시점 계산 입력으로 **사용 금지**
    (용도 = 정정 기인 NULL 비율 측정·파리티 사유 귀속). 원공시일~정정일 구간은 NULL(보수). 알려진 한계 = #186 본문.
달력 = index_daily(KOSPI 1001, 휴일 미적재 = 거래일 집합).
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection


def rcept_dt_of(rcept_no: str | None) -> date | None:
    if not rcept_no or len(rcept_no) < 8 or not rcept_no[:8].isdigit():
        return None
    try:
        return date(int(rcept_no[:4]), int(rcept_no[4:6]), int(rcept_no[6:8]))
    except ValueError:
        return None


def effective_from(conn: Connection, rcept_dt: date) -> date | None:
    """접수일 이후 첫 거래일(접수일 당일 제외). 달력에 이후 거래일이 없으면 None(미확정 — 소비자는 결측 취급)."""
    with conn.cursor() as cur:
        cur.execute("SELECT min(date) FROM index_daily WHERE date > %s", (rcept_dt,))
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def effective_from_cell(conn: Connection, cell: dict) -> date | None:
    """dart_fin_raw 셀 → 유효 시점. 입력은 cell["rcept_dt"](응답 rcept_no 접수일)만 — orig_rcept_dt 는 읽지 않는다([Q-3] A)."""
    rd = cell.get("rcept_dt")
    return effective_from(conn, rd) if rd else None
