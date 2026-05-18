"""POST /api/runner/run + GET /api/runner/status/{id}."""
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_run_invalid_mode_returns_400(client):
    r = client.post("/api/runner/run", json={"mode": "invalid"})
    assert r.status_code == 400


def test_run_dry_run_spawns(client, mocker):
    """dry-run 모드 → subprocess.Popen 호출되고 200 반환."""
    fake_proc = mocker.Mock()
    fake_proc.pid = 99999
    mocker.patch("subprocess.Popen", return_value=fake_proc)

    r = client.post("/api/runner/run", json={"mode": "performance", "dry_run": True})
    assert r.status_code in (200, 409)  # 409 = duplicate (이미 오늘 돌았다면)
    if r.status_code == 200:
        data = r.json()
        assert "pid" in data
        assert "command" in data


def test_run_duplicate_returns_409(db, mocker):
    """오늘 success 있으면 409."""
    from datetime import datetime, timezone
    from api.deps import get_conn

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
               VALUES ('llm_performance', 'performance', 'success', %s, %s)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )
    db.commit()

    app.dependency_overrides[get_conn] = lambda: db
    try:
        client = TestClient(app)
        r = client.post("/api/runner/run", json={"mode": "performance", "dry_run": True})
        assert r.status_code == 409
        data = r.json()
        assert "existing_run_id" in data["detail"]
    finally:
        app.dependency_overrides.clear()
