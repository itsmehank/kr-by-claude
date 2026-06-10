"""거래 캘린더 — 라이브 KRX 지수로 '기대 최신 거래일(ELTD)' 산출 + 신선도 단정.

pykrx 의존(get_index_ohlcv via fetch_index). 조회 실패는 fail-closed(예외 전파).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from kr_pipeline.ohlcv.fetch import fetch_index

log = logging.getLogger("kr_pipeline.common.trading_calendar")

CLOSE_BUFFER = time(17, 0)   # KST. KRX 마감 15:30 후 pykrx EOD 안정화 시점.
_KOSPI_INDEX = "1001"
_LOOKBACK_DAYS = 14          # 최근 거래일 목록 확보(연휴 대비 충분).


class TradingCalendarUnavailable(RuntimeError):
    """거래 캘린더(라이브 KRX 지수) 조회 실패 — fail-closed."""


class StaleDataError(RuntimeError):
    """최신 완전 데이터가 기대 최신 거래일보다 뒤처짐 — 분석 중단."""


def expected_latest_trading_day(now: datetime) -> date:
    """기대 최신 거래일(ELTD).

    라이브 KRX 지수로 실제 거래일 목록을 얻고 마감버퍼로 오늘 포함 여부 결정:
    - 오늘이 거래일 & now.time() >= CLOSE_BUFFER → 오늘
    - 그 외 → 오늘 직전 거래일
    조회 실패/빈 결과/직전거래일 없음 → TradingCalendarUnavailable(fail-closed).
    """
    today = now.date()
    try:
        df = fetch_index(_KOSPI_INDEX, today - timedelta(days=_LOOKBACK_DAYS), today)
    except Exception as e:  # noqa: BLE001 — 모든 조회 실패를 fail-closed 로 수렴
        raise TradingCalendarUnavailable(f"거래 캘린더 조회 실패: {e}") from e
    if df is None or df.empty or "date" not in df.columns:
        raise TradingCalendarUnavailable("거래 캘린더 조회 결과 없음")
    trading_days = sorted({d for d in df["date"]})
    if today in trading_days and now.time() >= CLOSE_BUFFER:
        return today
    prior = [d for d in trading_days if d < today]
    if not prior:
        raise TradingCalendarUnavailable(
            f"직전 거래일 없음(lookback {_LOOKBACK_DAYS}d, today={today})"
        )
    return max(prior)


def assert_data_fresh(as_of: date, now: datetime) -> None:
    """as_of(최신 완전 지표일)가 ELTD 보다 뒤처지면 StaleDataError.

    ELTD 산출 실패(pykrx) 시 TradingCalendarUnavailable 전파(fail-closed).
    """
    eltd = expected_latest_trading_day(now)
    if as_of < eltd:
        raise StaleDataError(
            f"최신 거래일 {eltd} 데이터 미적재 (현재 최신 {as_of}) — 분석 중단"
        )
    log.info("freshness OK: as_of=%s eltd=%s", as_of, eltd)
