from datetime import datetime, date, timezone


def _result(cls="watch", pivot=100.0):
    return {
        "classification": cls, "pattern": "flat_base", "pivot_price": pivot,
        "pivot_basis": "range_high", "base_high": pivot, "base_low": pivot * 0.9,
        "base_depth_pct": 8.0, "base_start_date": "2025-08-01", "risk_flags": [],
        "confidence": 0.7, "reasoning": "t",
    }


def test_insert_backfill_classification_basic(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKF1','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF1'")
    db.commit()
    insert_backfill_classification(
        db, symbol="BKF1", classified_at=datetime(2026, 6, 3, 1, tzinfo=timezone.utc),
        market="KOSPI", result=_result("watch"), source="backfill",
        llm_meta={"duration_s": 10.0, "input_tokens": 100, "output_tokens": 50},
        analyzed_for_date=date(2025, 9, 30),
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT classification, analyzed_for_date, source FROM classification_backfill WHERE symbol='BKF1'"
            )
            rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "watch"
        assert rows[0][1] == date(2025, 9, 30)
        assert rows[0][2] == "backfill"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF1'")
        db.commit()


def test_backfill_run_inserts_and_wires_on_date(db, monkeypatch):
    import kr_pipeline.llm_runner.backfill as bf
    from datetime import date as _date
    # 토요일, 실데이터 시작(2024-05-17) 이전 → get_qualifying_tickers 가 우리가 심은 종목만 반환(격리).
    sat = _date(2024, 1, 6)  # 토요일
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE analyzed_for_date=%s", (sat,))
        for t in ("BKR1", "BKR2"):
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'B','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s AND date=%s", (t, sat))
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, minervini_pass, rs_line_not_declining_7m, adj_close)
                   VALUES (%s,%s,TRUE,TRUE,1000.0)""",
                (t, sat),
            )
    db.commit()
    seen_on_date = []
    monkeypatch.setattr(bf, "build_analysis_inline",
                        lambda conn, symbol, on_date=None, **kw: (seen_on_date.append(on_date) or ("inline", ["/tmp/_bfpng/daily_chart.png", "/tmp/_bfpng/weekly_chart.png"], b"zip")))
    monkeypatch.setattr(bf, "call_claude",
                        lambda **kwargs: _result("watch"))
    try:
        res = bf.run(db, start=sat, end=sat, dry_run=False)
        assert res["processed"] == 2
        assert res["weeks"] == 1
        assert seen_on_date and all(d == sat for d in seen_on_date)
        with db.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM classification_backfill WHERE analyzed_for_date=%s", (sat,))
            assert cur.fetchone()[0] == 2
        # 재실행 = resume: 이미 된 것 skip
        res2 = bf.run(db, start=sat, end=sat, dry_run=False)
        assert res2["processed"] == 0
        assert res2["skipped_existing"] == 2
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE analyzed_for_date=%s", (sat,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker IN ('BKR1','BKR2') AND date=%s", (sat,))
        db.commit()


def test_insert_backfill_idempotent_on_symbol_analyzed_for_date(db):
    """같은 (symbol, analyzed_for_date) 재삽입 → ON CONFLICT DO NOTHING (1행 유지, 덮어쓰기 안 함)."""
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKF2','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF2'")
    db.commit()
    afd = date(2025, 9, 30)
    insert_backfill_classification(db, symbol="BKF2", classified_at=datetime(2026, 6, 3, 1, tzinfo=timezone.utc),
                                   market="KOSPI", result=_result("watch", 111.0), source="backfill",
                                   llm_meta={"duration_s": 1, "input_tokens": 1, "output_tokens": 1},
                                   analyzed_for_date=afd)
    db.commit()
    insert_backfill_classification(db, symbol="BKF2", classified_at=datetime(2026, 6, 3, 2, tzinfo=timezone.utc),
                                   market="KOSPI", result=_result("ignore", 999.0), source="backfill",
                                   llm_meta={"duration_s": 1, "input_tokens": 1, "output_tokens": 1},
                                   analyzed_for_date=afd)
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT count(*), max(classification) FROM classification_backfill WHERE symbol='BKF2'")
            cnt, cls = cur.fetchone()
        assert cnt == 1
        assert cls == "watch"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF2'")
        db.commit()


def test_backfill_gate_uses_point_in_time_date(db, monkeypatch):
    import kr_pipeline.llm_runner.store as store_mod
    from datetime import datetime, date, timezone
    captured = {}
    def fake_gate(conn, symbol, classified_at, result):
        captured["at"] = classified_at
        return result, None
    monkeypatch.setattr(store_mod, "apply_phase1_gates", fake_gate)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKGATE','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BKGATE'")
    db.commit()
    try:
        store_mod.insert_backfill_classification(
            db, symbol="BKGATE", classified_at=datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
            market="KOSPI", result=_result("watch"), source="backfill",
            llm_meta={"duration_s": 1, "input_tokens": 1, "output_tokens": 1},
            analyzed_for_date=date(2025, 9, 30),
        )
        db.commit()
        assert captured["at"].date() == date(2025, 10, 1)   # as_of + 1 (가격창에 as_of 포함)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKGATE'")
        db.commit()


def _assert_parser_error(argv, expected_fragment):
    import io, contextlib, sys, pytest
    from kr_pipeline.llm_runner.__main__ import main
    buf = io.StringIO()
    saved = sys.argv
    try:
        sys.argv = argv
        with contextlib.redirect_stderr(buf):
            with pytest.raises(SystemExit) as exc_info:
                main()
    finally:
        sys.argv = saved
    assert exc_info.value.code == 2
    assert expected_fragment in buf.getvalue(), f"stderr was: {buf.getvalue()!r}"


def test_backfill_mode_requires_start_end():
    # backfill 에 --start/--end 둘 다 없음
    _assert_parser_error(
        ["prog", "--mode=backfill"],
        "--start and --end are required with --mode=backfill",
    )
    # --start 만 있고 --end 없음
    _assert_parser_error(
        ["prog", "--mode=backfill", "--start=2024-05-01"],
        "--start and --end are required with --mode=backfill",
    )


def test_range_args_rejected_for_non_backfill_modes():
    """--start/--end/--tickers 는 backfill 외 모드와 쓰면 가드 에러."""
    for extra in ("--start=2024-05-01", "--end=2024-05-31", "--tickers=000660"):
        _assert_parser_error(
            ["prog", "--mode=weekend", extra],
            "--start/--end/--tickers/--concurrency is only supported with --mode=backfill",
        )


def test_get_qualifying_tickers_filters_by_tickers(db):
    """tickers 인자 지정 시 그 종목 중 minervini 통과분만, 생략 시 전체."""
    from kr_pipeline.llm_runner.load import get_qualifying_tickers
    from datetime import date as _date
    as_of = _date(2023, 1, 7)  # 실데이터 이전 → 격리
    with db.cursor() as cur:
        for t in ("QF1", "QF2", "QF3"):
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'B','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s AND date=%s", (t, as_of))
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,rs_line_not_declining_7m,adj_close) VALUES ('QF1',%s,TRUE,TRUE,1000.0)", (as_of,))
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,rs_line_not_declining_7m,adj_close) VALUES ('QF2',%s,TRUE,TRUE,1000.0)", (as_of,))
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,adj_close) VALUES ('QF3',%s,FALSE,1000.0)", (as_of,))
    db.commit()
    try:
        got = get_qualifying_tickers(db, as_of=as_of, tickers=["QF1"])
        assert [r["symbol"] for r in got] == ["QF1"]
        assert get_qualifying_tickers(db, as_of=as_of, tickers=["QF3"]) == []
        got2 = get_qualifying_tickers(db, as_of=as_of, tickers=["QF1", "QF2", "QF3"])
        assert sorted(r["symbol"] for r in got2) == ["QF1", "QF2"]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_indicators WHERE ticker IN ('QF1','QF2','QF3') AND date=%s", (as_of,))
        db.commit()


def test_enumerate_saturdays():
    from kr_pipeline.llm_runner.backfill import _enumerate_saturdays
    from datetime import date as _date
    # 2024-05-01(수) ~ 2024-05-31(금) 사이 토요일: 4,11,18,25
    got = _enumerate_saturdays(_date(2024, 5, 1), _date(2024, 5, 31))
    assert got == [_date(2024, 5, 4), _date(2024, 5, 11), _date(2024, 5, 18), _date(2024, 5, 25)]
    # 경계가 토요일이면 포함 (start=end=토요일 → 그 토요일 1개)
    assert _enumerate_saturdays(_date(2024, 5, 4), _date(2024, 5, 4)) == [_date(2024, 5, 4)]
    # 범위 내 토요일 없음 → 빈 리스트 (월~금)
    assert _enumerate_saturdays(_date(2024, 5, 6), _date(2024, 5, 10)) == []
    # start > end → 빈 리스트
    assert _enumerate_saturdays(_date(2024, 5, 31), _date(2024, 5, 1)) == []


def test_backfill_run_multi_week_with_tickers(db, monkeypatch):
    """여러 토요일 × ticker 지정 — 통과한 주만 분류, weeks 집계."""
    import kr_pipeline.llm_runner.backfill as bf
    from datetime import date as _date
    s1, s2 = _date(2024, 1, 6), _date(2024, 1, 13)  # 연속 토요일 2개
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKW1','B','KOSPI') ON CONFLICT DO NOTHING")
        for s in (s1, s2):
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKW1' AND analyzed_for_date=%s", (s,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker='BKW1' AND date=%s", (s,))
        # s1 통과 / s2 미통과 → s2 는 건너뛰어야 함
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,rs_line_not_declining_7m,adj_close) VALUES ('BKW1',%s,TRUE,TRUE,1000.0)", (s1,))
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,adj_close) VALUES ('BKW1',%s,FALSE,1000.0)", (s2,))
    db.commit()
    monkeypatch.setattr(bf, "build_analysis_inline", lambda conn, symbol, on_date=None, **kw: ("inline", ["/tmp/_bfpng/daily_chart.png", "/tmp/_bfpng/weekly_chart.png"], b"zip"))
    monkeypatch.setattr(bf, "call_claude", lambda **kwargs: _result("watch"))
    try:
        res = bf.run(db, start=s1, end=s2, tickers=["BKW1"], dry_run=False)
        assert res["weeks"] == 2          # 토요일 2개 순회
        assert res["processed"] == 1      # s1 만 분류 (s2 미통과 건너뜀)
        with db.cursor() as cur:
            cur.execute("SELECT analyzed_for_date FROM classification_backfill WHERE symbol='BKW1' ORDER BY analyzed_for_date")
            rows = [r[0] for r in cur.fetchall()]
        assert rows == [s1]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKW1'")
            cur.execute("DELETE FROM daily_indicators WHERE ticker='BKW1' AND date IN (%s,%s)", (s1, s2))
        db.commit()


def test_backfill_aborts_on_usage_limit(db, monkeypatch):
    """사용량 제한 시 남은 토요일들을 헛돌지 않고 즉시 중단 + 예외 전파
    (run_tracking 이 failed 기록 → 재실행이 중복 가드에 안 막힘).
    기적재 토요일 skip(_already_backfilled)과 합쳐져 '중단→재실행=이어하기'가 완성된다.
    weekend/daily_delta 와 동일 정책 — backfill 만 범용 except 가 삼키고 있었다."""
    from datetime import date
    import pytest
    import kr_pipeline.llm_runner.backfill as bf
    from kr_pipeline.llm_runner.llm.claude_cli import UsageLimitError

    monkeypatch.setattr(bf, "get_qualifying_tickers",
                        lambda conn, as_of=None, tickers=None: [{"symbol": "UL660", "market": "KOSPI"}])
    monkeypatch.setattr(bf, "_already_backfilled", lambda conn, as_of: set())
    calls = []
    def fake_process_one(conn, symbol, market, *, dry_run, as_of):
        calls.append(as_of)
        raise UsageLimitError("usage limit reached")
    monkeypatch.setattr(bf, "_process_one", fake_process_one)

    with pytest.raises(UsageLimitError):
        # 4개 토요일 기간 — 첫 토요일에서 제한 → 나머지 3개는 시도 금지
        bf.run(db, start=date(2025, 6, 1), end=date(2025, 6, 30), tickers=["UL660"], dry_run=False)

    assert len(calls) == 1, f"제한 후에도 남은 토요일 헛호출: {calls}"


def test_backfill_resume_after_usage_limit(db, monkeypatch):
    """중단→재실행 이어하기 계약(end-to-end): 1차 실행이 토요일 2개 적재 후
    사용량 제한으로 중단되면, 2차 실행은 그 2개를 LLM 호출 없이 skip 하고
    남은 토요일만 분석한다."""
    from datetime import date
    import pytest
    import kr_pipeline.llm_runner.backfill as bf
    from kr_pipeline.llm_runner.llm.claude_cli import UsageLimitError

    t = "RSM660"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM classification_backfill WHERE symbol=%s", (t,))
    db.commit()

    monkeypatch.setattr(bf, "get_qualifying_tickers",
                        lambda conn, as_of=None, tickers=None: [{"symbol": t, "market": "KOSPI"}])
    monkeypatch.setattr(bf, "build_analysis_inline",
                        lambda conn, symbol, on_date=None, **kw: ("inline", ["/tmp/_bfpng/daily_chart.png", "/tmp/_bfpng/weekly_chart.png"], b"zip"))
    canned = {"classification": "watch", "pattern": "flat_base", "confidence": 0.7,
              "reasoning": "x", "risk_flags": [], "pivot_price": 100.0,
              "pivot_basis": "range_high", "base_high": 100.0, "base_low": 90.0,
              "base_depth_pct": 10.0, "base_start_date": "2025-05-01"}

    # 1차: 2개 토요일 성공 후 3번째에서 사용량 제한
    calls_1st = []
    def claude_1st(**kw):
        calls_1st.append(1)
        if len(calls_1st) >= 3:
            raise UsageLimitError("limit")
        return dict(canned)
    monkeypatch.setattr(bf, "call_claude", lambda *a, **kw: claude_1st(**kw))

    start, end = date(2025, 6, 1), date(2025, 6, 30)  # 토요일 4개 (6/7,14,21,28)
    with pytest.raises(UsageLimitError):
        bf.run(db, start=start, end=end, tickers=[t], dry_run=False)
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT analyzed_for_date FROM classification_backfill WHERE symbol=%s ORDER BY 1", (t,))
        stored_1st = [r[0] for r in cur.fetchall()]
    assert stored_1st == [date(2025, 6, 7), date(2025, 6, 14)], f"1차 적재: {stored_1st}"

    # 2차: 제한 해제 — 기적재 2개는 호출 없이 skip, 남은 2개만 분석
    calls_2nd = []
    def claude_2nd(**kw):
        calls_2nd.append(1)
        return dict(canned)
    monkeypatch.setattr(bf, "call_claude", lambda *a, **kw: claude_2nd(**kw))

    try:
        result = bf.run(db, start=start, end=end, tickers=[t], dry_run=False)
        db.commit()
        assert len(calls_2nd) == 2, f"기적재분 재호출 발생: {len(calls_2nd)}회 (2회여야)"
        assert result["processed"] == 2
        assert result["skipped_existing"] == 2
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM classification_backfill WHERE symbol=%s", (t,))
            assert cur.fetchone()[0] == 4, "최종 4개 토요일 전부 적재"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol=%s", (t,))
        db.commit()


def test_backfill_parallel_aggregates_and_retries(db, monkeypatch):
    """한 토요일 다중 종목 병렬: transient(TimeoutExpired) 1회 재시도 후 성공 집계."""
    import subprocess
    from datetime import date
    import kr_pipeline.llm_runner.backfill as bf

    monkeypatch.setattr(bf, "get_qualifying_tickers",
                        lambda conn, as_of=None, tickers=None: [
                            {"symbol": "PB01", "market": "KOSPI"},
                            {"symbol": "PB02", "market": "KOSPI"}])
    monkeypatch.setattr(bf, "_already_backfilled", lambda conn, as_of: set())
    seen = {}
    def fake_process_one(conn, symbol, market, *, dry_run, as_of):
        seen[symbol] = seen.get(symbol, 0) + 1
        if symbol == "PB02" and seen[symbol] == 1:
            raise subprocess.TimeoutExpired(cmd="claude", timeout=1)  # 1회 일시오류
    monkeypatch.setattr(bf, "_process_one", fake_process_one)

    res = bf.run(db, start=date(2024, 1, 6), end=date(2024, 1, 6),
                 tickers=["PB01", "PB02"], dry_run=True, concurrency=2)
    assert res["processed"] == 2
    assert res["failures"] == 0
    assert seen["PB02"] == 2  # 재시도로 2회 호출


def test_backfill_worker_connect_failure_does_not_abort(db, mocker):
    """워커 connect 실패는 그 종목만 실패 — 배치 전체 중단 안 함."""
    from datetime import date
    import kr_pipeline.llm_runner.backfill as bf
    import kr_pipeline.llm_runner.parallel as parallel

    mocker.patch.object(bf, "get_qualifying_tickers", return_value=[
        {"symbol": "CF01", "market": "KOSPI"}, {"symbol": "CF02", "market": "KOSPI"}])
    mocker.patch.object(bf, "_already_backfilled", return_value=set())
    mocker.patch.object(parallel.psycopg, "connect", side_effect=OSError("no conn"))

    res = bf.run(db, start=date(2024, 1, 6), end=date(2024, 1, 6),
                 tickers=["CF01", "CF02"], dry_run=True, concurrency=2)
    assert res["processed"] == 0
    assert res["failures"] == 2
    assert res["weeks"] == 1


def test_backfill_integrity_error_skips_not_fails(db, monkeypatch):
    """DataIntegrityError 는 integrity_skipped 로 분류(실패 집계 아님)."""
    from datetime import date
    import kr_pipeline.llm_runner.backfill as bf
    from api.services.integrity_guard import DataIntegrityError

    monkeypatch.setattr(bf, "get_qualifying_tickers",
                        lambda conn, as_of=None, tickers=None: [{"symbol": "IG01", "market": "KOSPI"}])
    monkeypatch.setattr(bf, "_already_backfilled", lambda conn, as_of: set())
    def fake_process_one(conn, symbol, market, *, dry_run, as_of):
        raise DataIntegrityError(ticker=symbol, on_date=date(2024, 1, 5),
                                 p_value=100.0, i_value=50.0, column="adj_close")
    monkeypatch.setattr(bf, "_process_one", fake_process_one)

    res = bf.run(db, start=date(2024, 1, 6), end=date(2024, 1, 6),
                 tickers=["IG01"], dry_run=True, concurrency=1)
    assert res["processed"] == 0
    assert res["failures"] == 0
    assert len(res["integrity_skipped"]) == 1
    assert res["integrity_skipped"][0]["symbol"] == "IG01"


def test_backfill_run_returns_expected_keys(db, monkeypatch):
    """반환 dict 키 보존(__main__ / run_tracking 소비 계약)."""
    from datetime import date
    import kr_pipeline.llm_runner.backfill as bf
    monkeypatch.setattr(bf, "get_qualifying_tickers", lambda conn, as_of=None, tickers=None: [])
    monkeypatch.setattr(bf, "_already_backfilled", lambda conn, as_of: set())
    res = bf.run(db, start=date(2024, 1, 6), end=date(2024, 1, 6), tickers=["X"], dry_run=True)
    assert set(res) == {"weeks", "processed", "skipped_existing", "failures",
                        "failed", "integrity_skipped", "start", "end"}


def test_concurrency_arg_rejected_for_non_backfill(capsys):
    """--concurrency 는 backfill 전용 — 다른 모드와 함께 쓰면 우리 가드가 명시적 에러."""
    import sys
    import pytest
    from kr_pipeline.llm_runner.__main__ import main
    old = sys.argv
    sys.argv = ["prog", "--mode=weekend", "--concurrency=4"]
    try:
        with pytest.raises(SystemExit):
            main()
        err = capsys.readouterr().err
        assert "only supported with --mode=backfill" in err  # 구현 전: "unrecognized arguments"
    finally:
        sys.argv = old


def test_insert_backfill_classification_records_llm_model(db):
    """llm_meta.model → llm_model 컬럼 기록 (미제공 시 NULL 하위호환)."""
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKF2','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF2'")
    db.commit()
    insert_backfill_classification(
        db, symbol="BKF2", classified_at=datetime(2026, 7, 2, 1, tzinfo=timezone.utc),
        market="KOSPI", result=_result("watch"), source="backfill",
        llm_meta={"duration_s": 10.0, "input_tokens": 100, "output_tokens": 50,
                  "model": "claude-sonnet-5"},
        analyzed_for_date=date(2025, 10, 7),
    )
    # 하위호환: model 키 없는 llm_meta 도 그대로 동작 (NULL 저장)
    insert_backfill_classification(
        db, symbol="BKF2", classified_at=datetime(2026, 7, 2, 2, tzinfo=timezone.utc),
        market="KOSPI", result=_result("watch"), source="backfill",
        llm_meta={"duration_s": 10.0, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2025, 10, 14),
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT analyzed_for_date, llm_model FROM classification_backfill "
                "WHERE symbol='BKF2' ORDER BY analyzed_for_date"
            )
            rows = cur.fetchall()
        assert rows == [(date(2025, 10, 7), "claude-sonnet-5"), (date(2025, 10, 14), None)]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF2'")
        db.commit()
