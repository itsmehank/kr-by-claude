"""주말 (5) batch — 결정론 통과 종목 분류."""
from datetime import date


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
