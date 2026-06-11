# tests/test_indicators_store.py
from datetime import date

from kr_pipeline.indicators.store import (
    upsert_daily_indicators_phase_a,
    update_daily_indicators_rs_rating,
    update_daily_indicators_minervini_pass,
)


def _seed_stock(db, ticker="005930"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '삼성전자', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )


def test_upsert_phase_a_inserts_new_row(db):
    _seed_stock(db)
    rows = [{
        "ticker": "005930",
        "date": date(2026, 5, 15),
        "adj_close": 70000.0,
        "sma_10": 69000.0, "sma_21": 68000.0, "sma_50": 65000.0,
        "sma_150": 60000.0, "sma_200": 55000.0,
        "w52_high": 80000.0, "w52_low": 50000.0,
        "pct_from_52w_high": -12.5, "pct_from_52w_low": 40.0,
        "rs_line": 0.0040, "rs_line_52w_high": 0.0050, "rs_line_52w_high_date": date(2026, 1, 15),
        "rs_line_at_52w_high": False,
        "rs_line_uptrend_6w": True, "rs_line_uptrend_13w": True,
        "rs_line_not_declining_7m": False,
        "minervini_c1": True, "minervini_c2": True, "minervini_c3": True,
        "minervini_c4": True, "minervini_c5": True, "minervini_c6": True,
        "minervini_c7": True,
    }]
    affected = upsert_daily_indicators_phase_a(db, rows)
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT adj_close, sma_50, minervini_c1, rs_rating FROM daily_indicators WHERE ticker='005930' AND date='2026-05-15'")
        row = cur.fetchone()
    assert row[0] == 70000.0
    assert row[1] == 65000.0
    assert row[2] == True
    assert row[3] is None   # rs_rating 은 Phase B 에서


def test_upsert_phase_a_updates_on_conflict(db):
    _seed_stock(db)
    rows_v1 = [{
        "ticker": "005930", "date": date(2026, 5, 15), "adj_close": 70000.0,
        "sma_10": None, "sma_21": None, "sma_50": None, "sma_150": None, "sma_200": None,
        "w52_high": None, "w52_low": None, "pct_from_52w_high": None, "pct_from_52w_low": None,
        "rs_line": None, "rs_line_52w_high": None, "rs_line_52w_high_date": None,
        "rs_line_at_52w_high": None, "rs_line_uptrend_6w": None, "rs_line_uptrend_13w": None,
        "rs_line_not_declining_7m": None,
        "minervini_c1": None, "minervini_c2": None, "minervini_c3": None,
        "minervini_c4": None, "minervini_c5": None, "minervini_c6": None, "minervini_c7": None,
    }]
    upsert_daily_indicators_phase_a(db, rows_v1)

    rows_v2 = [dict(rows_v1[0], adj_close=71000.0, sma_50=65000.0)]
    upsert_daily_indicators_phase_a(db, rows_v2)

    with db.cursor() as cur:
        cur.execute("SELECT adj_close, sma_50 FROM daily_indicators WHERE ticker='005930'")
        assert cur.fetchone() == (71000.0, 65000.0)


def test_update_rs_rating_sets_value(db):
    _seed_stock(db)
    rows = [dict(
        ticker="005930", date=date(2026, 5, 15), adj_close=70000.0,
        sma_10=None, sma_21=None, sma_50=None, sma_150=None, sma_200=None,
        w52_high=None, w52_low=None, pct_from_52w_high=None, pct_from_52w_low=None,
        rs_line=None, rs_line_52w_high=None, rs_line_52w_high_date=None,
        rs_line_at_52w_high=None, rs_line_uptrend_6w=None, rs_line_uptrend_13w=None,
        rs_line_not_declining_7m=None,
        minervini_c1=None, minervini_c2=None, minervini_c3=None,
        minervini_c4=None, minervini_c5=None, minervini_c6=None, minervini_c7=None,
    )]
    upsert_daily_indicators_phase_a(db, rows)

    affected = update_daily_indicators_rs_rating(db, [("005930", date(2026, 5, 15), 85)])
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT rs_rating FROM daily_indicators WHERE ticker='005930'")
        assert cur.fetchone() == (85,)


def test_update_minervini_pass_uses_sql(db):
    """SQL UPDATE 가 minervini_c8 와 pass 를 계산하는지."""
    _seed_stock(db)
    # 모든 c1-c7 True, rs_rating 85 시드
    rows = [dict(
        ticker="005930", date=date(2026, 5, 15), adj_close=70000.0,
        sma_10=None, sma_21=None, sma_50=65000.0, sma_150=60000.0, sma_200=55000.0,
        w52_high=80000.0, w52_low=50000.0, pct_from_52w_high=-12.5, pct_from_52w_low=40.0,
        rs_line=None, rs_line_52w_high=None, rs_line_52w_high_date=None,
        rs_line_at_52w_high=None, rs_line_uptrend_6w=None, rs_line_uptrend_13w=None,
        rs_line_not_declining_7m=None,
        minervini_c1=True, minervini_c2=True, minervini_c3=True,
        minervini_c4=True, minervini_c5=True, minervini_c6=True, minervini_c7=True,
    )]
    upsert_daily_indicators_phase_a(db, rows)
    update_daily_indicators_rs_rating(db, [("005930", date(2026, 5, 15), 85)])

    affected = update_daily_indicators_minervini_pass(db, date(2026, 5, 15), date(2026, 5, 15))
    assert affected == 1

    with db.cursor() as cur:
        cur.execute("SELECT minervini_c8, minervini_pass FROM daily_indicators WHERE ticker='005930'")
        c8, pass_ = cur.fetchone()
    assert c8 == True       # rs_rating 85 >= 70
    assert pass_ == True    # 8 모두 True


