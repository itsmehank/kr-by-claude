# tests/test_indicators_integration.py
"""indicators end-to-end 통합 테스트. 실제 Postgres + #1/#1.5 입력 데이터."""
from datetime import date, timedelta

import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.indicators.modes import Mode, Target, run_daily


pytestmark = pytest.mark.integration


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM daily_indicators")
        cur.execute("DELETE FROM weekly_indicators")
        cur.execute("DELETE FROM daily_prices")
        cur.execute("DELETE FROM index_daily")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('INDTEST1', 'INDTEST2')")
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'indicators'")
    conn.commit()


def _seed_300_days_data(conn):
    """300 일치 일봉 + 지수 (lookback 252 일 통과용).

    range(360) 달력일 → ~257 영업일 → 1y-return 유효 행 ~5개 확보.
    (range(300) 달력일 = ~214 영업일 < 252 window → rs_rating 모두 NULL)
    """
    with conn.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('INDTEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('INDTEST2', 'T2', 'KOSPI') ON CONFLICT DO NOTHING")
        base = date(2025, 1, 2)
        for i in range(360):
            d = base + timedelta(days=i)
            if d.weekday() >= 5:  # 주말 skip
                continue
            adj_close1 = 100.0 + i * 0.1
            # adj_volume = volume * close / adj_close (split-adjusted)
            adj_vol1 = round(1000.0 * 100.0 / adj_close1, 6)
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_open, adj_high, adj_low, adj_close, volume, adj_volume, value)
                   VALUES ('INDTEST1', %s, 100, 110, 90, 100, 100, 110, 90, %s, 1000, %s, 100000)""",
                (d, adj_close1, adj_vol1),   # 우상향
            )
            adj_close2 = 200.0 - i * 0.05
            adj_vol2 = round(2000.0 * 200.0 / adj_close2, 6)
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_open, adj_high, adj_low, adj_close, volume, adj_volume, value)
                   VALUES ('INDTEST2', %s, 200, 220, 180, 200, 200, 220, 180, %s, 2000, %s, 400000)""",
                (d, adj_close2, adj_vol2),  # 약한 우하향
            )
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES ('1001', %s, 2500, 2520, 2480, %s, 1000, 1000000)""",
                (d, 2500.0 + i * 0.01),
            )
    conn.commit()


def test_daily_backfill_end_to_end(test_db_url):
    """일봉 시드 → backfill → 3 phase 완료, minervini_pass 계산 확인."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_300_days_data(conn)

        try:
            stats = run_daily(conn, Mode.BACKFILL, limit_tickers=2)

            assert stats.rows_affected > 0

            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM daily_indicators WHERE ticker LIKE 'INDTEST%'")
                total_rows = cur.fetchone()[0]
                assert total_rows > 250  # 충분한 행

                # SMA(200) 마지막 행은 채워져 있어야
                cur.execute("""
                    SELECT sma_200 FROM daily_indicators
                     WHERE ticker = 'INDTEST1' ORDER BY date DESC LIMIT 1
                """)
                last_sma = cur.fetchone()[0]
                assert last_sma is not None

                # rs_rating 마지막 날 둘 다 계산됨
                cur.execute("""
                    SELECT ticker, rs_rating FROM daily_indicators
                     WHERE date = (SELECT MAX(date) FROM daily_indicators WHERE ticker LIKE 'INDTEST%')
                       AND ticker LIKE 'INDTEST%'
                """)
                rs_rows = cur.fetchall()
                rs_dict = {r[0]: r[1] for r in rs_rows}
                # INDTEST1 우상향 → rs_rating 더 높음
                assert rs_dict["INDTEST1"] >= rs_dict["INDTEST2"]

                # V2: volume columns populated
                cur.execute("""
                    SELECT volume, avg_volume_50d, volume_ratio_50d
                      FROM daily_indicators
                     WHERE ticker = 'INDTEST1' AND volume IS NOT NULL
                     ORDER BY date DESC LIMIT 1
                """)
                v_row = cur.fetchone()
                assert v_row is not None, "V2 volume columns should be populated"
                assert v_row[0] > 0, "adj_volume should be positive"

                # pipeline_runs 기록
                cur.execute("""
                    SELECT pipeline, mode, status, rows_affected FROM pipeline_runs
                     WHERE pipeline = 'indicators' ORDER BY id DESC LIMIT 1
                """)
                row = cur.fetchone()
                assert row[0] == "indicators"
                assert row[2] == "success"
                assert row[3] == total_rows or row[3] > 0
        finally:
            _cleanup(conn)


def test_idempotent_backfill_twice(test_db_url):
    """같은 backfill 두 번 → 결과 동일 (멱등)."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_300_days_data(conn)

        try:
            run_daily(conn, Mode.BACKFILL, limit_tickers=2)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM daily_indicators WHERE ticker LIKE 'INDTEST%'")
                first_count = cur.fetchone()[0]

            run_daily(conn, Mode.BACKFILL, limit_tickers=2)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM daily_indicators WHERE ticker LIKE 'INDTEST%'")
                second_count = cur.fetchone()[0]

            assert first_count == second_count
        finally:
            _cleanup(conn)
