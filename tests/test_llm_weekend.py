"""주말 (5) batch — 결정론 통과 종목 분류."""
import json
from datetime import date, datetime, timedelta, timezone


def test_weekend_batch_dry_run_creates_classifications(db, mocker):
    """dry-run 모드에서 결정론 통과 종목 3개 → 3 row INSERT."""
    today = date(2026, 5, 16)
    with db.cursor() as cur:
        for t in ["WK1", "WK2", "WK3"]:
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
                (t, t),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, minervini_pass)
                   VALUES (%s, %s, 100, TRUE) ON CONFLICT DO NOTHING""",
                (t, today),
            )
    db.commit()

    # build_analysis_zip mock 처리 (실제 ZIP 생성은 chart_render Decimal 이슈 회피)
    mocker.patch(
        "kr_pipeline.llm_runner.weekend.build_analysis_zip",
        return_value=b"fake_zip_bytes",
    )

    from kr_pipeline.llm_runner.weekend import run

    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM weekly_classification WHERE source='weekend' AND symbol = ANY(%s)",
            (["WK1", "WK2", "WK3"],),
        )
        before = cur.fetchone()[0]

    result = run(db, dry_run=True, as_of=today)

    assert result["processed"] == 3
    assert result["failures"] == 0

    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM weekly_classification WHERE source='weekend' AND symbol = ANY(%s)",
            (["WK1", "WK2", "WK3"],),
        )
        after = cur.fetchone()[0]

    assert after - before == 3


def _seed_run(db, *, status, heartbeat_age_s=None, started_age_s=0):
    """started_age_s 만큼 과거의 started_at + (선택) heartbeat_at 을 가진 llm_weekend 행 삽입."""
    with db.cursor() as cur:
        details = None
        if heartbeat_age_s is not None:
            hb = (datetime.now(timezone.utc) - timedelta(seconds=heartbeat_age_s)).isoformat()
            details = json.dumps({"heartbeat_at": hb})
        cur.execute(
            "INSERT INTO pipeline_runs (pipeline, mode, started_at, status, details) "
            "VALUES ('llm_weekend','weekend', NOW() - make_interval(secs => %s), %s, %s::jsonb) RETURNING id",
            (started_age_s, status, details),
        )
        return cur.fetchone()[0]


def test_reaper_marks_stale_running_failed(db):
    from kr_pipeline.llm_runner.weekend import reap_stale_weekend_runs
    stale = _seed_run(db, status="running", heartbeat_age_s=200)            # hb > 90s
    fresh = _seed_run(db, status="running", heartbeat_age_s=10)             # hb 최근
    nohb_old = _seed_run(db, status="running", heartbeat_age_s=None, started_age_s=200)  # hb 없음 + started 오래됨(disqualify 중 kill -9)
    nohb_new = _seed_run(db, status="running", heartbeat_age_s=None, started_age_s=5)    # hb 없음 + 방금 시작
    current = _seed_run(db, status="running", heartbeat_age_s=200)          # 현재 실행(제외 대상)
    db.commit()

    reap_stale_weekend_runs(db, current_run_id=current, stale_seconds=90)
    db.commit()

    def status_of(rid):
        with db.cursor() as cur:
            cur.execute("SELECT status FROM pipeline_runs WHERE id=%s", (rid,))
            return cur.fetchone()[0]
    assert status_of(stale) == "failed"
    assert status_of(nohb_old) == "failed"
    assert status_of(fresh) == "running"
    assert status_of(nohb_new) == "running"
    assert status_of(current) == "running"

    with db.cursor() as cur:
        cur.execute("DELETE FROM pipeline_runs WHERE id = ANY(%s)", ([stale, fresh, nohb_old, nohb_new, current],))
    db.commit()
