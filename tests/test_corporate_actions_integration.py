# tests/test_corporate_actions_integration.py
"""corporate_actions end-to-end. DART API 는 mock — 실 호출 없음."""
from datetime import date
from unittest.mock import patch

import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.corporate_actions.modes import Mode, run


pytestmark = pytest.mark.integration


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM corporate_actions")
        cur.execute("DELETE FROM dart_corp_codes WHERE stock_code IN ('CATEST1', 'CATEST2')")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('CATEST1', 'CATEST2')")
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'corporate_actions'")
    conn.commit()


def _seed(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('CATEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('CATEST2', 'T2', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute(
            "INSERT INTO dart_corp_codes (stock_code, corp_code, corp_name) VALUES ('CATEST1', '11111111', 'T1') ON CONFLICT DO NOTHING"
        )
        cur.execute(
            "INSERT INTO dart_corp_codes (stock_code, corp_code, corp_name) VALUES ('CATEST2', '22222222', 'T2') ON CONFLICT DO NOTHING"
        )
    conn.commit()


def test_backfill_with_mocked_disclosures(test_db_url):
    """공시 mock 응답 → corporate_actions 행 생성 검증 (일괄 조회 + 역매핑).

    bulk 계약: fetch 는 corp_code=None 으로 호출되고, 응답에 섞인
    - 매핑된 회사(11111111→CATEST1)는 적재
    - 우리 universe 밖 회사(99999999)는 무시
    """
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed(conn)

        calls = []

        def mock_fetch(api_key, corp_code, start_date, end_date, pblntf_ty="B"):
            calls.append(corp_code)
            if len(calls) == 1:  # 첫 청크에만 공시 존재 (다른 청크는 빈 응답)
                return [
                    {"corp_code": "11111111", "report_nm": "주식분할결정",
                     "rcept_no": "20240312000123", "rcept_dt": "20240312"},
                    {"corp_code": "99999999", "report_nm": "주식분할결정",
                     "rcept_no": "20240312000999", "rcept_dt": "20240312"},
                ]
            return []

        try:
            with patch("kr_pipeline.corporate_actions.modes.fetch_disclosures", side_effect=mock_fetch):
                stats = run(conn, Mode.BACKFILL, api_key="MOCK", years=1)

            assert stats.rows_affected == 1
            assert stats.failures == []
            assert calls and all(c is None for c in calls), f"bulk 호출이어야: {calls}"

            with conn.cursor() as cur:
                cur.execute("SELECT ticker, event_type, dart_rcept_no FROM corporate_actions ORDER BY ticker")
                rows = cur.fetchall()
            assert rows == [("CATEST1", "stock_split", "20240312000123")]
        finally:
            _cleanup(conn)


def test_idempotent_incremental(test_db_url):
    """incremental 두 번 → 행 수 동일."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed(conn)

        def mock_fetch(api_key, corp_code, start_date, end_date, pblntf_ty="B"):
            return [{
                "corp_code": "11111111", "report_nm": "주식병합결정",
                "rcept_no": "20240315000456", "rcept_dt": "20240315",
            }]

        try:
            with patch("kr_pipeline.corporate_actions.modes.fetch_disclosures", side_effect=mock_fetch):
                run(conn, Mode.INCREMENTAL, api_key="MOCK", window_days=365)
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM corporate_actions")
                    first = cur.fetchone()[0]

                run(conn, Mode.INCREMENTAL, api_key="MOCK", window_days=365)
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM corporate_actions")
                    second = cur.fetchone()[0]

            assert first == 1
            assert second == 1
        finally:
            _cleanup(conn)


def test_incremental_fetches_once_not_per_ticker(test_db_url):
    """7일 incremental 은 종목 수와 무관하게 fetch 1회 — N+1 제거의 핵심 계약.

    (예전: 활성 매핑 종목 ~2,500개 × 회사별 DART 호출. 지금: 기간 일괄 1회.)
    """
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed(conn)  # 매핑 종목 2개

        calls = []

        def mock_fetch(api_key, corp_code, start_date, end_date, pblntf_ty="B"):
            calls.append((corp_code, start_date, end_date))
            return []

        try:
            with patch("kr_pipeline.corporate_actions.modes.fetch_disclosures", side_effect=mock_fetch):
                stats = run(conn, Mode.INCREMENTAL, api_key="MOCK", window_days=7)

            assert stats.failures == []
            assert len(calls) == 1, f"7일 창은 청크 1개 = 호출 1회여야: {len(calls)}회"
            assert calls[0][0] is None
        finally:
            _cleanup(conn)
