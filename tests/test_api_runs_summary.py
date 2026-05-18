"""GET /api/runs/summary — pipeline 별 마지막 실행 + 다음 스케줄."""
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_summary_returns_all_pipelines(client):
    r = client.get("/api/runs/summary")
    assert r.status_code == 200
    data = r.json()
    assert "pipelines" in data
    pipeline_ids = {p["pipeline_id"] for p in data["pipelines"]}
    assert {"llm-full-daily", "llm-weekend", "llm-performance"}.issubset(pipeline_ids)


def test_summary_each_pipeline_has_required_fields(client):
    r = client.get("/api/runs/summary")
    data = r.json()
    for p in data["pipelines"]:
        assert "pipeline_id" in p
        assert "group" in p
        assert "label" in p
        assert "last_run" in p   # None or {id, status, started_at, ...}
        assert "next_scheduled" in p  # ISO string or null
        assert "cron_expression" in p
        assert "modes" in p
