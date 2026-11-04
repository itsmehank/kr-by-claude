"""#124 — 저장 수정종가로 전 종목 강도 점수를 즉석 계산해 RS 순위를 현재 빈티지로 다시 매기는 도구. 외부 접촉 0."""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from kr_pipeline.indicators import modes
from kr_pipeline.indicators import rs_rank_recompute as m
from kr_pipeline.indicators.modes import Target

# 격리 구간(다른 테스트와 겹치지 않는 과거 연도)
D0 = date(2009, 1, 5)   # 월요일
W0 = date(2009, 1, 9)   # 금요일


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _fridays(start: date, n: int) -> list[date]:
    return [start + timedelta(days=7 * i) for i in range(n)]


def _price(kind: str, i: int) -> float:
    if kind == "up":
        return 100.0 + i * 0.5
    if kind == "down":
        return 300.0 - i * 0.3
    if kind == "wave":
        return 200.0 + 20.0 * math.sin(i / 17.0)
    return 150.0 + (i % 7) * 0.1  # flat


def seed_daily(db, spec: dict[str, tuple[str, int]], *, delisted: set[str] = frozenset()) -> list[date]:
    """spec = {ticker: (price_kind, n_rows)} — stocks + daily_prices + index_daily(1001). 반환 = 전체 날짜(최대 n)."""
    n_max = max(n for _, n in spec.values())
    days = _weekdays(D0, n_max)
    with db.cursor() as cur:
        for t, (kind, n) in spec.items():
            cur.execute("INSERT INTO stocks (ticker, name, market, delisted_at) VALUES (%s,'T','KOSPI',%s) "
                        "ON CONFLICT (ticker) DO UPDATE SET delisted_at = EXCLUDED.delisted_at",
                        (t, days[-1] + timedelta(days=30) if t in delisted else None))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            for i, d in enumerate(days[n_max - n:]):   # 신규상장 모사: 뒤쪽 n 행만
                p = _price(kind, i)
                cur.execute(
                    """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                           adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1000.0,1000,1)""",
                    (t, d, p, p, p, p, p, p, p, p),
                )
        for i, d in enumerate(days):
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close)
                   VALUES ('1001', %s, 2000, 2000, 2000, %s) ON CONFLICT (index_code, date) DO NOTHING""",
                (d, 2000.0 + i),
            )
    db.commit()
    return days


def cleanup_daily(db, tickers, days):
    with db.cursor() as cur:
        for t in tickers:
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM index_daily WHERE index_code='1001' AND date BETWEEN %s AND %s", (days[0], days[-1]))
    db.commit()


def run_phase_ab_daily(db, tickers, days):
    modes._phase_b_cache.clear()
    for t in tickers:
        modes._process_ticker_daily(db, t, "KOSPI", days[0], days[-1], days[0])
    modes._run_phase_b_daily(db, days[0], days[-1])
    modes._phase_b_cache.clear()


def stored_rs(db, target: Target, tickers) -> list[tuple[str, date, int | None]]:
    tbl, col = ("daily_indicators", "date") if target == Target.DAILY else ("weekly_indicators", "week_end_date")
    with db.cursor() as cur:
        cur.execute(f"SELECT ticker, {col}, rs_rating FROM {tbl} WHERE ticker = ANY(%s) ORDER BY 1, 2", (list(tickers),))
        return cur.fetchall()


def assert_ranks_equal(got: pd.DataFrame, stored_rows):
    assert len(stored_rows) > 0
    for t, d, stored in stored_rows:
        v = got.at[d, t]
        assert (pd.isna(v) and stored is None) or (not pd.isna(v) and int(v) == stored), (t, d, stored, v)


DAILY_SPEC = {"RK124A": ("up", 300), "RK124B": ("down", 300), "RK124C": ("wave", 150), "RK124D": ("flat", 300)}


def test_rank_table_equals_phase_b_daily(db):
    """저장 Phase B(캐시 경유) 와 즉석 계산(저장 adj_close 경유)이 모든 셀에서 같다 —
    신규상장(C, 150행 → SF NaN → NULL)·상폐됐지만 과거 행이 있는 종목(D) 포함."""
    tickers = list(DAILY_SPEC)
    days = seed_daily(db, DAILY_SPEC, delisted={"RK124D"})
    try:
        run_phase_ab_daily(db, tickers, days)
        stored = stored_rs(db, Target.DAILY, tickers)
        assert any(r[2] is not None for r in stored)
        assert all(r[2] is None for r in stored if r[0] == "RK124C")
        uni = [t for t in m.universe_tickers(db, Target.DAILY) if t in tickers]
        assert set(uni) == set(tickers), "상폐 종목도 지표 행이 있으면 유니버스에 포함"
        sf = m.strength_table(db, Target.DAILY, tickers=uni, end=days[-1])
        got = m.rank_table(sf, days)
        assert_ranks_equal(got, stored)
    finally:
        cleanup_daily(db, tickers, days)


def seed_weekly(db, spec: dict[str, tuple[str, int]]) -> list[date]:
    n_max = max(n for _, n in spec.values())
    weeks = _fridays(W0, n_max)
    with db.cursor() as cur:
        for t, (kind, n) in spec.items():
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
            for i, d in enumerate(weeks[n_max - n:]):
                p = _price(kind, i)
                cur.execute(
                    """INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close,
                           adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, trading_days)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1000.0,1000,1,5)""",
                    (t, d, p, p, p, p, p, p, p, p),
                )
        for i, d in enumerate(weeks):
            cur.execute(
                """INSERT INTO weekly_index (index_code, week_end_date, open, high, low, close, trading_days)
                   VALUES ('1001', %s, 2000, 2000, 2000, %s, 5) ON CONFLICT (index_code, week_end_date) DO NOTHING""",
                (d, 2000.0 + i),
            )
    db.commit()
    return weeks


def cleanup_weekly(db, tickers, weeks):
    with db.cursor() as cur:
        for t in tickers:
            cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM weekly_index WHERE index_code='1001' AND week_end_date BETWEEN %s AND %s",
                    (weeks[0], weeks[-1]))
    db.commit()


WEEKLY_SPEC = {"RK124W1": ("up", 60), "RK124W2": ("down", 60), "RK124W3": ("wave", 30)}


def test_rank_table_equals_phase_b_weekly(db):
    tickers = list(WEEKLY_SPEC)
    weeks = seed_weekly(db, WEEKLY_SPEC)
    try:
        modes._phase_b_cache.clear()
        for t in tickers:
            modes._process_ticker_weekly(db, t, "KOSPI", weeks[0], weeks[-1], weeks[0])
        modes._run_phase_b_weekly(db, weeks[0], weeks[-1])
        modes._phase_b_cache.clear()
        stored = stored_rs(db, Target.WEEKLY, tickers)
        assert any(r[2] is not None for r in stored)
        uni = [t for t in m.universe_tickers(db, Target.WEEKLY) if t in tickers]
        sf = m.strength_table(db, Target.WEEKLY, tickers=uni, end=weeks[-1])
        got = m.rank_table(sf, weeks)
        assert_ranks_equal(got, stored)
    finally:
        cleanup_weekly(db, tickers, weeks)
