"""주말 (5) batch — 결정론 통과 종목 분류."""
import json
from datetime import date, datetime, timedelta, timezone


def test_weekend_batch_dry_run_processes_all_qualifying(db, mocker):
    """dry-run + 병렬: rs_line·minervini 통과 3종목이 모두 처리(processed==3).
    (dry_run 은 분류 row 를 insert 하지 않고 freeze 만 저장 — _process_one 설계.)

    sentinel 미래 날짜(2099-01-01)를 써서 격리: get_qualifying_tickers 는
    MAX(date<=as_of) 의 자격종목을 반환하므로, 다른 테스트가 현실 날짜에 커밋한
    자격종목(공유 kr_test 오염)이 후보에 섞이지 않게 한다 → 후보 = WK1-3 결정적.
    실제 필터(minervini_pass AND rs_line_not_declining_7m)는 그대로 탄다."""
    today = date(2099, 1, 1)
    tickers = ["WK1", "WK2", "WK3"]
    with db.cursor() as cur:
        for t in tickers:
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

    with db.cursor() as cur:                              # cleanup (sentinel 날짜 행 정리)
        cur.execute("DELETE FROM daily_indicators WHERE date=%s AND ticker = ANY(%s)", (today, tickers))
    db.commit()


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


def test_weekend_worker_connect_failure_does_not_abort(db, mocker):
    """워커 connect 실패는 배치 전체를 중단시키지 않고 종목별 실패로 흡수돼야 한다."""
    import kr_pipeline.llm_runner.weekend as wk
    mocker.patch.object(wk, "get_qualifying_tickers", return_value=[
        {"symbol": "C1", "market": "KOSPI"},
        {"symbol": "C2", "market": "KOSPI"},
    ])
    # 워커가 여는 psycopg.connect 만 실패시킨다(run_id=None → 하트비트/리퍼 connect 없음).
    mocker.patch.object(wk.psycopg, "connect", side_effect=OSError("no conn"))

    r = wk.run(db, dry_run=True, concurrency=2, run_id=None)

    assert r["processed"] == 0
    assert r["failures"] == 2
    assert {f["symbol"] for f in r["failed_tickers"]} == {"C1", "C2"}
    assert all("connect failed" in f["error"] and f["attempts"] == 0 for f in r["failed_tickers"])


def test_weekend_writes_heartbeat_progress(db, mocker):
    import kr_pipeline.llm_runner.weekend as wk
    with db.cursor() as cur:
        cur.execute("INSERT INTO pipeline_runs (pipeline, mode, started_at, status) "
                    "VALUES ('llm_weekend','weekend',NOW(),'running') RETURNING id")
        run_id = cur.fetchone()[0]
    db.commit()

    mocker.patch.object(wk, "get_qualifying_tickers", return_value=[{"symbol": "AAAA", "market": "KOSPI"}])
    mocker.patch.object(wk, "_process_one", side_effect=lambda *a, **k: None)

    wk.run(db, dry_run=True, concurrency=1, run_id=run_id)

    with db.cursor() as cur:
        cur.execute("SELECT details FROM pipeline_runs WHERE id=%s", (run_id,))
        details = cur.fetchone()[0]
    assert details is not None
    assert details.get("heartbeat_at")
    assert details.get("weekend_progress", {}).get("total") == 1

    with db.cursor() as cur:
        cur.execute("DELETE FROM pipeline_runs WHERE id=%s", (run_id,))
    db.commit()


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


def test_weekend_zip_excludes_prior_analysis_and_pins_as_of(db, mocker):
    """신규 분석 ZIP 에 직전 분류(analysis_result.json)가 혼입되면 안 되고(anchoring),
    --date 과거 재실행 시 미래 데이터가 새지 않도록 on_date=as_of 를 고정해야 한다."""
    import kr_pipeline.llm_runner.weekend as wk
    zip_mock = mocker.patch.object(wk, "build_analysis_zip", return_value=b"fake_zip")
    mocker.patch.object(wk, "save_freeze")

    as_of = date(2025, 6, 10)
    wk._process_one(db, "WKZC1", "KOSPI", dry_run=True, as_of=as_of)

    _, kwargs = zip_mock.call_args
    assert kwargs.get("include_prior_analysis") is False
    assert kwargs.get("on_date") == as_of


def test_weekend_aborts_batch_on_usage_limit(db, mocker):
    """사용량 제한이 감지되면 남은 후보를 헛돌지 않고 배치 즉시 중단 +
    예외 전파(run_tracking 이 failed 로 기록 → 같은 as_of 재실행이 force 없이 가능)."""
    import pytest
    import kr_pipeline.llm_runner.weekend as wk
    from kr_pipeline.llm_runner.llm.claude_cli import UsageLimitError

    mocker.patch.object(wk, "get_qualifying_tickers", return_value=[
        {"symbol": "UL1", "market": "KOSPI"},
        {"symbol": "UL2", "market": "KOSPI"},
        {"symbol": "UL3", "market": "KOSPI"},
    ])
    calls = []
    def fake_process_one(conn, symbol, market, *, dry_run, as_of):
        calls.append(symbol)
        raise UsageLimitError("usage limit reached")
    mocker.patch.object(wk, "_process_one", side_effect=fake_process_one)

    with pytest.raises(UsageLimitError):
        wk.run(db, dry_run=True, concurrency=1, run_id=None)

    assert len(calls) == 1, f"제한 감지 후에도 추가 호출: {calls}"


def test_weekend_skips_already_classified_same_as_of(db, mocker):
    """같은 analyzed_for_date 에 이미 분류·적재된 종목은 재실행 시 LLM 호출 없이 skip —
    사용량 제한 등으로 중단된 배치를 재실행하면 '이어하기'가 되어야 한다 (backfill 과 동일 패턴)."""
    import kr_pipeline.llm_runner.weekend as wk

    as_of = date(2099, 2, 6)  # sentinel 미래 날짜 (격리)
    with db.cursor() as cur:
        for t in ("SKP1", "SKP2"):
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING", (t, t))
        # SKP1 은 이미 같은 as_of 로 분류 완료
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source)
               VALUES ('SKP1', NOW(), %s, 'KOSPI', 'watch', 'weekend')""",
            (as_of,),
        )
    db.commit()

    mocker.patch.object(wk, "get_qualifying_tickers", return_value=[
        {"symbol": "SKP1", "market": "KOSPI"},
        {"symbol": "SKP2", "market": "KOSPI"},
    ])
    calls = []
    def fake_process_one(conn, symbol, market, *, dry_run, as_of):
        calls.append(symbol)
    mocker.patch.object(wk, "_process_one", side_effect=fake_process_one)

    try:
        r = wk.run(db, dry_run=True, as_of=as_of, concurrency=1, run_id=None)
        assert calls == ["SKP2"], f"기적재 SKP1 이 다시 호출됨: {calls}"
        assert r["skipped_existing"] == 1
        assert r["processed"] == 1
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol IN ('SKP1','SKP2') AND analyzed_for_date=%s", (as_of,))
        db.commit()
