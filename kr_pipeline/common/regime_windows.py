"""(#207 회신 21 Q-5c 2, PR-3) 판정 창의 봉 날짜 → volume_regime_flag 유도.

regime 은 날짜의 함수(data_regimes.regime_for_date/regime_for_week)라 저장 컬럼을 읽지 않는다(#220 2차 리뷰 load 유도 전례 —
컬럼 선적용/구 writer 오저장에 면역). regime 은 날짜에 단조이므로 창의 **양 끝 날짜**만으로 상태가 결정된다:
mixed ⇔ 첫 봉 regime ≠ extended ∧ 끝 봉 regime ≠ regular. 따라서 DB 는 MIN/MAX 집계 1문(판정당 round-trip 1~2).
비용 상한: as_of < 경계 → DB 0(전부 regular 확정) / as_of − 경계 > 창 상한(일 400·주 800 달력일) → DB 0(전부 extended 확정;
그보다 긴 거래정지가 경계를 걸치는 경우만 희생 — 명시적 트레이드오프).
관측 전용 헬퍼 규약(store #39): 어떤 실패도 본 INSERT(LLM 비용 지출분)를 막지 않는다 — SAVEPOINT(conn.transaction) 격리.
실패 시 값은 **보수적으로 'mixed'**(경계 후 창) — NULL 은 '창이 깨끗함'으로 읽히므로 오류를 깨끗함으로 저장하면 안 된다(리뷰 #222).
주봉은 zero-bar(거래정지) 주를 제외해 find_anchor/C3/T2 가 쓰는 행 집합(_fetch_weekly_full)과 같은 창을 본다.
창(spec §5·D7, 리뷰 #222 정정): 분류 = 주간 C3 W+1 주 ∪ 일간 50봉 ∪ 앵커 주~평가 주(T2/P2 는 앵커 기준) / 트리거 = 일간 50봉 /
진입 = 일간 50봉 + PP 탐색 (N-1)봉 / 보유 climax T2 = 앵커 주~평가 주(러너가 gates.week_ends 로 DB 없이) / 보유 decline = NULL.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Iterable

from psycopg import Connection

from kr_pipeline.common.data_regimes import (
    FLAG_MIXED, REGIME_EXTENDED, REGIME_REGULAR, VOLUME_REGIME_BOUNDARY, VOLUME_WINDOW_DAILY_BARS,
    VOLUME_WINDOW_WEEKLY_WEEKS, _as_date, regime_for_date, regime_for_week, window_flag,
)
from kr_pipeline.common.price_source import price_source
from kr_pipeline.llm_runner.compute.entry_params_calc import PP_RECENT_SESSIONS

log = logging.getLogger("kr_pipeline.common.regime_windows")

DAILY_WINDOW_MAX_CAL_DAYS = 400    # 50 세션 ≈ 70 달력일; 경계 후 이만큼 지나면 창 전체가 extended(거래정지 ≤ ~11개월 허용)
WEEKLY_WINDOW_MAX_CAL_DAYS = 800   # 51 주 ≈ 357 달력일 + 여유
_ZERO_BAR = "NOT (open = 0 AND high = 0 AND low = 0 AND volume = 0)"   # _fetch_weekly_full 과 동일 술어(api/services/payload_builder.py)


def _edges_flag(first, last, rule) -> str | None:
    """창 양 끝 날짜 → flag. 빈 창(None) = NULL."""
    if first is None or last is None:
        return None
    return FLAG_MIXED if (rule(first) != REGIME_EXTENDED and rule(last) != REGIME_REGULAR) else None


def _window_flag(conn: Connection, ticker: str, as_of: date, *, weekly: bool, n: int) -> str | None:
    """as_of 이하 최근 n 봉의 MIN/MAX 날짜로 유도(집계 1문, SAVEPOINT 격리). 실패 → 'mixed'(보수) + 경고."""
    if as_of < VOLUME_REGIME_BOUNDARY:
        return None
    if (as_of - VOLUME_REGIME_BOUNDARY).days > (WEEKLY_WINDOW_MAX_CAL_DAYS if weekly else DAILY_WINDOW_MAX_CAL_DAYS):
        return None
    try:
        with conn.transaction():
            src = price_source(conn, ticker)
            if weekly:
                table, col, extra, rule = src.weekly, "week_end_date", f" AND {_ZERO_BAR}", regime_for_week
            else:
                table, col, extra, rule = src.daily, "date", "", regime_for_date
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT MIN(d), MAX(d) FROM (SELECT {col} AS d FROM {table} WHERE ticker = %s AND {col} <= %s{extra} "
                    f"ORDER BY {col} DESC LIMIT %s) q",
                    (ticker, as_of, n))
                first, last = cur.fetchone()
            return _edges_flag(first, last, rule)
    except Exception as e:  # noqa: BLE001 — 관측 전용. 오류를 '깨끗함(NULL)' 으로 저장하지 않는다
        log.warning("regime_window_flag_failed: %s %s weekly=%s — %s (flag=%s 보수)", ticker, as_of, weekly, e, FLAG_MIXED)
        return FLAG_MIXED


def daily_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_WINDOW_DAILY_BARS) -> str | None:
    """as_of 이하 최근 n 일봉(신규 상장 등 n 미만이면 있는 만큼)."""
    d = _as_date(as_of)
    return None if d is None else _window_flag(conn, ticker, d, weekly=False, n=n)


def weekly_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_WINDOW_WEEKLY_WEEKS) -> str | None:
    """as_of 이하 최근 n 주봉(zero-bar 주 제외; 주봉 regime = regime_for_week)."""
    d = _as_date(as_of)
    return None if d is None else _window_flag(conn, ticker, d, weekly=True, n=n)


def range_flag_from_week_ends(week_ends: Iterable, anchor_week) -> str | None:
    """앵커 주 ~ 마지막 주(순수, DB 0): 보유 climax T2·분류 T2/P2 창. 입력 = 산술이 실제로 쓴 주(week_end ISO/date), 앵커 없음 → NULL."""
    a = _as_date(anchor_week)
    if a is None:
        return None
    return window_flag(regime_for_week(d) for d in (_as_date(w) for w in week_ends) if d is not None and d >= a)


def classification_flag(conn: Connection, ticker: str, as_of, *, anchor_week=None) -> str | None:
    """분류 = 주간 C3(W+1 주) ∪ 일간 50봉 ∪ 앵커 주~평가 주(T2/P2 는 앵커 기준 — 리뷰 #222) — 하나라도 mixed → mixed(spec §5)."""
    d = _as_date(as_of)
    if d is None or d < VOLUME_REGIME_BOUNDARY:
        return None
    flags = [daily_window_flag(conn, ticker, d), weekly_window_flag(conn, ticker, d)]
    a = _as_date(anchor_week)
    if a is not None and regime_for_week(a) != REGIME_EXTENDED:          # 앵커가 경계 이후면 구간 전체 extended → 조회 불요
        flags.append(_window_flag(conn, ticker, d, weekly=True, n=max(1, (d - a).days // 7 + 2)))
    return FLAG_MIXED if FLAG_MIXED in flags else None


def entry_window_flag(conn: Connection, ticker: str, as_of) -> str | None:
    """진입 = 일간 50봉 + PP 탐색 여유(PP_RECENT_SESSIONS-1) — pocket_pivot 분기 창이 as_of 보다 최대 N-1 봉 앞서 끝나므로 합집합(보수)."""
    return daily_window_flag(conn, ticker, as_of, n=VOLUME_WINDOW_DAILY_BARS + PP_RECENT_SESSIONS - 1)
