# kr_pipeline/ohlcv/delisted_backfill.py
"""#114 — 상폐 종목 이력 백필 (별도 테이블 적재, 라이브 경로 무접촉).

설계: docs/superpowers/specs/2026-08-18-issue114-delisted-restore-design.md (v2)
- 적재 대상 = delisted_daily_prices(raw)·share_counts. 기존 daily_prices 무접촉.
- stocks 는 신규 행 INSERT 만 (ON CONFLICT DO NOTHING — 기존 행 무수정 보장).
- 체크포인트 = 종목 단위, 일일 사용자 호출 예산 관리 포함.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time as dtime
from pathlib import Path

from psycopg import Connection

PACE_SEC = 2.0
DAILY_CALL_CAP = 2000
ABORT_CONSECUTIVE_ERRORS = 5
_NIGHT_START = dtime(20, 30)
_NIGHT_END = dtime(6, 0)


def in_window(now: datetime) -> bool:
    """실행 창(설계 §2): 주말 종일, 평일은 20:30~익일 06:00."""
    if now.weekday() >= 5:
        return True
    return now.time() >= _NIGHT_START or now.time() < _NIGHT_END


def load_checkpoint(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"done": [], "calls": {}}


def save_checkpoint(path: Path, cp: dict) -> None:
    path.write_text(json.dumps(cp, ensure_ascii=False, indent=1))


def calls_today(cp: dict, day: str) -> int:
    return int(cp["calls"].get(day, 0))


def add_calls(cp: dict, day: str, n: int) -> None:
    cp["calls"][day] = calls_today(cp, day) + n


def price_rows(ticker: str, df) -> list[tuple]:
    """pykrx OHLCV DataFrame(한글 컬럼, 날짜 index) → delisted_daily_prices 행."""
    return [(ticker, idx.date(), float(r["시가"]), float(r["고가"]),
             float(r["저가"]), float(r["종가"]), int(r["거래량"]), int(r["거래대금"]))
            for idx, r in df.iterrows()]


def share_rows(ticker: str, df) -> list[tuple]:
    """pykrx 시가총액 DataFrame → share_counts 행."""
    return [(ticker, idx.date(), int(r["상장주식수"])) for idx, r in df.iterrows()]


def upsert_delisted_stock(conn: Connection, ticker: str, name: str, market: str,
                          delisted_at: date, is_common: bool) -> None:
    """신규 행만 INSERT — 기존 행은 어떤 컬럼도 수정하지 않는다(설계 §3-2)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market, delisted_at, is_common) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (ticker) DO NOTHING",
            (ticker, name, market, delisted_at, is_common),
        )


def _idempotent_insert(conn: Connection, table: str, insert_sql: str,
                       rows: list[tuple]) -> int:
    """멱등 적재(이어받기 안전). 반환 = 신규 삽입 행 수(사전/사후 차이)."""
    if not rows:
        return 0
    ticker, d_from, d_to = rows[0][0], rows[0][1], rows[-1][1]
    count_sql = (f"SELECT COUNT(*) FROM {table} "  # noqa: S608 — table 은 상수
                 "WHERE ticker = %s AND date BETWEEN %s AND %s")
    with conn.cursor() as cur:
        cur.execute(count_sql, (ticker, d_from, d_to))
        before = cur.fetchone()[0]
        cur.executemany(insert_sql, rows, returning=False)
        cur.execute(count_sql, (ticker, d_from, d_to))
        return cur.fetchone()[0] - before


def insert_delisted_prices(conn: Connection, rows: list[tuple]) -> int:
    return _idempotent_insert(
        conn, "delisted_daily_prices",
        "INSERT INTO delisted_daily_prices "
        "(ticker, date, open, high, low, close, volume, value) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", rows)


def insert_share_counts(conn: Connection, rows: list[tuple]) -> int:
    return _idempotent_insert(
        conn, "share_counts",
        "INSERT INTO share_counts (ticker, date, shares) "
        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", rows)
