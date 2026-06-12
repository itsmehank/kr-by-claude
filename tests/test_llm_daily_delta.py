from datetime import date


def test_daily_delta_dry_run(db, mocker):
    """dry-run: 신규 자격 종목을 처리(processed≥1)하되 DB insert 없이 freeze 만.

    (stale 정정: 0af04c7 에서 dry-run 이 'freeze 저장만, 분류 insert 없음'으로
    바뀌었는데 테스트가 insert 를 기대한 채 방치돼 baseline 상시 실패였다.)"""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('DD1', 'D', 'KOSPI') ON CONFLICT DO NOTHING"
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, minervini_pass)
               VALUES ('DD1', %s, 100, TRUE) ON CONFLICT DO NOTHING""",
            (today,),
        )
        # 최근 7일 분류 제거해야 delta 가 DD1 을 신규 후보로 인식
        cur.execute("DELETE FROM weekly_classification WHERE symbol='DD1'")
    db.commit()

    import kr_pipeline.llm_runner.daily_delta as dd

    mocker.patch.object(dd, "build_analysis_zip", return_value=b"fake_zip")
    freeze = mocker.patch.object(dd, "save_freeze")

    result = dd.run(db, dry_run=True, as_of=today)

    assert result["processed"] >= 1
    assert freeze.call_count >= 1, "dry-run 도 freeze 는 저장해야 한다"

    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM weekly_classification WHERE source='daily_delta' AND symbol='DD1'"
        )
        assert cur.fetchone()[0] == 0, "dry-run 이 분류를 insert 하면 안 된다"


def test_daily_delta_zip_excludes_prior_analysis_and_pins_as_of(db, mocker):
    """신규 분석 ZIP 에 직전 분류(analysis_result.json)가 혼입되면 안 되고(anchoring),
    --date 과거 재실행 시 미래 데이터가 새지 않도록 on_date=as_of 를 고정해야 한다."""
    from datetime import date
    import kr_pipeline.llm_runner.daily_delta as dd
    zip_mock = mocker.patch.object(dd, "build_analysis_zip", return_value=b"fake_zip")
    mocker.patch.object(dd, "save_freeze")
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('DDZC1','T','KOSPI') ON CONFLICT DO NOTHING")
    db.commit()

    as_of = date(2025, 6, 10)
    dd._process_one(db, "DDZC1", dry_run=True, as_of=as_of)

    _, kwargs = zip_mock.call_args
    assert kwargs.get("include_prior_analysis") is False
    assert kwargs.get("on_date") == as_of


def test_daily_delta_aborts_on_usage_limit(db, mocker):
    """사용량 제한 시 남은 종목 순회 없이 즉시 중단 + 예외 전파."""
    import pytest
    import kr_pipeline.llm_runner.daily_delta as dd
    from kr_pipeline.llm_runner.llm.claude_cli import UsageLimitError

    mocker.patch.object(dd, "find_new_tickers", return_value=["UL1", "UL2", "UL3"])
    calls = []
    def fake_process_one(conn, symbol, *, dry_run, as_of):
        calls.append(symbol)
        raise UsageLimitError("usage limit reached")
    mocker.patch.object(dd, "_process_one", side_effect=fake_process_one)

    with pytest.raises(UsageLimitError):
        dd.run(db, dry_run=True)

    assert len(calls) == 1, f"제한 감지 후에도 추가 호출: {calls}"
