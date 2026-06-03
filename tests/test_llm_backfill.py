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
    # 실데이터 시작(2024-05-17) 이전 날짜 → get_qualifying_tickers 가 우리가 심은 종목만 반환(격리).
    as_of = _date(2024, 1, 2)
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE analyzed_for_date=%s", (as_of,))
        for t in ("BKR1", "BKR2"):
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'B','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s AND date=%s", (t, as_of))
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, minervini_pass, adj_close)
                   VALUES (%s,%s,TRUE,1000.0)""",
                (t, as_of),
            )
    db.commit()
    seen_on_date = []
    monkeypatch.setattr(bf, "build_analysis_zip",
                        lambda conn, symbol, on_date=None, **kw: seen_on_date.append(on_date) or b"zip")
    monkeypatch.setattr(bf, "call_claude",
                        lambda **kwargs: _result("watch"))
    try:
        res = bf.run(db, dry_run=False, as_of=as_of)
        assert res["processed"] == 2
        assert seen_on_date and all(d == as_of for d in seen_on_date)
        with db.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM classification_backfill WHERE analyzed_for_date=%s", (as_of,))
            assert cur.fetchone()[0] == 2
        res2 = bf.run(db, dry_run=False, as_of=as_of)
        assert res2["processed"] == 0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE analyzed_for_date=%s", (as_of,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker IN ('BKR1','BKR2') AND date=%s", (as_of,))
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


def test_backfill_mode_requires_date():
    import sys, pytest
    from kr_pipeline.llm_runner.__main__ import main
    argv = sys.argv
    sys.argv = ["prog", "--mode=backfill"]  # --date 없음
    try:
        with pytest.raises(SystemExit):  # argparse parser.error → SystemExit
            main()
    finally:
        sys.argv = argv


def test_get_qualifying_tickers_filters_by_tickers(db):
    """tickers 인자 지정 시 그 종목 중 minervini 통과분만, 생략 시 전체."""
    from kr_pipeline.llm_runner.load import get_qualifying_tickers
    from datetime import date as _date
    as_of = _date(2023, 1, 7)  # 실데이터 이전 → 격리
    with db.cursor() as cur:
        for t in ("QF1", "QF2", "QF3"):
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'B','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s AND date=%s", (t, as_of))
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,adj_close) VALUES ('QF1',%s,TRUE,1000.0)", (as_of,))
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,adj_close) VALUES ('QF2',%s,TRUE,1000.0)", (as_of,))
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
