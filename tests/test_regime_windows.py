"""#207 회신 21 Q-5c 2 — 판정 창(일봉 50/주봉 50/앵커~평가) 날짜로 volume_regime_flag 유도."""
from datetime import date, timedelta

from kr_pipeline.common.data_regimes import VOLUME_REGIME_BOUNDARY as B
from kr_pipeline.common.regime_windows import (
    classification_flag, daily_window_flag, entry_window_flag, weekly_range_flag, weekly_window_flag,
)


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


def test_classification_flag_combines_daily_and_weekly(db):
    days = _weekdays(B - timedelta(days=10), 52)                               # 일간 창(마지막 50봉): 경계 걸침
    _seed_daily(db, "RWJ1", days)
    fridays = [B + timedelta(days=4) + timedelta(weeks=i) for i in range(3)]   # 주간 창: 전부 extended
    _seed_weekly(db, "RWJ1", fridays)
    as_of = days[-1]
    assert classification_flag(db, "RWJ1", as_of) == "mixed"
    assert weekly_window_flag(db, "RWJ1", as_of) is None


def test_flags_short_circuit_before_boundary_without_db(db, monkeypatch):
    """as_of < 경계면 창의 모든 봉이 regular 라 DB 를 읽지 않고 NULL(백필 수천 셀의 무의미한 왕복 제거, 리뷰 #222)."""
    import kr_pipeline.common.regime_windows as rw
    monkeypatch.setattr(rw, "price_source", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB 접근 금지")))
    d = B - timedelta(days=1)
    assert daily_window_flag(db, "ANY", d) is None and weekly_window_flag(db, "ANY", d) is None
    assert classification_flag(db, "ANY", d) is None and entry_window_flag(db, "ANY", d) is None
    assert weekly_range_flag(db, "ANY", (d - timedelta(days=30)).isoformat(), d) is None


def test_flags_fail_soft_and_keep_transaction_usable(db, monkeypatch, caplog):
    """관측 전용 헬퍼의 SQL 오류가 본 INSERT(LLM 비용 지출분)를 막으면 안 된다(store #39 규약) — SAVEPOINT 격리 후 None."""
    import logging
    import kr_pipeline.common.regime_windows as rw
    from kr_pipeline.common.price_source import PriceSource
    monkeypatch.setattr(rw, "price_source", lambda *a, **k: PriceSource("no_such_table_x", "no_such_table_y", "", "", False))
    with caplog.at_level(logging.WARNING, logger="kr_pipeline.common.regime_windows"):
        assert daily_window_flag(db, "RWX1", B) is None
        assert weekly_range_flag(db, "RWX1", B.isoformat(), B) is None
    assert "regime_window_flag_failed" in caplog.text
    with db.cursor() as cur:                                   # 트랜잭션 오염 없음
        cur.execute("SELECT 1"); assert cur.fetchone()[0] == 1


def test_entry_window_flag_covers_pocket_pivot_lookback(db):
    """진입 창: pocket_pivot 분기는 관측 비율이 PP 일(최근 5세션 중 최신)에서 끝나는 50봉 창 — as_of 창 + 4봉을 더 보아 보수적(mixed 쪽)."""
    days = _weekdays(B - timedelta(days=200), 240)
    _seed_daily(db, "RWE1", days)
    after = [d for d in days if d >= B]
    assert daily_window_flag(db, "RWE1", after[49]) is None                    # as_of 50봉 창은 만료
    assert entry_window_flag(db, "RWE1", after[49]) == "mixed"                 # PP 일이 4봉 전이면 그 창은 아직 걸침
    assert entry_window_flag(db, "RWE1", after[53]) is None                    # +4봉 뒤 만료
