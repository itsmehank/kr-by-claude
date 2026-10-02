"""#207 회신 21 Q-5c 2 — 판정 창(일봉 50/주봉 50/앵커~평가) 날짜로 volume_regime_flag 유도."""
from datetime import date, timedelta

from kr_pipeline.common.data_regimes import VOLUME_REGIME_BOUNDARY as B
from kr_pipeline.common.regime_windows import daily_window_flag, judgment_flag, weekly_range_flag, weekly_window_flag


def _seed_daily(db, ticker, dates):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) VALUES (%s,%s,1,1,1,1,1,1,1)",
                        [(ticker, d) for d in dates])


def _seed_weekly(db, ticker, week_ends):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days) "
                        "VALUES (%s,%s,1,1,1,1,1,1,1,5)", [(ticker, d) for d in week_ends])


def _weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_daily_window_flag_mixed_only_while_window_straddles_boundary(db):
    days = _weekdays(B - timedelta(days=120), 140)          # 경계 전후 넉넉히
    _seed_daily(db, "RWD1", days)
    before = [d for d in days if d < B]
    after = [d for d in days if d >= B]
    assert daily_window_flag(db, "RWD1", before[-1]) is None                  # 경계 전: clean
    assert daily_window_flag(db, "RWD1", after[0]) == "mixed"                 # 경계 당일: 49 regular + 1 extended
    assert daily_window_flag(db, "RWD1", after[48]) == "mixed"                # 50번째 봉 직전까지 mixed
    assert daily_window_flag(db, "RWD1", after[49]) is None                   # 경계 + 50봉: 전부 extended → new → NULL(자연 만료)


def test_daily_window_flag_with_fewer_bars_than_window(db):
    days = _weekdays(B - timedelta(days=5), 6)                                # 봉 6개뿐(신규 상장)
    _seed_daily(db, "RWD2", days)
    assert daily_window_flag(db, "RWD2", days[-1]) == "mixed"
    assert daily_window_flag(db, "RWD2", days[0]) is None


def test_weekly_window_and_range_flags(db):
    fridays = [date(2025, 10, 3) + timedelta(weeks=i) for i in range(60)]     # 금요일 60주(2025-10 ~ 2026-11)
    _seed_weekly(db, "RWW1", fridays)
    last_before = max(f for f in fridays if f < B)
    first_after = min(f for f in fridays if f >= B)
    assert weekly_window_flag(db, "RWW1", last_before) is None
    assert weekly_window_flag(db, "RWW1", first_after) == "mixed"
    assert weekly_range_flag(db, "RWW1", None, first_after) is None            # 앵커 없음 → 창 없음
    assert weekly_range_flag(db, "RWW1", first_after.isoformat(), first_after) is None   # 앵커=평가 주(extended 1주) → new
    assert weekly_range_flag(db, "RWW1", last_before.isoformat(), first_after) == "mixed"


def test_judgment_flag_combines_daily_and_weekly(db):
    days = _weekdays(B - timedelta(days=10), 52)                               # 일간 창(마지막 50봉): 경계 걸침
    _seed_daily(db, "RWJ1", days)
    fridays = [B + timedelta(days=4) + timedelta(weeks=i) for i in range(3)]   # 주간 창: 전부 extended
    _seed_weekly(db, "RWJ1", fridays)
    as_of = days[-1]
    assert judgment_flag(db, "RWJ1", as_of, daily=True, weekly=True) == "mixed"
    assert judgment_flag(db, "RWJ1", as_of, daily=False, weekly=True) is None
