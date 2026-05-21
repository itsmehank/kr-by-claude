"""delta — T_today − recently_classified."""
from datetime import date, timedelta


def test_find_new_tickers(db):
    """오늘 자격 있는 종목 중 7일 내 분류 없는 종목 추출."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        for t in ["A", "B", "C", "D"]:
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
                (t, t),
            )
        for t in ["A", "B", "C", "D"]:
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, minervini_pass)
                   VALUES (%s, %s, 100, TRUE) ON CONFLICT DO NOTHING""",
                (t, today),
            )
        for t in ["A", "B"]:
            cur.execute(
                """INSERT INTO weekly_classification
                   (symbol, classified_at, market, classification, source)
                   VALUES (%s, %s, 'KOSPI', 'entry', 'weekend')""",
                (t, today - timedelta(days=3)),
            )
    db.commit()

    from kr_pipeline.llm_runner.compute.delta import find_new_tickers

    new = find_new_tickers(db, as_of=today)
    assert set(new) == {"C", "D"}


def test_old_classification_does_not_block(db):
    """30일 전 분류된 종목은 다시 신규 후보."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('OLD', 'O', 'KOSPI') ON CONFLICT DO NOTHING"
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, minervini_pass)
               VALUES ('OLD', %s, 100, TRUE) ON CONFLICT DO NOTHING""",
            (today,),
        )
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, source)
               VALUES ('OLD', %s, 'KOSPI', 'ignore', 'weekend')""",
            (today - timedelta(days=30),),
        )
    db.commit()

    from kr_pipeline.llm_runner.compute.delta import find_new_tickers

    new = find_new_tickers(db, as_of=today)
    assert "OLD" in new
