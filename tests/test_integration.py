"""실제 Postgres 와 (제한된) pykrx 호출을 사용하는 통합 테스트.
네트워크 + DB 모두 필요. 실패 시 환경 문제일 가능성 있음."""
from datetime import date

import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.ohlcv.modes import Mode, run
from kr_pipeline.universe.fetch import fetch_universe
from kr_pipeline.universe.transform import filter_common_stocks
from kr_pipeline.universe.store import upsert_stocks


pytestmark = pytest.mark.integration


def test_universe_then_ohlcv_incremental_smoke(test_db_url):
    """소규모 universe + 7일 incremental 이 정상 동작.

    Cleans up after itself so subsequent unit tests see empty stocks/daily_prices/pipeline_runs.
    """
    with connect(test_db_url) as conn:
        # 1) 작은 universe 시드 (삼성전자, SK하이닉스)
        with conn.cursor() as cur:
            # 잔존행이 stocks 를 FK 로 참조할 수 있어(weekly_prices 등) CASCADE 로 일괄 정리
            cur.execute("TRUNCATE stocks CASCADE")
            cur.execute("DELETE FROM pipeline_runs")
        import pandas as pd
        df = pd.DataFrame([
            {"ticker": "005930", "name": "삼성전자", "market": "KOSPI", "sector": None},
            {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI", "sector": None},
        ])
        upsert_stocks(conn, df)
        conn.commit()

        try:
            # 2) 7일 incremental
            stats = run(conn, Mode.INCREMENTAL, window_days=7, limit_tickers=2, max_workers=2)

            # 3) 검증
            assert stats.rows_affected > 0
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM daily_prices")
                assert cur.fetchone()[0] > 0
                cur.execute("SELECT pipeline, mode, status FROM pipeline_runs ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                assert row == ("ohlcv", "incremental", "success")
        finally:
            # 4) 정리 — 후속 unit test 격리를 위해
            with conn.cursor() as cur:
                cur.execute("DELETE FROM index_daily")
                cur.execute("DELETE FROM pipeline_runs")
                cur.execute("TRUNCATE stocks CASCADE")
            conn.commit()
