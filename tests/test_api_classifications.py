import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_classifications(db):
    """3종목 분류 + stocks 데이터 seed."""
    def override():
        yield db
    app.dependency_overrides[get_conn] = override

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'CLSTEST%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'CLSTEST%'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('CLSTEST01','Test1','KOSPI','금융','2020-01-01'),
                      ('CLSTEST02','Test2','KOSDAQ','반도체','2020-01-01'),
                      ('CLSTEST03','Test3','KOSPI','보험','2020-01-01')"""
        )
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, confidence, reasoning, source, created_at)
               VALUES
                 ('CLSTEST01', NOW() - INTERVAL '23 hours', 'KOSPI', 'watch', 'flat_base',
                  1000.0, 0.55, '근거1', 'weekend', NOW()),
                 ('CLSTEST02', NOW() - INTERVAL '2 day', 'KOSDAQ', 'ignore', 'none',
                  NULL, 0.78, '근거2', 'weekend', NOW()),
                 ('CLSTEST03', NOW() - INTERVAL '3 day', 'KOSPI', 'entry', 'cup',
                  2000.0, 0.85, '근거3', 'daily-delta', NOW())"""
        )
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  confidence, source, created_at)
               VALUES ('CLSTEST01', NOW() - INTERVAL '10 day', 'KOSPI', 'ignore', 'none',
                       0.40, 'weekend', NOW())"""
        )
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_get_classifications_basic(client, seed_classifications):
    r = client.get("/api/classifications?lookback_days=30")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    symbols = {row["symbol"] for row in data}
    assert {"CLSTEST01", "CLSTEST02", "CLSTEST03"}.issubset(symbols)


def test_distinct_on_symbol_returns_latest(client, seed_classifications):
    """같은 symbol 의 두 분류 행 → 최신 1건만 응답."""
    r = client.get("/api/classifications?lookback_days=30")
    rows = [row for row in r.json() if row["symbol"] == "CLSTEST01"]
    assert len(rows) == 1
    assert rows[0]["classification"] == "watch"


def test_response_includes_name_and_sector(client, seed_classifications):
    r = client.get("/api/classifications?lookback_days=30")
    row = next(row for row in r.json() if row["symbol"] == "CLSTEST01")
    assert row["name"] == "Test1"
    assert row["sector"] == "금융"
    assert row["market"] == "KOSPI"


def test_classification_filter(client, seed_classifications):
    """classifications=watch&classifications=entry → ignore 제외."""
    r = client.get("/api/classifications?lookback_days=30&classifications=watch&classifications=entry")
    classes = {row["classification"] for row in r.json()}
    assert "ignore" not in classes
    test_symbols = {row["symbol"] for row in r.json() if row["symbol"].startswith("CLSTEST")}
    assert test_symbols == {"CLSTEST01", "CLSTEST03"}


def test_source_filter(client, seed_classifications):
    """sources=weekend → daily-delta 제외."""
    r = client.get("/api/classifications?lookback_days=30&sources=weekend")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    for row in test_rows:
        assert row["source"] == "weekend"


def test_min_confidence_filter(client, seed_classifications):
    """min_confidence=0.7 → confidence < 0.7 제외."""
    r = client.get("/api/classifications?lookback_days=30&min_confidence=0.7")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    for row in test_rows:
        assert row["confidence"] >= 0.7
    syms = {row["symbol"] for row in test_rows}
    assert syms == {"CLSTEST02", "CLSTEST03"}


def test_lookback_days_filter(client, seed_classifications):
    """lookback_days=1 → 1일 이내 분류만."""
    r = client.get("/api/classifications?lookback_days=1")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    syms = {row["symbol"] for row in test_rows}
    assert syms == {"CLSTEST01"}


def test_sort_confidence_desc(client, seed_classifications):
    """sort=confidence_desc → confidence 내림차순."""
    r = client.get("/api/classifications?lookback_days=30&sort=confidence_desc")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    confs = [row["confidence"] for row in test_rows]
    assert confs == sorted(confs, reverse=True)


def test_unknown_sort_returns_400(client):
    r = client.get("/api/classifications?sort=invalid")
    assert r.status_code == 400


def test_analyzed_for_date_in_response(client, db):
    """analyzed_for_date 가 채워진 행은 응답에 그 값으로 전달됨."""
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol = 'CLSTESTAFD'")
            cur.execute("DELETE FROM stocks WHERE ticker = 'CLSTESTAFD'")
            cur.execute(
                """INSERT INTO stocks (ticker, name, market, sector, listed_at)
                   VALUES ('CLSTESTAFD','TestAFD','KOSPI','금융','2020-01-01')"""
            )
            cur.execute(
                """INSERT INTO weekly_classification
                     (symbol, classified_at, analyzed_for_date, market,
                      classification, source, created_at)
                   VALUES ('CLSTESTAFD', NOW() - INTERVAL '1 day', '2026-05-15',
                           'KOSPI', 'watch', 'weekend', NOW())"""
            )
        db.commit()

        r = client.get("/api/classifications?lookback_days=30")
        row = next(r_ for r_ in r.json() if r_["symbol"] == "CLSTESTAFD")
        assert row["analyzed_for_date"] == "2026-05-15"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_backfill_rows_not_in_live_classifications(client, db):
    """classification_backfill 에만 있는 종목은 /api/classifications(weekly_classification)에 안 뜬다."""
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='ISOLBKF'")
            cur.execute("DELETE FROM weekly_classification WHERE symbol='ISOLBKF'")
            cur.execute("DELETE FROM stocks WHERE ticker='ISOLBKF'")
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ISOLBKF','Iso','KOSPI')")
            cur.execute(
                """INSERT INTO classification_backfill
                     (symbol, classified_at, analyzed_for_date, market, classification, source)
                   VALUES ('ISOLBKF', NOW(), CURRENT_DATE - 1, 'KOSPI', 'watch', 'backfill')"""
            )
        db.commit()
        r = client.get("/api/classifications?lookback_days=30&classifications=watch&classifications=entry")
        syms = {row["symbol"] for row in r.json()}
        assert "ISOLBKF" not in syms, "백필 행이 라이브 분류 API에 누수됨"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='ISOLBKF'")
            cur.execute("DELETE FROM stocks WHERE ticker='ISOLBKF'")
        db.commit()
        app.dependency_overrides.pop(get_conn, None)


def test_response_includes_analyzed_for_date_field_for_legacy_rows(client, seed_classifications):
    """기존 seed (analyzed_for_date 미지정) 도 응답에 키 존재 + None."""
    r = client.get("/api/classifications?lookback_days=30")
    test_rows = [row for row in r.json() if row["symbol"].startswith("CLSTEST")]
    for row in test_rows:
        assert "analyzed_for_date" in row
        if row["symbol"] in ("CLSTEST01", "CLSTEST02", "CLSTEST03"):
            assert row["analyzed_for_date"] is None


def test_ticker_filter_returns_only_that_symbol(client, seed_classifications):
    r = client.get("/api/classifications?lookback_days=30&ticker=CLSTEST02")
    rows = r.json()
    assert {row["symbol"] for row in rows} == {"CLSTEST02"}
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Task 4: default excludes disqualified; explicit filter includes it
# ---------------------------------------------------------------------------

_DQ_SYMS = ("API_W", "API_DQ")


@pytest.fixture(autouse=False)
def _clean_dq(db):
    def _del():
        with db.cursor() as cur:
            for t in _DQ_SYMS:
                cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
                cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
        db.commit()
    _del()
    yield
    _del()


def _seed_dq(cur, ticker, classification):
    cur.execute(
        "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
        (ticker, ticker),
    )
    cur.execute(
        """INSERT INTO weekly_classification (symbol, classified_at, market, classification, source)
           VALUES (%s, NOW(), 'KOSPI', %s, 'weekend')""",
        (ticker, classification),
    )


def test_classifications_default_excludes_disqualified(db, _clean_dq):
    from api.routers.classifications import get_classifications
    with db.cursor() as cur:
        _seed_dq(cur, "API_W", "watch")
        _seed_dq(cur, "API_DQ", "disqualified")
    db.commit()
    # 직접 호출 시 FastAPI Query 기본값 대신 명시적 None 전달 (HTTP 경로에선 FastAPI 가 해석)
    syms = {r.symbol for r in get_classifications(classifications=None, sources=None, conn=db)}
    assert "API_W" in syms
    assert "API_DQ" not in syms
    syms2 = {r.symbol for r in get_classifications(classifications=["disqualified"], sources=None, conn=db)}
    assert "API_DQ" in syms2


def test_latest_picked_by_analyzed_for_date_not_classified_at(client, db):
    """더 오래전 데이터(analyzed_for_date)지만 더 늦게 실행(classified_at)된 행이
    최신 상태를 덮어쓰지 않는다."""
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='CLSAXIS1'")
            cur.execute("DELETE FROM stocks WHERE ticker='CLSAXIS1'")
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES ('CLSAXIS1','Ax','KOSPI')"
            )
            # 데이터 기준 최신 = ignore (analyzed_for_date 어제), classified_at 2일 전
            cur.execute(
                """INSERT INTO weekly_classification
                     (symbol, classified_at, analyzed_for_date, market, classification, source)
                   VALUES ('CLSAXIS1', NOW() - INTERVAL '2 day', CURRENT_DATE - 1,
                           'KOSPI', 'ignore', 'weekend')"""
            )
            # 백필성 = watch (analyzed_for_date 30일 전), classified_at 방금(가장 늦음)
            cur.execute(
                """INSERT INTO weekly_classification
                     (symbol, classified_at, analyzed_for_date, market, classification, source)
                   VALUES ('CLSAXIS1', NOW(), CURRENT_DATE - 30,
                           'KOSPI', 'watch', 'weekend')"""
            )
        db.commit()
        r = client.get("/api/classifications?lookback_days=90&classifications=watch&classifications=ignore")
        rows = [x for x in r.json() if x["symbol"] == "CLSAXIS1"]
        assert len(rows) == 1
        assert rows[0]["classification"] == "ignore"  # analyzed_for_date 최신이 이김
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='CLSAXIS1'")
            cur.execute("DELETE FROM stocks WHERE ticker='CLSAXIS1'")
        db.commit()
        app.dependency_overrides.pop(get_conn, None)


def test_classification_history_unions_live_and_backfill(client, db):
    """history: weekly_classification + classification_backfill 합쳐 날짜순, 같은 날짜 라이브 우선."""
    from datetime import date, datetime, timezone

    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('HST1','H','KOSPI') ON CONFLICT DO NOTHING")
            cur.execute("DELETE FROM weekly_classification WHERE symbol='HST1'")
            cur.execute("DELETE FROM classification_backfill WHERE symbol='HST1'")
            cur.execute("""INSERT INTO weekly_classification (symbol, classified_at, analyzed_for_date, market, classification, source)
                           VALUES ('HST1', %s, %s, 'KOSPI', 'watch', 'weekend')""",
                        (datetime(2025, 2, 2, tzinfo=timezone.utc), date(2025, 2, 1)))
            cur.execute("""INSERT INTO classification_backfill (symbol, classified_at, analyzed_for_date, market, classification, source)
                           VALUES ('HST1', %s, %s, 'KOSPI', 'ignore', 'backfill')""",
                        (datetime(2025, 1, 5, tzinfo=timezone.utc), date(2025, 1, 4)))
            cur.execute("""INSERT INTO classification_backfill (symbol, classified_at, analyzed_for_date, market, classification, source)
                           VALUES ('HST1', %s, %s, 'KOSPI', 'entry', 'backfill')""",
                        (datetime(2025, 2, 1, tzinfo=timezone.utc), date(2025, 2, 1)))
        db.commit()
        r = client.get("/api/classifications/history/HST1?start=2025-01-01&end=2025-03-01")
        assert r.status_code == 200
        rows = r.json()
        # 날짜 오름차순; 2025-02-01 중복은 라이브(watch) 우선 1건
        assert [(x["date"], x["classification"]) for x in rows] == [
            ("2025-01-04", "ignore"),
            ("2025-02-01", "watch"),
        ]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='HST1'")
            cur.execute("DELETE FROM classification_backfill WHERE symbol='HST1'")
        db.commit()
        app.dependency_overrides.pop(get_conn, None)


def test_classification_history_empty_for_unknown_ticker(client, db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        r = client.get("/api/classifications/history/NOPE1?start=2025-01-01&end=2025-03-01")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.pop(get_conn, None)
