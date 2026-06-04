import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.deps import get_conn


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


def test_pipeline_detail_includes_component_of(client, db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        r = client.get("/api/pipelines/ohlcv")
        assert r.status_code == 200
        assert r.json().get("component_of") == "data-daily"
        # 통합 스펙은 component_of 없음(None)
        r2 = client.get("/api/pipelines/data-daily")
        assert r2.json().get("component_of") is None
    finally:
        app.dependency_overrides.pop(get_conn, None)
