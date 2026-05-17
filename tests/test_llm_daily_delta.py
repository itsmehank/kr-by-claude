from datetime import date


def test_daily_delta_dry_run(db, mocker):
    """오늘 신규 자격 종목 → daily_delta 로 분류."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('DD1', 'D', 'KOSPI') ON CONFLICT DO NOTHING"
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, minervini_pass, drawdown_filter_pass)
               VALUES ('DD1', %s, 100, TRUE, TRUE) ON CONFLICT DO NOTHING""",
            (today,),
        )
    db.commit()

    mocker.patch(
        "kr_pipeline.llm_runner.daily_delta.build_analysis_zip",
        return_value=b"fake_zip",
    )

    from kr_pipeline.llm_runner.daily_delta import run

    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM weekly_classification WHERE source='daily_delta' AND symbol='DD1'"
        )
        before = cur.fetchone()[0]

    result = run(db, dry_run=True, as_of=today)

    assert result["processed"] >= 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT source FROM weekly_classification WHERE symbol='DD1' ORDER BY classified_at DESC LIMIT 1"
        )
        assert cur.fetchone()[0] == "daily_delta"

    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM weekly_classification WHERE source='daily_delta' AND symbol='DD1'"
        )
        after = cur.fetchone()[0]

    assert after > before
