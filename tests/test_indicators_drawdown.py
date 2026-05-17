"""drawdown 컬럼 계산 검증."""
from datetime import date, timedelta

import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.indicators.modes import Mode, run as run_indicators


pytestmark = pytest.mark.integration


_TICKER = "AA001"  # 알파벳 순 첫째가 되도록 → limit_tickers=1 테스트 통과


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM daily_indicators WHERE ticker = '{_TICKER}'")
        cur.execute(f"DELETE FROM daily_prices WHERE ticker = '{_TICKER}'")
        cur.execute(f"DELETE FROM stocks WHERE ticker = '{_TICKER}'")
    conn.commit()


def test_drawdown_pct_calculation(test_db_url):
    """drawdown_52w_pct = (w52_high - w52_low) / w52_high * 100"""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO stocks (ticker, name, market)
                    VALUES ('{_TICKER}', 'D', 'KOSPI') ON CONFLICT DO NOTHING
                """)
                for i in range(650):  # 2024-01-01 ~ 2025-10-xx (~465 영업일) → 252-day window 통과
                    d = date(2024, 1, 1) + timedelta(days=i)
                    if d.weekday() >= 5:
                        continue
                    price = 100 + i  # 강한 상승
                    cur.execute(
                        """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, 1000, 100000)
                           ON CONFLICT DO NOTHING""",
                        (_TICKER, d, price - 1, price + 1, price - 2, price, price),
                    )
                    # KOSPI 지수 데이터도 필요
                    cur.execute(
                        """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                           VALUES ('1001', %s, 2500, 2520, 2480, %s, 1000, 1000000)
                           ON CONFLICT DO NOTHING""",
                        (d, 2500.0 + i * 0.01),
                    )
            conn.commit()

            run_indicators(conn, target="daily", mode=Mode.BACKFILL, limit_tickers=1)

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT w52_high, w52_low, drawdown_52w_pct, drawdown_filter_pass
                      FROM daily_indicators
                     WHERE ticker = %s
                     ORDER BY date DESC LIMIT 1
                """, (_TICKER,))
                row = cur.fetchone()
            assert row is not None
            w52_high, w52_low, drawdown_pct, drawdown_pass = row
            assert drawdown_pct is not None, "drawdown_52w_pct should be calculated"
            expected_pct = (float(w52_high) - float(w52_low)) / float(w52_high) * 100
            assert abs(float(drawdown_pct) - expected_pct) < 0.01
            # 100→360 강한 상승: w52_high 큰, w52_low 작음 → drawdown 매우 클 것
            assert drawdown_pass == (expected_pct <= 50)
        finally:
            _cleanup(conn)
