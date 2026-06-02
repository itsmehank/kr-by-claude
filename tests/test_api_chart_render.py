"""차트 렌더링 단위 테스트. PNG bytes 가 valid 한지 + edge cases."""
import io

import pytest
from PIL import Image  # matplotlib 의존성에 포함

from api.services.chart_render import render_daily_chart, render_weekly_chart


def _seed_full_data(db, ticker="005930"):
    """일봉 + 지표 시드 (~60 일치)."""
    from datetime import date, timedelta
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성', 'KOSPI') ON CONFLICT DO NOTHING", (ticker,))
        for i in range(60):
            d = date(2026, 1, 1) + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            price = 70000 + i * 100
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 1000000, 70000000000)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, price - 100, price + 200, price - 200, price, price),
            )
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, adj_close, volume, sma_50)
                   VALUES (%s, %s, %s, 1000000, %s)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, price, price - 1000 if i >= 50 else None),
            )
    db.commit()


def test_render_daily_chart_returns_valid_png(db):
    _seed_full_data(db)
    png_bytes = render_daily_chart(db, "005930", range_days=60)
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 1000
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    assert img.width > 0


def test_render_daily_chart_short_history_no_error(db):
    """5 일치만 있어도 에러 없이 PNG 반환."""
    from datetime import date, timedelta
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('SHRT', 'S', 'KOSPI') ON CONFLICT DO NOTHING")
        for i in range(5):
            d = date(2026, 5, 11) + timedelta(days=i)
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('SHRT', %s, 100, 105, 95, 100, 100, 1000, 100000) ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, adj_close, volume)
                   VALUES ('SHRT', %s, 100, 1000) ON CONFLICT DO NOTHING""",
                (d,),
            )
    db.commit()
    png_bytes = render_daily_chart(db, "SHRT", range_days=5)
    assert len(png_bytes) > 500


def test_render_weekly_chart_returns_valid_png(db):
    from datetime import date, timedelta
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('WK1', 'W', 'KOSPI') ON CONFLICT DO NOTHING")
        for i in range(20):
            d = date(2026, 1, 2) + timedelta(weeks=i)
            cur.execute(
                """INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days)
                   VALUES ('WK1', %s, 100, 110, 90, 105, 105, 5000, 500000, 5)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, volume)
                   VALUES ('WK1', %s, 105, 5000) ON CONFLICT DO NOTHING""",
                (d,),
            )
    db.commit()
    png_bytes = render_weekly_chart(db, "WK1", range_weeks=20)
    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"


def test_render_weekly_chart_respects_on_date(db):
    from datetime import date, timedelta
    t = "ASOFC2"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'C','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        for i in range(12):
            wk = date(2025, 3, 7) + timedelta(weeks=i)
            price = 1000 + i * 10
            cur.execute(
                """INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,1000,100000,5) ON CONFLICT DO NOTHING""",
                (t, wk, price, price + 20, price - 20, price, price),
            )
    db.commit()
    try:
        populated = render_weekly_chart(db, t, range_weeks=104, on_date=date(2025, 3, 7) + timedelta(weeks=11))
        before_all = render_weekly_chart(db, t, range_weeks=104, on_date=date(2025, 1, 1))
        assert isinstance(populated, bytes) and len(populated) > 1000
        assert len(before_all) < len(populated)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        db.commit()


def test_render_daily_chart_respects_on_date(db):
    from datetime import date, timedelta
    t = "ASOFC1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'C','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        for i in range(20):
            d = date(2025, 6, 2) + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            price = 1000 + i * 10
            cur.execute(
                """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,1000,100000) ON CONFLICT DO NOTHING""",
                (t, d, price, price + 20, price - 20, price, price),
            )
    db.commit()
    try:
        populated = render_daily_chart(db, t, range_days=60, on_date=date(2025, 6, 20))
        before_all = render_daily_chart(db, t, range_days=60, on_date=date(2025, 1, 1))
        assert isinstance(populated, bytes) and len(populated) > 1000
        assert len(before_all) < len(populated)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        db.commit()
