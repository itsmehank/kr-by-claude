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


def test_run_tracking_persists_rows_affected_and_warnings(db):
    """run_tracking 종료 시 state['rows_affected'] 와 state['warnings'] 가 DB 에 기록되어야 함."""
    from kr_pipeline.db.runs import run_tracking

    with run_tracking(db, pipeline="test", mode="x", params={}) as state:
        state["rows_affected"] = 42
        state["warnings"].append("coverage_low: example")

    with db.cursor() as cur:
        cur.execute("""
            SELECT status, rows_affected, error FROM pipeline_runs
             WHERE pipeline = 'test' AND mode = 'x' ORDER BY id DESC LIMIT 1
        """)
        status, rows_affected, error = cur.fetchone()
    assert status == "success"
    assert rows_affected == 42
    assert "coverage_low" in (error or "")

    # cleanup
    with db.cursor() as cur:
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'test'")
    db.commit()


def test_run_tracking_rows_affected_defaults_to_null(db):
    """rows_affected 를 안 세팅하면 NULL 로 유지."""
    from kr_pipeline.db.runs import run_tracking

    with run_tracking(db, pipeline="test", mode="y", params={}) as state:
        pass  # don't set rows_affected

    with db.cursor() as cur:
        cur.execute("SELECT rows_affected FROM pipeline_runs WHERE pipeline = 'test' AND mode = 'y' ORDER BY id DESC LIMIT 1")
        result = cur.fetchone()[0]
    assert result is None

    with db.cursor() as cur:
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline = 'test'")
    db.commit()
