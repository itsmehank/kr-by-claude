from datetime import date, timedelta
from api.services.csv_builder import build_daily_csv, build_weekly_csv, build_index_csv


def _seed_daily(db, ticker="DAILY1", n=10):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, 'D', 'KOSPI') ON CONFLICT DO NOTHING", (ticker,))
        for i in range(n):
            d = date(2026, 5, 1) + timedelta(days=i)
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
