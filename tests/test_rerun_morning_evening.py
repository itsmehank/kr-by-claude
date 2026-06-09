from datetime import date, datetime, timezone


def test_two_as_of_entry_params_independent(db):
    """as_of=D-1 / as_of=D 의 entry_params 후보가 서로 skip 하지 않고 독립."""
    from kr_pipeline.llm_runner.entry_params import _fetch_go_now_candidates
    d_prev, d_cur = date(2099, 6, 6), date(2099, 6, 8)   # sentinel 미래 — 오염/실데이터 격리
    ev_prev = datetime(2099, 6, 6, 23, 0, tzinfo=timezone.utc)
    ev_cur = datetime(2099, 6, 8, 9, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        for sym, ev in [("MEV1", ev_prev), ("MEV1", ev_cur)]:
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING", (sym,))
            cur.execute("INSERT INTO weekly_classification (symbol,classified_at,market,classification,source) "
                        "VALUES (%s,%s,'KOSPI','entry','test') ON CONFLICT DO NOTHING", (sym, ev))
        cur.execute("INSERT INTO trigger_evaluation_log "
                    "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
                    "VALUES ('MEV1',%s,'breakout','go_now',%s,%s) ON CONFLICT DO NOTHING", (ev_prev, ev_prev, d_prev))
        cur.execute("INSERT INTO trigger_evaluation_log "
                    "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
                    "VALUES ('MEV1',%s,'breakout','go_now',%s,%s) ON CONFLICT DO NOTHING", (ev_cur, ev_cur, d_cur))
        # 오전(D-1) 분은 이미 entry_params 처리됨
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date,"
                    "trigger_evaluation_at,prior_classification_at) "
                    "VALUES ('MEV1',%s,100,92,%s,%s,%s) ON CONFLICT DO NOTHING", (ev_prev, d_prev, ev_prev, ev_prev))
    # 오후(D) 후보: D-1 이 done 이어도 D 는 여전히 후보(독립)
    assert "MEV1" in {r[0] for r in _fetch_go_now_candidates(db, d_cur)}
    # 오전(D-1) 재실행: 이미 done 이라 skip
    assert "MEV1" not in {r[0] for r in _fetch_go_now_candidates(db, d_prev)}
