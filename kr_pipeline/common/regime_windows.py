"""(#207 회신 21 Q-5c 2, PR-3) 판정 창의 봉 날짜 → volume_regime_flag 유도.

regime 은 날짜의 함수(data_regimes.regime_for_date/regime_for_week)라 저장 컬럼을 읽지 않는다(#220 2차 리뷰 load 유도 전례 —
컬럼 선적용/구 writer 오저장에 면역). regime 은 날짜에 단조이므로 창의 **양 끝 날짜**만으로 상태가 결정된다
(window_flag((rule(first), rule(last)))). DB 는 창당 MIN/MAX 집계 1문, price_source 는 판정당 1회, 전부 SAVEPOINT 1개 안.
비용 상한: as_of < 경계 → DB 0(전부 regular 확정) / 고정 길이 창은 as_of − 경계 > 창 상한(일 400·주 800 달력일)이면 DB 0
(전부 extended 확정; 그보다 긴 거래정지가 경계를 걸치는 경우만 희생 — 명시적 트레이드오프). 앵커 기준 창은 상한 없음(길이가 자람).
관측 전용 헬퍼 규약(store #39): 서버측 SQL 오류(psycopg.Error)는 본 INSERT(LLM 비용 지출분)를 막지 않는다 — SAVEPOINT 격리,
값은 **보수적으로 'mixed'**(NULL 은 '창이 깨끗함'으로 읽히므로 오류를 깨끗함으로 저장하지 않는다). 프로그래밍 오류(TypeError 등)는
그대로 전파해 첫 실행에서 드러낸다(리뷰 #222 3차).
주봉은 zero-bar(거래정지) 주를 제외해 find_anchor/C3/T2 가 쓰는 행 집합(_fetch_weekly_full)과 같은 창을 본다(술어 공유 NOT_ZERO_BAR_SQL).
창(spec §5·D7, 리뷰 #222 정정): 분류 = 일간 50봉 ∪ 주간 W+1 주(as_of 끝) ∪ 앵커 주~마지막 주봉(T2/P2) ∪ **앵커에서 끝나는 C3 W+1 주**
(앵커를 적격 판정한 분모) / 트리거 = 일간 50봉 / 진입 = 일간 50봉 + PP 탐색 (N-1)봉 / 보유 climax T2 = 앵커 주~평가 주
(러너가 gates.week_ends 로 DB 0) / 보유 decline = NULL(거래량 입력 없음). 진입은 할트 여유(DAILY_HALT_ALLOWANCE)까지 더 본다.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Iterable

import psycopg
from psycopg import Connection

from kr_pipeline.common.data_regimes import (
    FLAG_MIXED, VOLUME_REGIME_BOUNDARY, VOLUME_WINDOW_WEEKLY_WEEKS, _as_date, regime_for_date, regime_for_week, window_flag,
)
from kr_pipeline.common.price_source import NOT_ZERO_BAR_SQL, PriceSource, price_source
from kr_pipeline.common.thresholds import PP_RECENT_SESSIONS, VOLUME_AVG_WINDOW_DAYS

log = logging.getLogger("kr_pipeline.common.regime_windows")

DAILY_WINDOW_MAX_CAL_DAYS = 400    # 50 세션 ≈ 70 달력일; 경계 후 이만큼 지나면 고정 창 전체가 extended(거래정지 ≤ ~11개월 허용)
WEEKLY_WINDOW_MAX_CAL_DAYS = 800   # 51 주 ≈ 357 달력일 + 여유
# 진입 창의 할트 여유: PP 탐색은 volume IS NOT NULL 세션(payload_lite recent_daily_indicators)을 세지만 일간 창은 원시 행을 세므로
# 할트 k 행이 끼면 모델 창이 실제보다 짧아진다 → avg_volume_50d 가 허용하는 할트 수(min_periods=40 → 10, indicators/modes.py)만큼 더 본다(보수).
DAILY_HALT_ALLOWANCE = VOLUME_AVG_WINDOW_DAYS - 40


def _edges_flag(first, last, rule: Callable[[date], str]) -> str | None:
    """창 양 끝 날짜 → flag(단조성: 창 상태 = {rule(first), rule(last)}). 빈 창(None) = NULL."""
    if first is None or last is None:
        return None
    return window_flag((rule(first), rule(last)))


def _edges(conn: Connection, src: PriceSource, ticker: str, *, weekly: bool, end: date, n: int) -> tuple[date | None, date | None]:
    """end 이하 최근 n 봉의 (MIN, MAX) 날짜 — 집계 1문. 주봉은 zero-bar 주 제외."""
    table, col, extra = (src.weekly, "week_end_date", f" AND {NOT_ZERO_BAR_SQL}") if weekly else (src.daily, "date", "")
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT MIN(d), MAX(d) FROM (SELECT {col} AS d FROM {table} WHERE ticker = %s AND {col} <= %s{extra} "
            f"ORDER BY {col} DESC LIMIT %s) q",
            (ticker, end, n))
        return cur.fetchone()


def _within_cap(d: date, weekly: bool) -> bool:
    return (d - VOLUME_REGIME_BOUNDARY).days <= (WEEKLY_WINDOW_MAX_CAL_DAYS if weekly else DAILY_WINDOW_MAX_CAL_DAYS)


def _guarded(conn: Connection, ticker: str, as_of: date, body: Callable[[PriceSource], str | None]) -> str | None:
    """SAVEPOINT 안에서 price_source 1회 + body. 서버측 SQL 오류 → 경고 + 보수 'mixed'; 그 외 예외는 전파.
    연결이 이미 INERROR 면 SAVEPOINT 자체가 거부되고 psycopg 의 트랜잭션 카운터가 새어(__enter__ 예외) 이후 rollback() 이 깨지므로
    (리뷰 #222 4차 실측) 들어가지 않고 보수값을 돌려준다 — 본 INSERT 는 어차피 실패하고 호출자의 rollback 이 정상 동작한다."""
    if conn.info.transaction_status == psycopg.pq.TransactionStatus.INERROR:
        log.warning("regime_window_flag_failed: %s %s — 연결이 INERROR(선행 문 실패) (flag=%s 보수)", ticker, as_of, FLAG_MIXED)
        return FLAG_MIXED
    try:
        with conn.transaction():
            return body(price_source(conn, ticker))
    except psycopg.Error as e:
        log.warning("regime_window_flag_failed: %s %s — %s (flag=%s 보수)", ticker, as_of, e, FLAG_MIXED)
        return FLAG_MIXED


def daily_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_AVG_WINDOW_DAYS) -> str | None:
    """as_of 이하 최근 n 일봉(신규 상장 등 n 미만이면 있는 만큼)."""
    d = _as_date(as_of)
    if d is None or d < VOLUME_REGIME_BOUNDARY or not _within_cap(d, weekly=False):
        return None
    return _guarded(conn, ticker, d, lambda src: _edges_flag(*_edges(conn, src, ticker, weekly=False, end=d, n=n), regime_for_date))


