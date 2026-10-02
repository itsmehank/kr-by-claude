"""(#207 회신 21 Q-5c 2, PR-3) 판정 창의 봉 날짜 → volume_regime_flag 유도.

regime 은 날짜의 함수(data_regimes.regime_for_date/regime_for_week)라 저장 컬럼을 읽지 않는다(#220 2차 리뷰 load 유도 전례 —
컬럼 선적용/구 writer 오저장에 면역). writer 가 conn·symbol·as_of 만 가지므로 판정당 1쿼리(LIMIT n) — spec §5 "추가 SQL 0 목표"는
프레임이 writer 까지 오지 않아 불가, 이것으로 대체(plan 2026-10-02-volume-regime-pr3 Architecture).
창(spec §5): 분류 = 주간 C3 50주 ∪ 일간 50봉 / 트리거·진입 = 일간 50봉 / 보유 T2·T-D = 앵커 주 ~ 평가 주.
"""
from __future__ import annotations

from datetime import date, datetime

from psycopg import Connection

from kr_pipeline.common.data_regimes import (
    VOLUME_WINDOW_DAILY_BARS, VOLUME_WINDOW_WEEKLY_WEEKS, regime_for_date, regime_for_week, window_flag,
)
from kr_pipeline.common.price_source import price_source


def _d(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def daily_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_WINDOW_DAILY_BARS) -> str | None:
    """as_of 이하 최근 n 일봉의 날짜로 창 상태 유도. 봉이 n 개 미만(신규 상장)이면 있는 만큼."""
    d = _d(as_of)
    if d is None:
        return None
    src = price_source(conn, ticker)
    with conn.cursor() as cur:
        cur.execute(f"SELECT date FROM {src.daily} WHERE ticker = %s AND date <= %s ORDER BY date DESC LIMIT %s", (ticker, d, n))
        return window_flag(regime_for_date(r[0]) for r in cur.fetchall())


def weekly_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_WINDOW_WEEKLY_WEEKS) -> str | None:
    """as_of 이하 최근 n 주봉(week_end_date)으로 창 상태 유도(주봉 regime = regime_for_week, mixed 주 포함 시 mixed)."""
    d = _d(as_of)
    if d is None:
        return None
    src = price_source(conn, ticker)
    with conn.cursor() as cur:
        cur.execute(f"SELECT week_end_date FROM {src.weekly} WHERE ticker = %s AND week_end_date <= %s ORDER BY week_end_date DESC LIMIT %s",
                    (ticker, d, n))
        return window_flag(regime_for_week(r[0]) for r in cur.fetchall())


def weekly_range_flag(conn: Connection, ticker: str, start_week_end, as_of) -> str | None:
    """보유 평가(T2·T-D) 창 = 앵커 주 ~ 평가 주(spec D7). 앵커 없음(None) = 창 없음 → NULL."""
    s, d = _d(start_week_end), _d(as_of)
    if s is None or d is None:
        return None
    src = price_source(conn, ticker)
    with conn.cursor() as cur:
        cur.execute(f"SELECT week_end_date FROM {src.weekly} WHERE ticker = %s AND week_end_date BETWEEN %s AND %s ORDER BY week_end_date",
                    (ticker, s, d))
        return window_flag(regime_for_week(r[0]) for r in cur.fetchall())


def judgment_flag(conn: Connection, ticker: str, as_of, *, daily: bool = True, weekly: bool = False) -> str | None:
    """분류 = 주간 C3 50주 ∪ 일간 50봉(둘 중 하나라도 mixed → mixed, spec §5). 트리거·진입 = 일간만."""
    flags = []
    if daily:
        flags.append(daily_window_flag(conn, ticker, as_of))
    if weekly:
        flags.append(weekly_window_flag(conn, ticker, as_of))
    return "mixed" if "mixed" in flags else None
