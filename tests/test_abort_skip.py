from datetime import date, datetime, timezone


def _seed_abort(cur, symbol, prior_at, *, decision="abort", evaluated_at=None):
    cur.execute(
        "INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING",
        (symbol,),
    )
    ev = evaluated_at or datetime(2099, 3, 2, 1, 0, tzinfo=timezone.utc)
    cur.execute(
        "INSERT INTO trigger_evaluation_log "
        "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
        "VALUES (%s,%s,'invalidation',%s,%s,%s) ON CONFLICT DO NOTHING",
        (symbol, ev, decision, prior_at, date(2099, 3, 2)),
    )


def test_abort_against_current_classification_is_skipped(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    cls_at = datetime(2099, 3, 1, 3, 20, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_abort(cur, "ABT1", cls_at)
    active = [{"symbol": "ABT1", "classified_at": cls_at}]
    assert _aborted_since_classification(db, active) == {"ABT1"}


def test_abort_against_old_classification_not_skipped(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    old_cls = datetime(2099, 3, 1, 3, 20, tzinfo=timezone.utc)
    new_cls = datetime(2099, 3, 8, 3, 20, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_abort(cur, "ABT2", old_cls)
    active = [{"symbol": "ABT2", "classified_at": new_cls}]
    assert _aborted_since_classification(db, active) == set()


def test_no_abort_or_wait_only_not_skipped(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    cls_at = datetime(2099, 3, 1, 3, 20, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_abort(cur, "ABT3", cls_at, decision="wait")
    active = [
        {"symbol": "ABT3", "classified_at": cls_at},
        {"symbol": "ABT4", "classified_at": cls_at},
    ]
    assert _aborted_since_classification(db, active) == set()


def test_classified_at_none_does_not_crash(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    cls_at = datetime(2099, 3, 1, 3, 20, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_abort(cur, "ABT5", cls_at)
    active = [{"symbol": "ABT5", "classified_at": None}]
    assert _aborted_since_classification(db, active) == set()


def test_empty_active_returns_empty(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    assert _aborted_since_classification(db, []) == set()


def test_symbol_with_old_and_current_abort_is_skipped(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    old_cls = datetime(2099, 3, 1, 3, 20, tzinfo=timezone.utc)
    cur_cls = datetime(2099, 3, 8, 3, 20, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_abort(cur, "ABT6", old_cls,
                    evaluated_at=datetime(2099, 3, 2, 1, 0, tzinfo=timezone.utc))
        _seed_abort(cur, "ABT6", cur_cls,
                    evaluated_at=datetime(2099, 3, 9, 1, 0, tzinfo=timezone.utc))
    active = [{"symbol": "ABT6", "classified_at": cur_cls}]
    assert _aborted_since_classification(db, active) == {"ABT6"}


def test_run_result_includes_abort_skipped_key(db):
    from kr_pipeline.llm_runner import evaluate_pivot
    # 활성 종목 없는 sentinel 미래 as_of → triggered 0, LLM 미호출
    res = evaluate_pivot.run(db, dry_run=True, as_of=date(2099, 12, 31))
    assert "abort_skipped" in res
    assert res["abort_skipped"] == 0
