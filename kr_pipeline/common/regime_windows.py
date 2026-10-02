"""(#207 회신 21 Q-5c 2, PR-3) 판정 창의 봉 날짜 → volume_regime_flag 유도.

regime 은 날짜의 함수(data_regimes.regime_for_date/regime_for_week)라 저장 컬럼을 읽지 않는다(#220 2차 리뷰 load 유도 전례 —
컬럼 선적용/구 writer 오저장에 면역). writer 가 conn·symbol·as_of 만 가지므로 창 봉 **날짜**를 읽어 유도 — spec §5 "추가 SQL 0 목표"는
프레임이 writer 까지 오지 않아 불가, 이것으로 대체. 비용: 경계 전 as_of 는 DB 0(전부 regular 확정), 경계 후는 price_source 1회 +
창당 SELECT 1회(분류 2·트리거/진입/보유 1).
관측 전용 헬퍼 규약(store #39): 어떤 실패도 본 INSERT(LLM 비용 지출분)를 막지 않는다 — SAVEPOINT(conn.transaction) 격리 후 None.
창(spec §5·D7, 리뷰 #222 정정): 분류 = 주간 C3 W+1 주 ∪ 일간 50봉 / 트리거 = 일간 50봉 / 진입 = 일간 50봉 + PP 탐색 4봉 /
보유 climax T2 = 앵커 주 ~ 평가 주 / 보유 decline = 거래량 입력 없음(T-A·TA-d 가격 낙폭) → NULL.
"""
from __future__ import annotations

import logging
from datetime import date

from psycopg import Connection

from kr_pipeline.common.data_regimes import (
    FLAG_MIXED, VOLUME_REGIME_BOUNDARY, VOLUME_WINDOW_DAILY_BARS, VOLUME_WINDOW_WEEKLY_WEEKS, _as_date, regime_for_date,
    regime_for_week, window_flag,
)
from kr_pipeline.common.price_source import PriceSource, price_source

log = logging.getLogger("kr_pipeline.common.regime_windows")

# entry_params_calc.py:119 `rdi[-5:]` — pocket_pivot 분기의 관측 비율은 최근 5세션 중 최신 PP 일에서 끝나는 50봉 창을 쓴다.
# as_of 창에 최대 4봉을 더 보아 그 어느 창이든 경계에 걸치면 mixed(보수 방향).
ENTRY_PP_LOOKBACK_SESSIONS = 5


def _flag(conn: Connection, ticker: str, as_of: date, *, weekly: bool, where: str, params: tuple, src: PriceSource | None = None) -> str | None:
    """as_of ≥ 경계일 때만 DB 를 읽는다. 실패는 경고 + None(트랜잭션 오염은 SAVEPOINT 가 격리)."""
    if as_of < VOLUME_REGIME_BOUNDARY:
        return None
    try:
        with conn.transaction():
            src = src or price_source(conn, ticker)
            table, col, rule = (src.weekly, "week_end_date", regime_for_week) if weekly else (src.daily, "date", regime_for_date)
            with conn.cursor() as cur:
                cur.execute(f"SELECT {col} FROM {table} WHERE ticker = %s AND {where}", (ticker, *params))
                return window_flag(rule(r[0]) for r in cur.fetchall())
    except Exception as e:  # noqa: BLE001 — 관측 전용
        log.warning("regime_window_flag_failed: %s %s weekly=%s — %s (flag=NULL)", ticker, as_of, weekly, e)
        return None


def daily_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_WINDOW_DAILY_BARS, *, src: PriceSource | None = None) -> str | None:
    """as_of 이하 최근 n 일봉의 날짜로 창 상태 유도. 봉이 n 개 미만(신규 상장)이면 있는 만큼."""
    d = _as_date(as_of)
    if d is None:
        return None
    return _flag(conn, ticker, d, weekly=False, where="date <= %s ORDER BY date DESC LIMIT %s", params=(d, n), src=src)


def weekly_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_WINDOW_WEEKLY_WEEKS, *, src: PriceSource | None = None) -> str | None:
    """as_of 이하 최근 n 주봉(week_end_date)으로 창 상태 유도(주봉 regime = regime_for_week, mixed 주 포함 시 mixed)."""
    d = _as_date(as_of)
    if d is None:
        return None
    return _flag(conn, ticker, d, weekly=True, where="week_end_date <= %s ORDER BY week_end_date DESC LIMIT %s", params=(d, n), src=src)


def weekly_range_flag(conn: Connection, ticker: str, start_week_end, as_of) -> str | None:
    """보유 climax T2 창 = 앵커 주 ~ 평가 주(spec D7). 앵커 없음(None) = 창 없음 → NULL."""
    s, d = _as_date(start_week_end), _as_date(as_of)
    if s is None or d is None:
        return None
    return _flag(conn, ticker, d, weekly=True, where="week_end_date BETWEEN %s AND %s ORDER BY week_end_date", params=(s, d))


def classification_flag(conn: Connection, ticker: str, as_of) -> str | None:
    """분류 = 주간 C3(W+1 주) ∪ 일간 50봉 — 둘 중 하나라도 mixed → mixed(spec §5). price_source 는 1회."""
    d = _as_date(as_of)
    if d is None or d < VOLUME_REGIME_BOUNDARY:
        return None
    try:
        src = price_source(conn, ticker)
    except Exception as e:  # noqa: BLE001
        log.warning("regime_window_flag_failed: %s %s price_source — %s (flag=NULL)", ticker, d, e)
        return None
    flags = (daily_window_flag(conn, ticker, d, src=src), weekly_window_flag(conn, ticker, d, src=src))
    return FLAG_MIXED if FLAG_MIXED in flags else None


def entry_window_flag(conn: Connection, ticker: str, as_of) -> str | None:
    """진입 = 일간 50봉 + PP 탐색 여유(ENTRY_PP_LOOKBACK_SESSIONS-1) — PP 분기 창이 as_of 보다 최대 4봉 앞서 끝나므로 합집합(보수)."""
    return daily_window_flag(conn, ticker, as_of, n=VOLUME_WINDOW_DAILY_BARS + ENTRY_PP_LOOKBACK_SESSIONS - 1)
