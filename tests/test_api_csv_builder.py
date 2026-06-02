from datetime import date, timedelta
from api.services.csv_builder import build_daily_csv, build_weekly_csv, build_index_csv


def _seed_daily(db, ticker="DAILY1", n=10):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, 'D', 'KOSPI') ON CONFLICT DO NOTHING", (ticker,))
        for i in range(n):
            d = date(2026, 5, 1) + timedelta(days=i)
            # 가격·거래량 권위 소스 = daily_prices (Phase 0 Step 2 fix)
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s, %s, 100, 105, 95, 100, 100, 1000, 100000)
                   ON CONFLICT DO NOTHING""",
                (ticker, d),
            )
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, adj_close, volume, sma_50)
                   VALUES (%s, %s, 100, 1000, 95)
                   ON CONFLICT DO NOTHING""",
                (ticker, d),
            )
    db.commit()


def test_build_daily_csv_returns_bytes(db):
    _seed_daily(db, n=5)
    csv_bytes = build_daily_csv(db, "DAILY1", days=10)
    assert isinstance(csv_bytes, bytes)
    text = csv_bytes.decode("utf-8")
    assert "date" in text   # header
    assert "100" in text     # 값


def test_build_daily_csv_empty_ticker(db):
    """데이터 없는 종목 → header 만."""
    csv_bytes = build_daily_csv(db, "NOEXIST", days=10)
    text = csv_bytes.decode("utf-8")
    assert "date" in text
    # 한 줄 (header) 만
    assert len([l for l in text.strip().split("\n") if l]) == 1


def test_build_daily_csv_respects_on_date(db):
    from datetime import date, timedelta
    t = "ASOFD1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'D','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        for i in range(20):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute(
                """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                   VALUES (%s,%s,100,105,95,100,%s,1000,100000) ON CONFLICT DO NOTHING""",
                (t, d, 100 + i),
            )
    db.commit()
    try:
        text = build_daily_csv(db, t, days=60, on_date=date(2025, 6, 10)).decode("utf-8")
        dates = [l.split(",")[0] for l in text.strip().split("\n")[1:]]
        assert "2025-06-10" in dates
        assert "2025-06-11" not in dates
        assert max(dates) == "2025-06-10"
        text2 = build_daily_csv(db, t, days=60).decode("utf-8")
        dates2 = [l.split(",")[0] for l in text2.strip().split("\n")[1:]]
        assert "2025-06-20" in dates2
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        db.commit()
