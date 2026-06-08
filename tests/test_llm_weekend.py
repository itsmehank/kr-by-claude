"""주말 (5) batch — 결정론 통과 종목 분류."""
import json
from datetime import date, datetime, timedelta, timezone


def test_weekend_batch_dry_run_processes_all_qualifying(db, mocker):
    """dry-run + 병렬: rs_line·minervini 통과 3종목이 모두 처리(processed==3).
    (dry_run 은 분류 row 를 insert 하지 않고 freeze 만 저장 — _process_one 설계.)"""
    today = date(2026, 5, 16)
    with db.cursor() as cur:
        for t in ["WK1", "WK2", "WK3"]:
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING", (t, t))
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass, rs_line_not_declining_7m)
                   VALUES (%s,%s,100,TRUE,TRUE)
                   ON CONFLICT (ticker, date) DO UPDATE SET minervini_pass=TRUE, rs_line_not_declining_7m=TRUE""",
                (t, today),
            )
    db.commit()
    mocker.patch("kr_pipeline.llm_runner.weekend.build_analysis_zip", return_value=b"fake_zip_bytes")

    from kr_pipeline.llm_runner.weekend import run
    result = run(db, dry_run=True, as_of=today, concurrency=3)

    assert result["processed"] == 3
    assert result["failures"] == 0
    assert result["failed_tickers"] == []


def test_weekend_parallel_aggregates_and_retries(db, mocker):
    import kr_pipeline.llm_runner.weekend as wk
    from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError

    mocker.patch.object(wk, "get_qualifying_tickers", return_value=[
        {"symbol": "OKAA", "market": "KOSPI"},
        {"symbol": "TRNS", "market": "KOSPI"},  # 일시오류 1회 후 성공
        {"symbol": "PERM", "market": "KOSPI"},  # 영구 실패
    ])
    calls = {}
    def fake_process_one(conn, symbol, market, *, dry_run, as_of):
        calls[symbol] = calls.get(symbol, 0) + 1
        if symbol == "TRNS" and calls[symbol] == 1:
            raise ClaudeCLIError("transient")          # 1회 일시오류 → 재시도
        if symbol == "PERM":
            raise ValueError("permanent")              # 영구 → 재시도 안 함
        return None
    mocker.patch.object(wk, "_process_one", side_effect=fake_process_one)

    r = wk.run(db, dry_run=True, concurrency=3, run_id=None)

    assert r["processed"] == 2                          # OKAA, TRNS
    assert calls["TRNS"] == 2                           # 재시도 1회
    assert calls["PERM"] == 1                           # 영구는 재시도 안 함
    failed = {f["symbol"]: f for f in r["failed_tickers"]}
    assert "PERM" in failed and failed["PERM"]["attempts"] == 1
    assert "permanent" in failed["PERM"]["error"]


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
