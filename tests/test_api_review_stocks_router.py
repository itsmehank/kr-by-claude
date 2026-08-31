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


def test_stocks_endpoint_exposes_closed_reason(client, seed, db):
    # 닫는 행(system_disqualify)의 reasoning 이 응답 JSON 의 streaks[].closed_reason 으로
    # 노출되는지(#139).
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date, reasoning)
               VALUES ('RVSAPI01','2026-10-12 22:02:00+09','KOSPI','disqualified',NULL,
                       NULL,'system_disqualify','2026-10-12',
                       'minervini_pass=false — 미너비니 자격 상실(시스템 강등)')""")
    db.commit()
    r = client.get("/api/review/stocks?from=2026-10-01&to=2026-10-31&ticker=RVSAPI01")
    assert r.status_code == 200
    streak = r.json()["rows"][0]["streaks"][0]
    assert streak["closed_by"] == "disqualify"
    assert streak["closed_reason"] == "minervini_pass=false — 미너비니 자격 상실(시스템 강등)"


def test_candles_endpoint_returns_adj_ohlc_in_range(client, seed, db):
    # 캔들 엔드포인트(#143): adj open/high/low/close 를 날짜순으로 반환하고,
    # o/h/l 미백필(null)인 날은 null 을 그대로 내려 프론트가 종가 틱으로 폴백한다.
    with db.cursor() as cur:
        cur.execute(
            """UPDATE daily_prices
                  SET adj_open = 95, adj_high = 105, adj_low = 94
                WHERE ticker = 'RVSAPI01' AND date = '2026-10-06'""")
    db.commit()
    r = client.get("/api/review/stocks/RVSAPI01/candles"
                   "?from=2026-10-06&to=2026-10-07")
    assert r.status_code == 200
    candles = r.json()["candles"]
    assert [c[0] for c in candles] == ["2026-10-06", "2026-10-07"]
    assert candles[0][1:] == [95.0, 105.0, 94.0, 97.0]   # adj_close = 90+row_number
    assert candles[1][1] is None and candles[1][2] is None and candles[1][3] is None
    assert isinstance(candles[1][4], float)              # adj_close 는 항상 존재
    # 범위 밖 날짜는 포함되지 않는다
    r2 = client.get("/api/review/stocks/RVSAPI01/candles"
                    "?from=2026-10-06&to=2026-10-06")
    assert [c[0] for c in r2.json()["candles"]] == ["2026-10-06"]