def weekly_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_WINDOW_WEEKLY_WEEKS) -> str | None:
    """as_of 이하 최근 n 주봉(zero-bar 주 제외; 주봉 regime = regime_for_week)."""
    d = _as_date(as_of)
    if d is None or d < VOLUME_REGIME_BOUNDARY or not _within_cap(d, weekly=True):
        return None
    return _guarded(conn, ticker, d, lambda src: _edges_flag(*_edges(conn, src, ticker, weekly=True, end=d, n=n), regime_for_week))


def range_flag_from_week_ends(week_ends: Iterable, anchor_week) -> str | None:
    """앵커 주 ~ 마지막 주(순수, DB 0): 보유 climax T2 창. 입력 = 산술이 실제로 쓴 주(week_end ISO/date), 앵커 없음 → NULL."""
    a = _as_date(anchor_week)
    if a is None:
        return None
    return window_flag(regime_for_week(d) for d in (_as_date(w) for w in week_ends) if d is not None and d >= a)


def classification_flag(conn: Connection, ticker: str, as_of, *, anchor_week=None) -> str | None:
    """분류 = 일간 50봉 ∪ 주간 W+1 주 ∪ 앵커 주~마지막 주봉 ∪ 앵커에서 끝나는 C3 W+1 주 — 하나라도 mixed → mixed(spec §5, 리뷰 #222).
    앵커~마지막 주봉의 우측 끝 = 주간 집계의 MAX(week_end_date)(find_anchor/T2 가 실제로 본 마지막 주; as_of 달력 주가 아님 — 4차).
    앵커 기준 두 창은 상한 없음: C3 창은 앵커 < 경계면 전부 regular(DB 0). 첫 mixed 에서 즉시 반환. 범위 밖: LLM 이 보는 원시 봉
    (일 60·주 104)은 결정론 창이 아니므로 모델링하지 않는다(spec §9)."""
    d = _as_date(as_of)
    if d is None or d < VOLUME_REGIME_BOUNDARY:
        return None
    try:
        a = _as_date(anchor_week)
    except (TypeError, ValueError) as e:            # echo 가 비정상이어도 본 INSERT 를 막지 않는다(관측 전용)
        log.warning("regime_window_flag: %s %s anchor_week 비정상 %r — %s (앵커 창 생략)", ticker, d, anchor_week, e)
        a = None
    want_daily, want_weekly = _within_cap(d, weekly=False), _within_cap(d, weekly=True)
    want_c3 = a is not None and a >= VOLUME_REGIME_BOUNDARY and _within_cap(a, weekly=True)
    if not want_weekly and a is not None and _edges_flag(a, d, regime_for_week) == FLAG_MIXED:
        return FLAG_MIXED                                # 주간 창이 상한 밖(모든 주봉 extended) + 경계 전 앵커 → 순수 유도, DB 0
    if not (want_daily or want_weekly or want_c3):
        return None

    def body(src: PriceSource) -> str | None:
        if want_daily and _edges_flag(*_edges(conn, src, ticker, weekly=False, end=d, n=VOLUME_AVG_WINDOW_DAYS), regime_for_date) == FLAG_MIXED:
            return FLAG_MIXED
        if want_weekly:
            w_first, w_last = _edges(conn, src, ticker, weekly=True, end=d, n=VOLUME_WINDOW_WEEKLY_WEEKS)
            if _edges_flag(w_first, w_last, regime_for_week) == FLAG_MIXED:
                return FLAG_MIXED
            if a is not None and _edges_flag(a, w_last, regime_for_week) == FLAG_MIXED:     # 앵커 ~ 마지막 주봉
                return FLAG_MIXED
        if want_c3 and _edges_flag(*_edges(conn, src, ticker, weekly=True, end=a, n=VOLUME_WINDOW_WEEKLY_WEEKS), regime_for_week) == FLAG_MIXED:
            return FLAG_MIXED
        return None

    return _guarded(conn, ticker, d, body)


def entry_window_flag(conn: Connection, ticker: str, as_of) -> str | None:
    """진입 = 일간 50봉 + PP 탐색 여유(PP_RECENT_SESSIONS-1) + 할트 여유(DAILY_HALT_ALLOWANCE) — pocket_pivot 분기 창이 as_of 보다
    최대 N-1 세션(할트 제외 계수) 앞서 끝나므로 원시 행 기준 합집합(보수)."""
    return daily_window_flag(conn, ticker, as_of, n=VOLUME_AVG_WINDOW_DAYS + PP_RECENT_SESSIONS - 1 + DAILY_HALT_ALLOWANCE)
