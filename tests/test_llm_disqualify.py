from datetime import date, datetime, timezone

AS_OF = date(2026, 6, 2)


def _seed(cur, ticker, classification, minervini_pass):
    cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
                (ticker, ticker))
    cur.execute("""INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass)
                   VALUES (%s, %s, 100, %s) ON CONFLICT DO NOTHING""", (ticker, AS_OF, minervini_pass))
    cur.execute("""INSERT INTO weekly_classification (symbol, classified_at, market, classification, source)
                   VALUES (%s, %s, 'KOSPI', %s, 'weekend')""",
                (ticker, datetime(2026, 5, 30, tzinfo=timezone.utc), classification))


def test_get_classified_losing_minervini(db):
    from kr_pipeline.llm_runner.load import get_classified_losing_minervini
    with db.cursor() as cur:
        for t in ("LOSE_W", "LOSE_E", "LOSE_I", "KEEP_W", "ALREADY_DQ"):
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        _seed(cur, "LOSE_W", "watch", False)
        _seed(cur, "LOSE_E", "entry", False)
        _seed(cur, "LOSE_I", "ignore", False)
        _seed(cur, "KEEP_W", "watch", True)
        _seed(cur, "ALREADY_DQ", "disqualified", False)
    db.commit()
    losers = {x["symbol"] for x in get_classified_losing_minervini(db, AS_OF)}
    assert losers >= {"LOSE_W", "LOSE_E", "LOSE_I"}
    assert "KEEP_W" not in losers
    assert "ALREADY_DQ" not in losers
