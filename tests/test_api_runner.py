"""POST /api/runner/run."""
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_run_invalid_pipeline_returns_400(client):
    r = client.post("/api/runner/run", json={"pipeline_id": "invalid", "mode_id": "default"})
    assert r.status_code in (400, 409)


def test_run_universe_spawns(client, mocker):
    fake_proc = mocker.Mock()
    fake_proc.pid = 99999
    mocker.patch("subprocess.Popen", return_value=fake_proc)

    r = client.post("/api/runner/run", json={"pipeline_id": "universe", "mode_id": "default"})
    assert r.status_code in (200, 409)  # 409 = duplicate (이미 오늘 돌았다면)
    if r.status_code == 200:
        data = r.json()
        assert "pid" in data
        assert "command" in data
        assert data["pipeline_id"] == "universe"


def test_run_duplicate_returns_409(client, db):
    from datetime import datetime, timezone
    from api.deps import get_conn

    def override_get_conn():
        yield db

    app.dependency_overrides[get_conn] = override_get_conn
    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
                   VALUES ('llm_performance', 'performance', 'success', %s, %s)""",
                (datetime.now(timezone.utc), datetime.now(timezone.utc)),
            )
        db.commit()

        r = client.post("/api/runner/run", json={"pipeline_id": "llm-performance", "mode_id": "default"})
        assert r.status_code == 409
        assert "existing_run_id" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_conn, None)
