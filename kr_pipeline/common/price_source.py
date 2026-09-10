"""(#181 B4) 가격·지표 테이블 리졸버 — 심볼이 상폐 격리 데이터(P0-①)를 가지면 격리 테이블, 아니면 라이브.

판정: `delisted_daily_prices` 에 행 존재 → 격리. (stocks.delisted_at 이 아니라 데이터 존재로 판정 —
레거시 상폐 17종목은 daily_prices 에만 있어 라이브로 남는다.)
rs_source: "live" = 라이브 daily_indicators.rs_rating(생존 유니버스 백분위) — 격리 종목은 항상
delisted_daily_indicators(rs = bt_rs_daily 유래). "bt" = 생존 종목도 bt_rs_daily(무편향) — ②-2 결정 후 사용.
테이블명은 이 모듈의 상수만 — SQL 에 f-string 으로 들어가므로 외부 입력 금지.
"""
from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection


@dataclass(frozen=True)
class PriceSource:
    daily: str          # daily_prices 동일 컬럼 집합(raw + adj_*)
    weekly: str         # weekly_prices 동일 컬럼 집합
    indicators: str     # daily_indicators 동일 37컬럼
    rs: str             # rs_rating 을 읽을 테이블(ticker, date, rs_rating)
    delisted: bool


LIVE = PriceSource("daily_prices", "weekly_prices", "daily_indicators", "daily_indicators", False)
DELISTED = PriceSource("delisted_daily_prices_adj", "delisted_weekly_prices",
                       "delisted_daily_indicators", "delisted_daily_indicators", True)
BT_RS_TABLE = "bt_rs_daily"


def is_delisted_isolated(conn: Connection, ticker: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM delisted_daily_prices WHERE ticker = %s LIMIT 1", (ticker,))
        return cur.fetchone() is not None


def price_source(conn: Connection, ticker: str, rs_source: str = "live") -> PriceSource:
    if rs_source not in ("live", "bt"):
        raise ValueError(f"rs_source must be 'live' or 'bt': {rs_source!r}")
    if is_delisted_isolated(conn, ticker):
        return DELISTED
    if rs_source == "bt":
        return PriceSource(LIVE.daily, LIVE.weekly, LIVE.indicators, BT_RS_TABLE, False)
    return LIVE
