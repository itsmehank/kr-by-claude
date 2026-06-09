from datetime import date, datetime, timezone


def test_force_deletes_trigger_log_for_as_of(db):
    from kr_pipeline.llm_runner import evaluate_pivot
    as_of = date(2099, 1, 10)
    ev = datetime(2099, 1, 10, 1, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('EVF1','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO trigger_evaluation_log "
                    "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
                    "VALUES ('EVF1',%s,'breakout','wait',%s,%s) ON CONFLICT DO NOTHING", (ev, ev, as_of))
    db.commit()
    evaluate_pivot.run(db, dry_run=False, as_of=as_of, force=True)
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM trigger_evaluation_log WHERE symbol='EVF1'")
        assert cur.fetchone()[0] == 0


def test_already_evaluated_symbols_for_as_of(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _already_evaluated_symbols
    # sentinel future date so no existing DB rows can pollute
    as_of = date(2099, 1, 8)
    ev = datetime(2099, 1, 8, 1, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('EVS1','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO trigger_evaluation_log "
                    "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
                    "VALUES ('EVS1',%s,'breakout','wait',%s,%s) ON CONFLICT DO NOTHING", (ev, ev, as_of))
    db.commit()
    assert _already_evaluated_symbols(db, as_of) == {"EVS1"}
    assert _already_evaluated_symbols(db, date(2099, 1, 9)) == set()
