import pytest
from datetime import datetime, timezone
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
