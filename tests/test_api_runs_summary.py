"""GET /api/runs/summary — 모드별 마지막 실행 + 다음 스케줄."""
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_summary_returns_all_modes(client):
    r = client.get("/api/runs/summary")
    assert r.status_code == 200
    data = r.json()
    assert "modes" in data
    mode_names = {m["mode"] for m in data["modes"]}
    assert {"weekend", "full-daily", "performance"}.issubset(mode_names)


def test_summary_each_mode_has_required_fields(client):
    r = client.get("/api/runs/summary")
    data = r.json()
    for m in data["modes"]:
        assert "mode" in m
        assert "pipeline" in m
        assert "last_run" in m   # None or {id, status, started_at, ...}
        assert "next_scheduled" in m  # ISO string or null
        assert "cron_expression" in m
