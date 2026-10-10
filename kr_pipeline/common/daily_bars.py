"""daily_prices 최신 일봉 날짜 — 공용 조회(#204 리뷰 1차: 같은 SQL 이 5곳에 흩어져 있어 정의 변경 시 누락 위험).

기존 호출처(weekly/modes.py·trade_management/runner.py·indicators/completeness.py·ohlcv/modes.py)는 `SELECT MAX(date) FROM daily_prices`
직접 실행 — 이 PR 범위(#204)에서는 universe 만 이 헬퍼로 옮기고 나머지는 별건(동작 동일, 기계적 교체).
"""
from __future__ import annotations

from datetime import date


def latest_daily_bar_date(conn, *, upto: date | None = None) -> date | None:
    """DB 에 있는 가장 최근 일봉 날짜. upto 가 있으면 그 날짜 이하 중 최신. 일봉이 없으면 None."""
    with conn.cursor() as cur:
        if upto is None:
            cur.execute("SELECT MAX(date) FROM daily_prices")
        else:
            cur.execute("SELECT MAX(date) FROM daily_prices WHERE date <= %s", (upto,))
        row = cur.fetchone()
    return row[0] if row and row[0] else None
