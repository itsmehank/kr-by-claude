import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    with db.cursor() as cur:
        for tbl, col in [("trigger_evaluation_log", "symbol"),
                         ("weekly_classification", "symbol"),
                         ("daily_prices", "ticker"), ("stocks", "ticker")]:
            cur.execute(f"DELETE FROM {tbl} WHERE {col} LIKE 'RVSAPI%'")
        cur.execute("""INSERT INTO stocks (ticker, name, market, sector, listed_at)
                       VALUES ('RVSAPI01','에이피','KOSPI','반도체','2020-01-01')""")
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES ('RVSAPI01','2026-10-05 10:00:00+09','KOSPI','watch',
                       'cup_with_handle', 100, 'weekend', '2026-10-05')""")
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, reasoning, prior_classification_at, analyzed_for_date)
               VALUES ('RVSAPI01','2026-10-07 21:00:00+09','promotion',
                       98, 1000, 100, 'wait', '접근',
                       '2026-10-05 10:00:00+09', '2026-10-07')""")
        cur.execute(
            """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                                         adj_close, volume, value)
               SELECT 'RVSAPI01', d::date, 1,1,1,1,
                      90 + row_number() OVER (), 1000, 1000
                 FROM generate_series('2026-09-28'::date, '2026-10-30', '1 day') d
                WHERE extract(isodow FROM d) < 6""")
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_stocks_endpoint_shape_and_filters(client, seed):
    r = client.get("/api/review/stocks?from=2026-10-01&to=2026-10-31&ticker=RVSAPI01")
    assert r.status_code == 200
    body = r.json()
    assert body["orphan_trigger_count"] == 0
    row = body["rows"][0]
    assert row["name"] == "에이피"                     # stocks JOIN
    assert row["latest"]["stage"] == "staging"
    assert row["streaks"][0]["analyses"][0]["triggers"][0]["trigger_type"] == "promotion"
    assert row["pivot_steps"][0][2] == 100.0
    # status·음수 방어
    assert client.get("/api/review/stocks?status=closed&ticker=RVSAPI01"
                      "&from=2026-10-01&to=2026-10-31").json()["rows"] == []
    assert client.get("/api/review/stocks?limit=-1").status_code == 422
    assert client.get("/api/review/stocks?limit=9999").status_code == 200
