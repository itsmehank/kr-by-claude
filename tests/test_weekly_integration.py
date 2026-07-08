"""weekly 파이프라인 end-to-end 통합 테스트.
실제 Postgres 필요. 네트워크는 안 씀 (DB-to-DB)."""
from datetime import date

import pytest

from kr_pipeline.db.connection import connect
from kr_pipeline.weekly.modes import Mode, run


pytestmark = pytest.mark.integration


def _cleanup(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM weekly_prices")
        cur.execute("DELETE FROM weekly_index")
        cur.execute("DELETE FROM daily_prices")
        cur.execute("DELETE FROM index_daily")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('WEEKTEST1', 'WEEKTEST2')")
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'weekly'")
    conn.commit()


def _seed_daily(conn):
    """2주치 일봉 + 2종목 + 지수 시드."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('WEEKTEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('WEEKTEST2', 'T2', 'KOSPI') ON CONFLICT DO NOTHING")
        # Week 1: 2026-04-28(Mon) ~ 2026-05-02(Fri)  — 완전한 과거 주
        # Week 2: 2026-05-05(Mon) ~ 2026-05-09(Fri)  — 완전한 과거 주
        days_w1 = [date(2026, 4, 28), date(2026, 4, 29), date(2026, 4, 30), date(2026, 5, 1), date(2026, 5, 2)]
        days_w2 = [date(2026, 5, 5), date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8), date(2026, 5, 9)]
        for ticker in ("WEEKTEST1", "WEEKTEST2"):
            for d in days_w1 + days_w2:
                cur.execute(
                    """
                    INSERT INTO daily_prices (ticker, date, open, high, low, close,
                                              adj_close, adj_high, adj_low, adj_open, adj_volume,
                                              volume, value)
                    VALUES (%s, %s, 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 1000, 1000, 105000)
                    """,
                    (ticker, d),
                )
        for d in days_w1 + days_w2:
            cur.execute(
                """
                INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                VALUES ('1001', %s, 2500, 2520, 2480, 2510, 1000, 1000000)
                """,
                (d,),
            )
    conn.commit()


def test_backfill_end_to_end(test_db_url):
    """일봉 시드 → backfill → weekly 2주 × 2종목 + 지수 2주."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_daily(conn)

        try:
            stats = run(conn, Mode.BACKFILL, only_tickers=["WEEKTEST1", "WEEKTEST2"])

            assert stats.rows_affected >= 4

            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker LIKE 'WEEKTEST%'")
                assert cur.fetchone()[0] == 4  # 2주 × 2종목
                cur.execute("SELECT COUNT(*) FROM weekly_index WHERE index_code = '1001'")
                assert cur.fetchone()[0] == 2  # 2주
                cur.execute(
                    "SELECT close, trading_days FROM weekly_prices "
                    "WHERE ticker = 'WEEKTEST1' AND week_end_date = '2026-05-09'"
                )
                assert cur.fetchone() == (105, 5)
                cur.execute("SELECT pipeline, mode, status FROM pipeline_runs ORDER BY id DESC LIMIT 1")
                assert cur.fetchone() == ("weekly", "backfill", "success")
        finally:
            _cleanup(conn)


def test_incremental_overwrites_existing(test_db_url):
    """incremental 두 번 돌려도 결과 동일 (멱등)."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        _seed_daily(conn)

        try:
            run(conn, Mode.BACKFILL, only_tickers=["WEEKTEST1", "WEEKTEST2"])
            run(conn, Mode.INCREMENTAL, window_weeks=4, only_tickers=["WEEKTEST1", "WEEKTEST2"])

            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker LIKE 'WEEKTEST%'")
                assert cur.fetchone()[0] == 4
        finally:
            _cleanup(conn)


def test_partial_failure_isolates(test_db_url):
    """한 종목 데이터 없음 → 다른 종목은 정상 적재."""
    with connect(test_db_url) as conn:
        _cleanup(conn)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('WEEKTEST1', 'T1', 'KOSPI') ON CONFLICT DO NOTHING")
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('WEEKTEST2', 'T2', 'KOSPI') ON CONFLICT DO NOTHING")
            for d in [date(2026, 4, 28), date(2026, 4, 29), date(2026, 5, 2)]:
                cur.execute(
                    """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                                                 adj_close, adj_high, adj_low, adj_open, adj_volume,
                                                 volume, value)
                       VALUES ('WEEKTEST1', %s, 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 1000, 1000, 105000)""",
                    (d,),
                )
        conn.commit()

        try:
            stats = run(conn, Mode.BACKFILL, only_tickers=["WEEKTEST1", "WEEKTEST2"])

            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker = 'WEEKTEST1'")
                assert cur.fetchone()[0] == 1
                cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE ticker = 'WEEKTEST2'")
                assert cur.fetchone()[0] == 0
        finally:
            _cleanup(conn)


def test_process_ticker_heals_partial_week_orphan(db):
    """일봉이 화요일까지만 있을 때 집계된 부분 주봉(week_end=화)이,
    완전한 일봉으로 재집계 시 금요일 행으로 교체되고 화요일 고아가 삭제된다.

    production 사고(2026-06-07): 597종목이 같은 ISO 주에 (화, td=2) + (금, td=4)
    두 행을 갖게 됨 — full-refresh 로도 복구 불가였다."""
    from datetime import date
    from kr_pipeline.weekly.modes import _process_ticker

    t = "HEAL1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        # 1차: 월·화만 적재된 stale 상태 (2026-06-01 월, 06-02 화)
        for d in (date(2026, 6, 1), date(2026, 6, 2)):
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                       adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value)
                   VALUES (%s,%s,100,110,95,105,105.0,110.0,95.0,100.0,1000.0,1000,1)""",
                (t, d),
            )
    db.commit()

    # 1차 집계 (today=일요일 → '주말이라 완료' 간주, 부분 행 기록)
    _process_ticker(db, t, date(2026, 6, 1), date(2026, 6, 6), date(2026, 6, 7))
    with db.cursor() as cur:
        cur.execute("SELECT week_end_date, trading_days FROM weekly_prices WHERE ticker=%s", (t,))
        assert cur.fetchall() == [(date(2026, 6, 2), 2)]  # 부분 행

    # 수·목·금 일봉 도착
    with db.cursor() as cur:
        for d in (date(2026, 6, 3), date(2026, 6, 4), date(2026, 6, 5)):
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                       adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value)
                   VALUES (%s,%s,100,110,95,105,105.0,110.0,95.0,100.0,1000.0,1000,1)""",
                (t, d),
            )
    db.commit()

    # 2차 집계 — 금요일 행으로 교체되고 화요일 고아는 삭제되어야 한다
    _process_ticker(db, t, date(2026, 6, 1), date(2026, 6, 6), date(2026, 6, 7))
    with db.cursor() as cur:
        cur.execute("SELECT week_end_date, trading_days FROM weekly_prices WHERE ticker=%s ORDER BY week_end_date", (t,))
        rows = cur.fetchall()
        # cleanup — stocks 도 삭제 (남기면 limit_tickers 쓰는 후속 테스트가 HEAL1 을 집어감)
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
    db.commit()
    assert rows == [(date(2026, 6, 5), 5)], f"화요일 고아가 남음: {rows}"
