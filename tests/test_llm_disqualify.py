import pytest
from datetime import date, datetime, timezone

AS_OF = date(2026, 6, 2)

_ALL_TEST_SYMBOLS = (
    "LOSE_W", "LOSE_E", "LOSE_I", "KEEP_W", "ALREADY_DQ",
    "RUN_LOSE", "RUN_KEEP",
    "DRY_LOSE",
)


@pytest.fixture(autouse=True)
def _clean_test_symbols(db):
    """각 테스트 전후로 테스트 전용 심볼을 정리해 커밋 누출을 방지."""
    with db.cursor() as cur:
        for sym in _ALL_TEST_SYMBOLS:
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (sym,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (sym,))
    db.commit()
    yield
    with db.cursor() as cur:
        for sym in _ALL_TEST_SYMBOLS:
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (sym,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (sym,))
    db.commit()


def _seed(cur, ticker, classification, minervini_pass):
    cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
                (ticker, ticker))
    cur.execute("""INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass)
                   VALUES (%s, %s, 100, %s) ON CONFLICT DO NOTHING""", (ticker, AS_OF, minervini_pass))
    cur.execute("""INSERT INTO weekly_classification (symbol, classified_at, market, classification, source)
                   VALUES (%s, %s, 'KOSPI', %s, 'weekend')""",
                (ticker, datetime(2026, 5, 30, tzinfo=timezone.utc), classification))


def test_get_classified_losing_minervini(db):
    from kr_pipeline.llm_runner.load import get_classified_losing_minervini
    with db.cursor() as cur:
        for t in ("LOSE_W", "LOSE_E", "LOSE_I", "KEEP_W", "ALREADY_DQ"):
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        _seed(cur, "LOSE_W", "watch", False)
        _seed(cur, "LOSE_E", "entry", False)
        _seed(cur, "LOSE_I", "ignore", False)
        _seed(cur, "KEEP_W", "watch", True)
        _seed(cur, "ALREADY_DQ", "disqualified", False)
    db.commit()
    losers = {x["symbol"] for x in get_classified_losing_minervini(db, AS_OF)}
    assert losers >= {"LOSE_W", "LOSE_E", "LOSE_I"}
    assert "KEEP_W" not in losers
    assert "ALREADY_DQ" not in losers


def test_disqualify_run_writes_and_idempotent(db):
    from kr_pipeline.llm_runner import disqualify
    with db.cursor() as cur:
        for t in ("RUN_LOSE", "RUN_KEEP"):
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        _seed(cur, "RUN_LOSE", "watch", False)
        _seed(cur, "RUN_KEEP", "entry", True)
    db.commit()

    r1 = disqualify.run(db, dry_run=False, as_of=AS_OF, limit=None)
    assert r1["disqualified"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT ON (symbol) classification FROM weekly_classification WHERE symbol='RUN_LOSE' ORDER BY symbol, classified_at DESC")
        assert cur.fetchone()[0] == "disqualified"
        cur.execute("SELECT DISTINCT ON (symbol) classification FROM weekly_classification WHERE symbol='RUN_KEEP' ORDER BY symbol, classified_at DESC")
        assert cur.fetchone()[0] == "entry"

    r2 = disqualify.run(db, dry_run=False, as_of=AS_OF, limit=None)
    assert r2["disqualified"] == 0  # 멱등: 이미 disqualified


def test_disqualify_dry_run_no_write(db):
    from kr_pipeline.llm_runner import disqualify
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='DRY_LOSE'")
        _seed(cur, "DRY_LOSE", "watch", False)
    db.commit()
    r = disqualify.run(db, dry_run=True, as_of=AS_OF, limit=None)
    assert r["disqualified"] == 0
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM weekly_classification WHERE symbol='DRY_LOSE' AND classification='disqualified'")
        assert cur.fetchone()[0] == 0


def test_insert_disqualification_sets_analyzed_for_date(db):
    from datetime import datetime, timezone, date
    from kr_pipeline.llm_runner.store import insert_disqualification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='AXDQ1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('AXDQ1','A','KOSPI') ON CONFLICT DO NOTHING")
    db.commit()
    insert_disqualification(
        db, symbol='AXDQ1', classified_at=datetime(2026, 6, 1, 5, tzinfo=timezone.utc),
        market='KOSPI', analyzed_for_date=date(2026, 6, 1),
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT classification, analyzed_for_date FROM weekly_classification WHERE symbol='AXDQ1'")
            row = cur.fetchone()
        assert row[0] == 'disqualified'
        assert row[1] == date(2026, 6, 1)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXDQ1'")
        db.commit()
