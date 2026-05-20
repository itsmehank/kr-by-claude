import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_triggers(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override

    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'TRGTEST%'")
        cur.execute("DELETE FROM daily_indicators WHERE ticker LIKE 'TRGTEST%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'TRGTEST%'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('TRGTEST01','Test1','KOSPI','반도체','2020-01-01'),
                      ('TRGTEST02','Test2','KOSDAQ','보험','2020-01-01')"""
        )
        cur.execute(
            """INSERT INTO daily_indicators
                 (ticker, date, adj_close, volume, avg_volume_50d)
               VALUES
                 ('TRGTEST01', '2026-05-20', 84000, 12000000, 6600000),
                 ('TRGTEST02', '2026-05-19', 30200,  3000000, 2500000)"""
        )
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, confidence, reasoning, prior_classification_at)
               VALUES
                 ('TRGTEST01', '2026-05-20 09:32:12+09', 'breakout',
                  84000, 12000000, 82300, 'go_now', 0.78, '거래량 증가와 함께 …',
                  '2026-05-17 10:00:00+09'),
                 ('TRGTEST02', '2026-05-19 09:35:00+09', 'invalidation',
                  30200, 3000000, 32100, 'abort', 0.65, '손절 가격 하향 이탈',
                  '2026-05-17 10:00:00+09')"""
        )
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_empty_when_no_filter_matches(client, seed_triggers):
    r = client.get("/api/triggers?ticker=NOSUCH")
    assert r.status_code == 200
    assert r.json() == []


def test_returns_triggers_with_stocks_join(client, seed_triggers):
    r = client.get("/api/triggers?ticker=TRGTEST01")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    row = data[0]
    assert row["symbol"] == "TRGTEST01"
    assert row["name"] == "Test1"
    assert row["market"] == "KOSPI"
    assert row["trigger_type"] == "breakout"
    assert row["decision"] == "go_now"
    assert row["close"] == 84000.0
    assert row["pivot_price"] == 82300.0
    assert row["confidence"] == 0.78


def test_volume_ratio_and_pivot_delta_calculated(client, seed_triggers):
    r = client.get("/api/triggers?ticker=TRGTEST01")
    row = r.json()[0]
    # avg_volume_50d_ratio = 12000000 / 6600000 ≈ 1.818
    assert row["avg_volume_50d_ratio"] == pytest.approx(1.818, rel=0.01)
    # pivot_delta_pct = (84000 - 82300) / 82300 * 100 ≈ 2.066
    assert row["pivot_delta_pct"] == pytest.approx(2.066, rel=0.01)


def test_date_filter(client, seed_triggers):
    r = client.get("/api/triggers?date=2026-05-20")
    syms = {row["symbol"] for row in r.json() if row["symbol"].startswith("TRGTEST")}
    assert syms == {"TRGTEST01"}


def test_from_to_range(client, seed_triggers):
    r = client.get("/api/triggers?from=2026-05-19&to=2026-05-19")
    syms = {row["symbol"] for row in r.json() if row["symbol"].startswith("TRGTEST")}
    assert syms == {"TRGTEST02"}


def test_decision_filter(client, seed_triggers):
    r = client.get("/api/triggers?decision=go_now")
    test_rows = [row for row in r.json() if row["symbol"].startswith("TRGTEST")]
    for row in test_rows:
        assert row["decision"] == "go_now"
    assert {row["symbol"] for row in test_rows} == {"TRGTEST01"}


def test_trigger_type_filter(client, seed_triggers):
    r = client.get("/api/triggers?trigger_type=invalidation")
    test_rows = [row for row in r.json() if row["symbol"].startswith("TRGTEST")]
    assert {row["symbol"] for row in test_rows} == {"TRGTEST02"}


def test_combined_filters(client, seed_triggers):
    r = client.get("/api/triggers?from=2026-05-20&to=2026-05-20&decision=go_now")
    syms = {row["symbol"] for row in r.json() if row["symbol"].startswith("TRGTEST")}
    assert syms == {"TRGTEST01"}


def test_order_evaluated_at_desc(client, seed_triggers):
    r = client.get("/api/triggers?from=2026-05-19&to=2026-05-20")
    test_rows = [row for row in r.json() if row["symbol"].startswith("TRGTEST")]
    assert test_rows[0]["symbol"] == "TRGTEST01"
    assert test_rows[1]["symbol"] == "TRGTEST02"


def test_limit_and_offset(client, seed_triggers):
    # Baseline ordered list (default limit=200) — captures ground truth for the range,
    # independent of any other rows that may already live in the test DB.
    baseline = client.get("/api/triggers?from=2026-05-19&to=2026-05-20").json()
    assert len(baseline) >= 2

    r1 = client.get("/api/triggers?from=2026-05-19&to=2026-05-20&limit=1&offset=0").json()
    r2 = client.get("/api/triggers?from=2026-05-19&to=2026-05-20&limit=1&offset=1").json()
    assert len(r1) == 1 and len(r2) == 1
    assert r1[0]["symbol"] == baseline[0]["symbol"]
    assert r2[0]["symbol"] == baseline[1]["symbol"]
    assert r1[0]["symbol"] != r2[0]["symbol"]
