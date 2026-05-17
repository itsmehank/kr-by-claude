from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_signals_endpoint():
    r = client.get("/api/signals?days=30")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_performance_stats():
    r = client.get("/api/performance/stats?period=2w")
    assert r.status_code == 200
    data = r.json()
    assert "signal_count" in data
    assert "avg_return_pct" in data


def test_performance_signals_list():
    r = client.get("/api/performance/signals?limit=10")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
