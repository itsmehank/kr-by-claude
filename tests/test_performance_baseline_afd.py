from datetime import date, datetime, timezone


def test_baseline_uses_analyzed_for_date(db):
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 3, 2)                                   # 데이터 날짜 = 기준일이어야 함
    sig = datetime(2099, 3, 3, 1, 0, tzinfo=timezone.utc)    # 실행 시각(기준 아님)
    as_of = date(2099, 3, 20)
    with db.cursor() as cur:
        cur.execute("DELETE FROM signal_performance WHERE symbol='PB1'")
        cur.execute("DELETE FROM entry_params WHERE symbol='PB1'")
        cur.execute("DELETE FROM daily_prices WHERE ticker='PB1'")
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('PB1','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date,"
                    "trigger_evaluation_at,prior_classification_at) "
                    "VALUES ('PB1',%s,100,92,%s,%s,%s) ON CONFLICT DO NOTHING", (sig, afd, sig, sig))
        cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                    "VALUES ('PB1',%s,110,110,110,110,110,1000,1) ON CONFLICT DO NOTHING", (date(2099,3,9),))   # afd+7
        cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                    "VALUES ('PB1',%s,200,200,200,200,200,1000,1) ON CONFLICT DO NOTHING", (date(2099,3,10),))  # signal_at+7 함정
    performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT price_1w, return_1w_pct FROM signal_performance WHERE symbol='PB1' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None
    assert float(row[0]) == 110.0
    assert abs(float(row[1]) - 10.0) < 0.01


def test_baseline_fallback_to_signal_at_when_afd_null(db):
    from kr_pipeline.llm_runner import performance
    sig = datetime(2099, 4, 3, 1, 0, tzinfo=timezone.utc)
    as_of = date(2099, 4, 20)
    with db.cursor() as cur:
        cur.execute("DELETE FROM signal_performance WHERE symbol='PB2'")
        cur.execute("DELETE FROM entry_params WHERE symbol='PB2'")
        cur.execute("DELETE FROM daily_prices WHERE ticker='PB2'")
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('PB2','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,"
                    "trigger_evaluation_at,prior_classification_at) "
                    "VALUES ('PB2',%s,100,92,%s,%s) ON CONFLICT DO NOTHING", (sig, sig, sig))   # analyzed_for_date NULL
        cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                    "VALUES ('PB2',%s,130,130,130,130,130,1000,1) ON CONFLICT DO NOTHING", (date(2099,4,10),))  # signal_at+7
    performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT price_1w, return_1w_pct FROM signal_performance WHERE symbol='PB2' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None and float(row[0]) == 130.0
    assert abs(float(row[1]) - 30.0) < 0.01


def test_late_kst_legacy_signal_window_matches_utc_baseline(db):
    """늦은 KST(=UTC 전날) signal, analyzed_for_date NULL — 윈도(SQL)와 기준일(Python)이 UTC로 일치해야 함."""
    from kr_pipeline.llm_runner import performance
    # 2099-05-10 15:30 UTC = 2099-05-11 00:30 KST → UTC date 05-10 ≠ KST date 05-11. 기준일은 UTC(05-10), +7 = 05-17.
    sig = datetime(2099, 5, 10, 15, 30, tzinfo=timezone.utc)
    as_of = date(2099, 5, 25)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('PB3','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM signal_performance WHERE symbol='PB3'")
        cur.execute("DELETE FROM entry_params WHERE symbol='PB3'")
        cur.execute("DELETE FROM daily_prices WHERE ticker='PB3'")
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,"
                    "trigger_evaluation_at,prior_classification_at) "
                    "VALUES ('PB3',%s,100,92,%s,%s) ON CONFLICT DO NOTHING", (sig, sig, sig))
        # UTC 기준 1주 후 = 05-17 에 가격 140
        cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                    "VALUES ('PB3',%s,140,140,140,140,140,1000,1) ON CONFLICT DO NOTHING", (date(2099,5,17),))
    performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT price_1w FROM signal_performance WHERE symbol='PB3' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None and float(row[0]) == 140.0   # UTC baseline 05-10 +7 = 05-17
