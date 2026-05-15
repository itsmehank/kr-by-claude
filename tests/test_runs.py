import json
from kr_pipeline.db.runs import start_run, finish_run


def test_start_and_finish_success(db):
    run_id = start_run(db, pipeline="ohlcv", mode="incremental", params={"window_days": 30})
    finish_run(db, run_id, status="success", rows_affected=1234)

    with db.cursor() as cur:
        cur.execute("SELECT pipeline, mode, status, rows_affected, params FROM pipeline_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    assert row[0] == "ohlcv"
    assert row[1] == "incremental"
    assert row[2] == "success"
    assert row[3] == 1234
    assert row[4] == {"window_days": 30}


def test_finish_with_error(db):
    run_id = start_run(db, pipeline="ohlcv", mode="backfill", params={})
    finish_run(db, run_id, status="failed", error="boom")

    with db.cursor() as cur:
        cur.execute("SELECT status, error FROM pipeline_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    assert row == ("failed", "boom")
