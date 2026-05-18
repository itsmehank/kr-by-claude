import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_list_pipelines_returns_all_specs(client):
    r = client.get("/api/pipelines")
    assert r.status_code == 200
    data = r.json()
    assert "pipelines" in data
    ids = {p["id"] for p in data["pipelines"]}
    assert {"universe", "ohlcv", "weekly", "corporate-actions",
            "indicators-daily", "indicators-weekly", "market-context",
            "llm-full-daily", "llm-weekend", "llm-performance"}.issubset(ids)


def test_summary_includes_all_pipelines(client):
    r = client.get("/api/runs/summary")
    assert r.status_code == 200
    data = r.json()
    assert "pipelines" in data
    assert len(data["pipelines"]) >= 10
    for p in data["pipelines"]:
        assert "pipeline_id" in p
        assert "group" in p
        assert "label" in p
        assert "last_run" in p
        assert "next_scheduled" in p
        assert "modes" in p
