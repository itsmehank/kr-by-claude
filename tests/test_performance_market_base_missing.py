from datetime import date, datetime, timezone


def _seed_signal(cur, ticker, sig, afd, price_date, price=110.0):
    cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING", (ticker,))
    cur.execute("DELETE FROM entry_params WHERE symbol=%s", (ticker,))
    cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date,"
                "trigger_evaluation_at,prior_classification_at) "
                "VALUES (%s,%s,100,92,%s,%s,%s) ON CONFLICT DO NOTHING", (ticker, sig, afd, sig, sig))
    cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,1000,1) ON CONFLICT DO NOTHING",
                (ticker, price_date, price, price, price, price, price))


def test_missing_market_base_is_reported_not_silent(db):
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 6, 1)
    sig = datetime(2099, 6, 1, 5, 0, tzinfo=timezone.utc)
    as_of = date(2099, 6, 20)
    with db.cursor() as cur:
        cur.execute("DELETE FROM index_daily WHERE index_code='1001' AND date IN ('2099-06-01','2099-06-08')")
        _seed_signal(cur, "MBM1", sig, afd, date(2099, 6, 8))
    res = performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT price_1w, return_1w_pct, market_return_1w_pct FROM signal_performance WHERE symbol='MBM1' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None
    assert float(row[0]) == 110.0
    assert abs(float(row[1]) - 10.0) < 0.01
    assert row[2] is None
    assert "MBM1" in {m["symbol"] for m in res.get("market_base_missing", [])}


def test_market_base_present_computes_and_no_report(db):
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 7, 1)
    sig = datetime(2099, 7, 1, 5, 0, tzinfo=timezone.utc)
    as_of = date(2099, 7, 20)
    with db.cursor() as cur:
        _seed_signal(cur, "MBM2", sig, afd, date(2099, 7, 8), price=120.0)
        for d, c in [(date(2099,7,1), 1000.0), (date(2099,7,8), 1100.0)]:
            cur.execute("INSERT INTO index_daily (index_code,date,open,high,low,close) "
                        "VALUES ('1001',%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (d, c, c, c, c))
    res = performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT market_return_1w_pct FROM signal_performance WHERE symbol='MBM2' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None and row[0] is not None
    assert abs(float(row[0]) - 10.0) < 0.01
    assert "MBM2" not in {m["symbol"] for m in res.get("market_base_missing", [])}
