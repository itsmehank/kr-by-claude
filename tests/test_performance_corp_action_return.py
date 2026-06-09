from datetime import date, datetime, timezone


def _seed(cur, ticker, sig, afd, sig_close, sig_adj, target_date, target_adj):
    cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING", (ticker,))
    cur.execute("DELETE FROM entry_params WHERE symbol=%s", (ticker,))
    cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date,"
                "trigger_evaluation_at,prior_classification_at) "
                "VALUES (%s,%s,100,92,%s,%s,%s) ON CONFLICT DO NOTHING", (ticker, sig, afd, sig, sig))
    cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,1000,1) ON CONFLICT DO NOTHING",
                (ticker, afd, sig_close, sig_close, sig_close, sig_close, sig_adj))
    cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,1000,1) ON CONFLICT DO NOTHING",
                (ticker, target_date, target_adj, target_adj, target_adj, target_adj, target_adj))


def test_split_adjusts_entry_denominator(db):
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 3, 2); sig = datetime(2099, 3, 2, 5, 0, tzinfo=timezone.utc); as_of = date(2099, 3, 20)
    with db.cursor() as cur:
        _seed(cur, "CAR1", sig, afd, sig_close=100, sig_adj=50, target_date=date(2099,3,9), target_adj=60)
    performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT entry_price, return_1w_pct FROM signal_performance WHERE symbol='CAR1' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None
    assert abs(float(row[0]) - 50.0) < 0.01
    assert abs(float(row[1]) - 20.0) < 0.01


def test_no_adjustment_unchanged(db):
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 4, 2); sig = datetime(2099, 4, 2, 5, 0, tzinfo=timezone.utc); as_of = date(2099, 4, 20)
    with db.cursor() as cur:
        _seed(cur, "CAR2", sig, afd, sig_close=100, sig_adj=100, target_date=date(2099,4,9), target_adj=110)
    performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT entry_price, return_1w_pct FROM signal_performance WHERE symbol='CAR2' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None
    assert abs(float(row[0]) - 100.0) < 0.01
    assert abs(float(row[1]) - 10.0) < 0.01


def test_zero_adj_close_falls_back_to_raw_no_crash(db):
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 5, 2); sig = datetime(2099, 5, 2, 5, 0, tzinfo=timezone.utc); as_of = date(2099, 5, 20)
    with db.cursor() as cur:
        _seed(cur, "CAR3", sig, afd, sig_close=100, sig_adj=0, target_date=date(2099,5,9), target_adj=110)
    performance.run(db, as_of=as_of)   # must not raise
    with db.cursor() as cur:
        cur.execute("SELECT entry_price, return_1w_pct FROM signal_performance WHERE symbol='CAR3' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None
    assert abs(float(row[0]) - 100.0) < 0.01    # fallback raw entry
    assert abs(float(row[1]) - 10.0) < 0.01     # (110-100)/100
