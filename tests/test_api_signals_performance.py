import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


def test_signals_endpoint(client):
    r = client.get("/api/signals?days=30")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_performance_stats(client):
    r = client.get("/api/performance/stats?period=2w")
    assert r.status_code == 200
    data = r.json()
    assert "signal_count" in data
    assert "avg_return_pct" in data


def test_performance_signals_list(client):
    r = client.get("/api/performance/signals?limit=10")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_performance_stats_accepts_all_valid_periods(client):
    for period in ("1w", "2w", "4w", "8w"):
        r = client.get(f"/api/performance/stats?period={period}")
        assert r.status_code == 200, f"period={period} should be valid"
        assert r.json()["period"] == period


def test_performance_stats_rejects_unknown_period(client):
    """허용 외 period 는 422 — 현재는 존재하지 않는 컬럼으로 500."""
    r = client.get("/api/performance/stats?period=3w")
    assert r.status_code == 422


def test_performance_stats_rejects_sql_injection(client):
    """period 가 f-string 으로 컬럼명에 보간되므로 주입 문자열은 422 로 차단되어야 한다."""
    payload = "1w_pct) FROM signal_performance;--"
    r = client.get("/api/performance/stats", params={"period": payload})
    assert r.status_code == 422


def test_signals_ticker_filter(client, db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM signal_performance WHERE symbol LIKE 'SIGTKR%'")
            cur.execute("DELETE FROM entry_params WHERE symbol LIKE 'SIGTKR%'")
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'SIGTKR%'")
            cur.execute(
                """INSERT INTO stocks (ticker, name, market, sector, listed_at)
                   VALUES ('SIGTKR01','T1','KOSPI','반도체','2020-01-01'),
                          ('SIGTKR02','T2','KOSPI','보험','2020-01-01')"""
            )
            cur.execute(
                """INSERT INTO entry_params
                     (symbol, signal_at, entry_price, stop_loss,
                      trigger_evaluation_at, prior_classification_at)
                   VALUES
                     ('SIGTKR01', NOW() - INTERVAL '1 day', 100, 90, NOW(), NOW()),
                     ('SIGTKR02', NOW() - INTERVAL '1 day', 200, 180, NOW(), NOW())"""
            )
        db.commit()
        r = client.get("/api/signals?ticker=SIGTKR01&days=7")
        syms = {row["symbol"] for row in r.json()}
        assert syms == {"SIGTKR01"}
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_performance_signals_ticker_filter(client, db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM signal_performance WHERE symbol LIKE 'PERFTKR%'")
            cur.execute("DELETE FROM entry_params WHERE symbol LIKE 'PERFTKR%'")
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'PERFTKR%'")
            cur.execute(
                """INSERT INTO stocks (ticker, name, market, sector, listed_at)
                   VALUES ('PERFTKR01','T1','KOSPI','반도체','2020-01-01'),
                          ('PERFTKR02','T2','KOSPI','보험','2020-01-01')"""
            )
            cur.execute(
                """INSERT INTO entry_params
                     (symbol, signal_at, entry_price, stop_loss,
                      trigger_evaluation_at, prior_classification_at)
                   VALUES
                     ('PERFTKR01', NOW() - INTERVAL '7 day', 100, 90, NOW(), NOW()),
                     ('PERFTKR02', NOW() - INTERVAL '7 day', 200, 180, NOW(), NOW())"""
            )
            cur.execute(
                """INSERT INTO signal_performance
                     (symbol, signal_at, entry_price, return_2w_pct)
                   VALUES
                     ('PERFTKR01', (SELECT signal_at FROM entry_params WHERE symbol='PERFTKR01'), 100, 5.0),
                     ('PERFTKR02', (SELECT signal_at FROM entry_params WHERE symbol='PERFTKR02'), 200, -3.0)"""
            )
        db.commit()
        r = client.get("/api/performance/signals?ticker=PERFTKR01")
        syms = {row["symbol"] for row in r.json()}
        assert syms == {"PERFTKR01"}
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_signals_tolerates_null_prices_and_zero_trigger(client, db):
    """entry_price/stop_loss 는 NULLABLE — NULL 행 하나로 /api/signals 전체가
    500 나면 안 된다. 또한 trigger_price=0(Decimal)이 falsy 체크로 None 으로
    오변환되면 안 된다."""
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM entry_params WHERE symbol='NULSIG1'")
            cur.execute("DELETE FROM stocks WHERE ticker='NULSIG1'")
            cur.execute(
                """INSERT INTO stocks (ticker, name, market, sector, listed_at)
                   VALUES ('NULSIG1','N','KOSPI','테스트','2020-01-01')"""
            )
            cur.execute(
                """INSERT INTO entry_params
                     (symbol, signal_at, entry_price, stop_loss, trigger_price,
                      trigger_evaluation_at, prior_classification_at)
                   VALUES ('NULSIG1', NOW(), NULL, NULL, 0, NOW(), NOW())"""
            )
        db.commit()

        r = client.get("/api/signals?ticker=NULSIG1&days=7")
        assert r.status_code == 200, f"NULL 가격 행으로 500: {r.text[:200]}"
        row = r.json()[0]
        assert row["entry_price"] is None
        assert row["stop_loss"] is None
        assert row["trigger_price"] == 0.0, "Decimal(0) 이 falsy 체크로 None 오변환"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM entry_params WHERE symbol='NULSIG1'")
            cur.execute("DELETE FROM stocks WHERE ticker='NULSIG1'")
        db.commit()
        app.dependency_overrides.pop(get_conn, None)
