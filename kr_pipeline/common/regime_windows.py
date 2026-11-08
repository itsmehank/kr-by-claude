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
창(spec §5·D7, 리뷰 #222 정정 → **#184 ver 2(2026-11) 갱신**): 분류 = 일간 50봉(as_of 끝) ∪ 앵커 주~마지막 주봉(T2/P2) ∪ **앵커 C3′ 일간 창**
(앵커 주 첫 거래일에서 끝나는 50봉의 첫 날 ~ 앵커 주 — 앵커를 적격 판정한 avg_volume_50d 분모의 합집합) / 트리거 = 일간 50봉 /
진입 = 일간 50봉 + PP 탐색 (N-1)봉 / 보유 climax·decline = 앵커 C3′ 창 시작 ~ 평가 주(러너가 gates.week_ends·daily_dates 로 DB 0,
회신 22 Q-A·23 Q-D). 구 주간 51주 창(W+1)·앵커 끝 51주 창은 삭제(소비 규칙이 C3 뿐이었음 — 회신 11-08 Q-4-2); 저장 행의
volume_regime_flag_ver 가 1(구 창)/2(이 창)을 구분한다. 진입은 할트 여유(DAILY_HALT_ALLOWANCE)까지 더 본다.
원칙(회신 22): 표지 창 = 판정이 직접·간접 의존하는 모든 계산 창의 합집합.
"""
from __future__ import annotations

import logging
from bisect import bisect_left
from datetime import date, timedelta
from typing import Callable, Iterable

import psycopg
from psycopg import Connection

from kr_pipeline.common.data_regimes import (
    FLAG_MIXED, VOLUME_REGIME_BOUNDARY, _as_date, regime_for_date, regime_for_week, window_flag,
)
from kr_pipeline.common.price_source import NOT_ZERO_BAR_SQL, PriceSource, price_source
from kr_pipeline.common.thresholds import PP_RECENT_SESSIONS, VOLUME_AVG_WINDOW_DAYS

log = logging.getLogger("kr_pipeline.common.regime_windows")

DAILY_WINDOW_MAX_CAL_DAYS = 400    # 50 세션 ≈ 70 달력일; 경계 후 이만큼 지나면 고정 창 전체가 extended(거래정지 ≤ ~11개월 허용)
WEEKLY_WINDOW_MAX_CAL_DAYS = 800   # (#184 ver 2) 앵커~마지막 주봉 창의 DB-0 단축 상한: as_of 가 경계 + 이만큼 지나면 마지막 주봉은 경계 후로 간주
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


def _anchor_week_first_day(conn: Connection, src: PriceSource, ticker: str, anchor: date) -> date | None:
    """앵커 ISO 주(달력 월요일 ~ anchor_week)의 첫 거래일(일봉 MIN(date)). 없으면 None."""
    monday = anchor - timedelta(days=anchor.weekday())
    with conn.cursor() as cur:
        cur.execute(f"SELECT MIN(date) FROM {src.daily} WHERE ticker = %s AND date BETWEEN %s AND %s", (ticker, monday, anchor))
        return cur.fetchone()[0]


def held_window_flag(week_ends: Iterable, anchor_week, daily_dates: Iterable) -> str | None:
    """보유 climax·decline 창(순수, DB 0) = 앵커 C3′ 일간 창 시작 ~ 마지막 주 — 회신 22 Q-A·23 Q-D 원칙("표지 창 = 판정이 직접·간접
    의존하는 모든 계산 창의 합집합")을 #184 ver 2 창에 적용. find_anchor 는 앵커 주 안 일봉의 avg_volume_50d(앵커 주 첫 거래일 끝
    50봉이 가장 이른 분모)로 앵커를 고르고, T2·T-A/TA-d 는 그 앵커를 시작점으로 쓴다 → climax·decline 같은 창.
    입력 = gates.week_ends(산술이 쓴 주, zero-bar 제외, 오름차순) + gates.daily_dates(C3′ 가 본 지표 행 날짜, 오름차순).
    창 시작 = daily_dates 중 앵커 ISO 주 첫 날짜 인덱스 j → daily_dates[max(0, j − 49)](regime_for_date); 앵커 주 일봉이 없으면(방어)
    앵커 주 자체(regime_for_week). 앵커 없음(no_transition·left_censored) → NULL(판정 신호 자체가 None)."""
    a = _as_date(anchor_week)
    if a is None:
        return None
    weeks = [d for d in (_as_date(w) for w in week_ends) if d is not None]
    if not weeks:
        return None
    days = [d for d in (_as_date(x) for x in daily_dates) if d is not None]
    iso = a.isocalendar()[:2]
    j = next((k for k, d in enumerate(days) if d.isocalendar()[:2] == iso), None)
    start_regime = (regime_for_week(a) if j is None
                    else regime_for_date(days[max(0, j - (VOLUME_AVG_WINDOW_DAYS - 1))]))
    i = bisect_left(weeks, a)
    return window_flag([start_regime, *(regime_for_week(d) for d in weeks[i:])])


def classification_flag(conn: Connection, ticker: str, as_of, *, anchor_week=None) -> str | None:
    """분류(#184 ver 2) = 일간 50봉(as_of 끝) ∪ 앵커 주~마지막 주봉 ∪ 앵커 C3′ 일간 창 — 하나라도 mixed → mixed(spec §5, 리뷰 #222).
    앵커~마지막 주봉의 우측 끝 = 주간 집계의 MAX(week_end_date)(find_anchor/T2 가 실제로 본 마지막 주; as_of 달력 주가 아님 — 4차).
    DB-0 분기(regime 단조성): 앵커 ≥ 경계면 앵커~마지막 주 창은 전부 extended(생략); 앵커 < 경계면 C3′ 창은 전부 regular(생략);
    앵커 < 경계 ∧ as_of 가 주간 상한 밖이면 마지막 주봉은 경계 후 → 순수 유도 mixed. 첫 mixed 에서 즉시 반환. 범위 밖: LLM 이 보는
    원시 봉(일 60·주 104)은 결정론 창이 아니므로 모델링하지 않는다(spec §9)."""
    d = _as_date(as_of)
    if d is None or d < VOLUME_REGIME_BOUNDARY:
        return None
    try:
        a = _as_date(anchor_week)
    except (TypeError, ValueError) as e:            # echo 가 비정상이어도 본 INSERT 를 막지 않는다(관측 전용)
        log.warning("regime_window_flag: %s %s anchor_week 비정상 %r — %s (앵커 창 생략)", ticker, d, anchor_week, e)
        a = None
    want_daily = _within_cap(d, weekly=False)
    want_range = a is not None and a < VOLUME_REGIME_BOUNDARY                       # 앵커~마지막 주봉
    want_c3 = a is not None and a >= VOLUME_REGIME_BOUNDARY and _within_cap(a, weekly=False)   # 앵커 C3′ 일간 창
    if want_range and not _within_cap(d, weekly=True):
        return FLAG_MIXED                                # 경계 전 앵커 + 마지막 주봉은 경계 후일 수밖에 없음 → 순수 유도, DB 0
    if not (want_daily or want_range or want_c3):
        return None

    def body(src: PriceSource) -> str | None:
        if want_daily and _edges_flag(*_edges(conn, src, ticker, weekly=False, end=d, n=VOLUME_AVG_WINDOW_DAYS), regime_for_date) == FLAG_MIXED:
            return FLAG_MIXED
        if want_range:
            _, w_last = _edges(conn, src, ticker, weekly=True, end=d, n=1)
            if _edges_flag(a, w_last, regime_for_week) == FLAG_MIXED:                 # 앵커 ~ 마지막 주봉
                return FLAG_MIXED
        if want_c3:
            first_day = _anchor_week_first_day(conn, src, ticker, a)
            if first_day is not None:
                s, _ = _edges(conn, src, ticker, weekly=False, end=first_day, n=VOLUME_AVG_WINDOW_DAYS)
                if _edges_flag(s, a, regime_for_date) == FLAG_MIXED:
                    return FLAG_MIXED
        return None

    return _guarded(conn, ticker, d, body)


def entry_window_flag(conn: Connection, ticker: str, as_of) -> str | None:
    """진입 = 일간 50봉 + PP 탐색 여유(PP_RECENT_SESSIONS-1) + 할트 여유(DAILY_HALT_ALLOWANCE) — pocket_pivot 분기 창이 as_of 보다
    최대 N-1 세션(할트 제외 계수) 앞서 끝나므로 원시 행 기준 합집합(보수)."""
    return daily_window_flag(conn, ticker, as_of, n=VOLUME_AVG_WINDOW_DAYS + PP_RECENT_SESSIONS - 1 + DAILY_HALT_ALLOWANCE)