def test_minervini_pass_false_when_any_condition_false(db):
    """c1-c7 중 하나라도 False 면 pass=False"""
    _seed_stock(db)
    rows = [dict(
        ticker="005930", date=date(2026, 5, 15), adj_close=70000.0,
        sma_10=None, sma_21=None, sma_50=None, sma_150=None, sma_200=None,
        w52_high=None, w52_low=None, pct_from_52w_high=None, pct_from_52w_low=None,
        rs_line=None, rs_line_52w_high=None, rs_line_52w_high_date=None,
        rs_line_at_52w_high=None, rs_line_uptrend_6w=None, rs_line_uptrend_13w=None,
        rs_line_not_declining_7m=None,
        minervini_c1=False, minervini_c2=True, minervini_c3=True,
        minervini_c4=True, minervini_c5=True, minervini_c6=True, minervini_c7=True,
    )]
    upsert_daily_indicators_phase_a(db, rows)
    update_daily_indicators_rs_rating(db, [("005930", date(2026, 5, 15), 85)])
    update_daily_indicators_minervini_pass(db, date(2026, 5, 15), date(2026, 5, 15))

    with db.cursor() as cur:
        cur.execute("SELECT minervini_pass FROM daily_indicators WHERE ticker='005930'")
        assert cur.fetchone() == (False,)


def test_mirror_gate_null_when_no_weekly_row(db):
    from kr_pipeline.indicators.store import update_daily_rs_gate_from_weekly
    from datetime import date
    _seed_stock(db, "005930")
    with db.cursor() as cur:
        # daily row exists but NO weekly row on or before its date
        cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close) VALUES ('005930','2026-06-03',100)")
    update_daily_rs_gate_from_weekly(db, date(2026, 6, 1), date(2026, 6, 4))
    with db.cursor() as cur:
        cur.execute("SELECT rs_line_not_declining_7m FROM daily_indicators WHERE ticker='005930' AND date='2026-06-03'")
        # 매칭되는 weekly 행 없음 → NULL (후보 쿼리 = TRUE 게이트에서 제외됨)
        assert cur.fetchone()[0] is None


def test_mirror_gate_picks_latest_week_le_date(db):
    from kr_pipeline.indicators.store import update_daily_rs_gate_from_weekly
    _seed_stock(db, "005930")
    with db.cursor() as cur:
        cur.execute("INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, rs_line_not_declining_7m) "
                    "VALUES ('005930','2026-05-29',100,TRUE),('005930','2026-06-05',100,FALSE)")
        cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close) VALUES ('005930','2026-06-03',100)")
    update_daily_rs_gate_from_weekly(db, date(2026, 6, 1), date(2026, 6, 4))
    with db.cursor() as cur:
        cur.execute("SELECT rs_line_not_declining_7m FROM daily_indicators WHERE ticker='005930' AND date='2026-06-03'")
        # 2026-06-03 은 06-05 이전 → 최신 week_end ≤ date 는 05-29 → TRUE
        assert cur.fetchone()[0] is True


def test_delete_weekly_indicators_orphans(db):
    """weekly_prices 에서 사라진 키의 weekly_indicators 행 삭제 (불변식:
    weekly_indicators ⊆ weekly_prices 키).

    production 사고 후속: weekly_prices 고아(부분집계 키)는 자가치유로 삭제됐지만
    indicators full-refresh 는 upsert 만 해 하류 weekly_indicators 에 597행 잔존."""
    from datetime import date
    from kr_pipeline.indicators.store import delete_weekly_indicators_orphans

    t = "WIORPH"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        # 소스(weekly_prices)에는 금요일 행만 존재
        cur.execute(
            """INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close,
                   adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, trading_days)
               VALUES (%s, '2026-06-05', 100,110,95,105, 105.0,110.0,95.0,100.0,1000.0,1000,1,4)""",
            (t,),
        )
        # indicators 에는 금요일(정상) + 화요일(소스 삭제된 고아) 두 행
        cur.execute(
            "INSERT INTO weekly_indicators (ticker, week_end_date, adj_close) VALUES (%s,'2026-06-05',105.0), (%s,'2026-06-02',105.0)",
            (t, t),
        )
    db.commit()

    deleted = delete_weekly_indicators_orphans(db)

    with db.cursor() as cur:
        cur.execute("SELECT week_end_date FROM weekly_indicators WHERE ticker=%s ORDER BY week_end_date", (t,))
        rows = [r[0] for r in cur.fetchall()]
        cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
    db.commit()
    assert deleted >= 1
    assert rows == [date(2026, 6, 5)], f"고아 잔존: {rows}"
