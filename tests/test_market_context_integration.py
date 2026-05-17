# tests/test_market_context_integration.py
from datetime import date, timedelta
import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.market_context.modes import Mode, run


pytestmark = pytest.mark.integration


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM market_context_daily")
        cur.execute("DELETE FROM daily_indicators")
        cur.execute("DELETE FROM index_daily")
        cur.execute("DELETE FROM daily_prices")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('MKTTEST1', 'MKTTEST2')")
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'market_context'")
    conn.commit()


def _seed_index_data(conn, days: int = 300):
    """KOSPI 1001 에 days 일치 데이터 + KOSDAQ 2001 에 들어가는 더미.

    SMA200/yearly_high 통과 위해 충분한 일수.
    """
    base = date(2025, 1, 2)
    with conn.cursor() as cur:
        # stocks: KOSPI 종목 1개 + KOSDAQ 종목 1개
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('MKTTEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('MKTTEST2', 'T2', 'KOSDAQ') ON CONFLICT DO NOTHING")

        for i in range(days):
            d = base + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            # KOSPI 지수: 우상향
            kospi_close = 2500 + i * 1.0
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES ('1001', %s, %s, %s, %s, %s, 1000, 1000000)
                   ON CONFLICT DO NOTHING""",
                (d, kospi_close - 5, kospi_close + 5, kospi_close - 8, kospi_close),
            )
            # KOSDAQ
            kosdaq_close = 700 + i * 0.5
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES ('2001', %s, %s, %s, %s, %s, 500, 500000)
                   ON CONFLICT DO NOTHING""",
                (d, kosdaq_close - 3, kosdaq_close + 3, kosdaq_close - 5, kosdaq_close),
            )
            # daily_prices + daily_indicators (breadth 용)
            for ticker in ("MKTTEST1", "MKTTEST2"):
                price = 100.0 + i * 0.1
                cur.execute(
                    """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 1000, 100000)
                       ON CONFLICT DO NOTHING""",
                    (ticker, d, price, price + 1, price - 1, price, price),
                )
                # daily_indicators: 마지막 ~100 일에만 sma_200 채움 (lookback 200 통과)
                sma_200 = price - 5 if i >= 200 else None
                cur.execute(
                    """INSERT INTO daily_indicators (ticker, date, adj_close, sma_200, sma_50)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (ticker, d, price, sma_200, price - 2 if i >= 50 else None),
                )
    conn.commit()


def test_backfill_creates_kospi_and_kosdaq_rows(test_db_url):
    """backfill → 매 영업일에 KOSPI + KOSDAQ 양쪽 행 생성."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_index_data(conn, days=300)

        try:
            stats = run(conn, Mode.BACKFILL)

            assert stats.rows_affected > 0

            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM market_context_daily WHERE index_code = '1001'")
                kospi_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM market_context_daily WHERE index_code = '2001'")
                kosdaq_count = cur.fetchone()[0]

                assert kospi_count > 0
                assert kospi_count == kosdaq_count  # 같은 날짜 양쪽 다 생성

                # current_status enum 4 종류 외 없는지
                cur.execute("""
                    SELECT DISTINCT current_status FROM market_context_daily
                """)
                statuses = {row[0] for row in cur.fetchall()}
                allowed = {"confirmed_uptrend", "rally_attempt", "correction", "downtrend"}
                assert statuses.issubset(allowed)

                # pipeline_runs
                cur.execute("""
                    SELECT pipeline, mode, status FROM pipeline_runs
                     WHERE pipeline = 'market_context' ORDER BY id DESC LIMIT 1
                """)
                row = cur.fetchone()
                assert row == ("market_context", "backfill", "success")
        finally:
            _cleanup(conn)


def test_incremental_idempotent(test_db_url):
    """incremental 두 번 → 결과 행 수 동일."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_index_data(conn, days=300)

        try:
            run(conn, Mode.BACKFILL)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM market_context_daily")
                first_count = cur.fetchone()[0]

            run(conn, Mode.INCREMENTAL, window_days=30)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM market_context_daily")
                second_count = cur.fetchone()[0]

            assert first_count == second_count
        finally:
            _cleanup(conn)
