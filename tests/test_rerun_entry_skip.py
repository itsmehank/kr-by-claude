from datetime import date, datetime, timezone


def _seed_trigger(cur, symbol, eval_at, afd):
    cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING", (symbol,))
    cur.execute("INSERT INTO weekly_classification (symbol,classified_at,market,classification,source) "
                "VALUES (%s,%s,'KOSPI','entry','test') ON CONFLICT DO NOTHING", (symbol, eval_at))
    cur.execute("INSERT INTO trigger_evaluation_log "
                "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
                "VALUES (%s,%s,'breakout','go_now',%s,%s) ON CONFLICT DO NOTHING",
                (symbol, eval_at, eval_at, afd))

def test_fetch_excludes_already_entry_and_isolates_as_of(db):
    from kr_pipeline.llm_runner.entry_params import _fetch_go_now_candidates
    as_of = date(2026, 6, 8)
    ev = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_trigger(cur, "ESK_DONE", ev, as_of)
        _seed_trigger(cur, "ESK_TODO", ev, as_of)
        _seed_trigger(cur, "ESK_OTHER", ev, date(2026, 6, 9))
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,trigger_evaluation_at,prior_classification_at,analyzed_for_date) "
                    "VALUES ('ESK_DONE',%s,100,92,%s,%s,%s) ON CONFLICT DO NOTHING", (ev, ev, ev, as_of))
    db.commit()
    got = {r[0] for r in _fetch_go_now_candidates(db, as_of)}
    assert "ESK_TODO" in got
    assert "ESK_DONE" not in got
    assert "ESK_OTHER" not in got

def test_force_deletes_entry_params_for_as_of(db):
    from kr_pipeline.llm_runner import entry_params
    as_of = date(2099, 1, 15)  # sentinel: 트리거 행 없음 → force fetch 비어 LLM 미호출
    ev = datetime(2099, 1, 15, 1, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('EFD1','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date,"
                    "trigger_evaluation_at,prior_classification_at) "
                    "VALUES ('EFD1',%s,100,92,%s,%s,%s) ON CONFLICT DO NOTHING", (ev, as_of, ev, ev))
    db.commit()
    entry_params.run(db, dry_run=False, as_of=as_of, force=True)
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM entry_params WHERE symbol='EFD1'")
        assert cur.fetchone()[0] == 0
