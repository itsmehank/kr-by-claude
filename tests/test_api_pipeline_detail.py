import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


def test_get_pipeline_detail_200(client):
    r = client.get("/api/pipelines/indicators-daily")
    assert r.status_code == 200
    data = r.json()
    for key in [
        "id", "group", "label", "description", "long_description",
        "module", "schedule_label", "default_cron",
        "inputs", "outputs", "depends_on", "consumed_by",
        "modes", "recent_runs",
    ]:
        assert key in data, f"missing key: {key}"
    assert data["id"] == "indicators-daily"


def test_get_pipeline_detail_404(client):
    r = client.get("/api/pipelines/nonexistent")
    assert r.status_code == 404


def test_consumed_by_reverse_lookup(client):
    """ohlcv 의 consumed_by 에 weekly, indicators-daily, llm-performance, market-context, llm-full-daily 가 포함되어야 함."""
    r = client.get("/api/pipelines/ohlcv")
    assert r.status_code == 200
    consumed_ids = {p["id"] for p in r.json()["consumed_by"]}
    assert {"weekly", "indicators-daily", "llm-performance", "market-context", "llm-full-daily"}.issubset(consumed_ids)


def test_depends_on_includes_label(client):
    """depends_on 각 항목은 {id, label} 페어여야 함."""
    r = client.get("/api/pipelines/indicators-daily")
    deps = r.json()["depends_on"]
    assert len(deps) == 2
    for dep in deps:
        assert "id" in dep
        assert "label" in dep
        assert isinstance(dep["label"], str)


def test_recent_runs_filtered_by_mode_prefix(client, db):
    """indicators-daily 의 recent_runs 는 'daily-' prefix 만 포함해야 함."""
    def override_get_conn():
        yield db
    app.dependency_overrides[get_conn] = override_get_conn
    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at, rows_affected)
                   VALUES ('indicators', 'daily-incremental', 'success', %s, %s, 100),
                          ('indicators', 'weekly-incremental', 'success', %s, %s, 50)""",
                (datetime.now(timezone.utc), datetime.now(timezone.utc),
                 datetime.now(timezone.utc), datetime.now(timezone.utc)),
            )
        db.commit()

        r = client.get("/api/pipelines/indicators-daily")
        assert r.status_code == 200
        modes = [run["mode"] for run in r.json()["recent_runs"]]
        for m in modes:
            assert m.startswith("daily-"), f"weekly 모드가 포함됨: {m}"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_recent_runs_limit_5(client):
    """recent_runs 는 최대 5건."""
    r = client.get("/api/pipelines/ohlcv")
    assert r.status_code == 200
    assert len(r.json()["recent_runs"]) <= 5


def test_modes_include_is_heavy(client):
    """modes 응답이 is_heavy 필드 포함."""
    r = client.get("/api/pipelines/ohlcv")
    modes = r.json()["modes"]
    assert len(modes) > 0
    for m in modes:
        assert "is_heavy" in m
        assert isinstance(m["is_heavy"], bool)


def test_recent_runs_include_total_count(client, db):
    """recent_runs 의 각 row 에 total_count 필드 포함 (NULL 가능)."""
    def override_get_conn():
        yield db
    app.dependency_overrides[get_conn] = override_get_conn
    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at, rows_affected, total_count)
                   VALUES ('indicators', 'daily-incremental', 'success', %s, %s, 65, 65)""",
                (datetime.now(timezone.utc), datetime.now(timezone.utc)),
            )
        db.commit()

        r = client.get("/api/pipelines/indicators-daily")
        assert r.status_code == 200
        for run in r.json()["recent_runs"]:
            assert "total_count" in run
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_recent_runs_include_details(client):
    """recent_runs 의 각 row 에 details 필드 포함 (NULL 가능)."""
    r = client.get("/api/pipelines/llm-full-daily")
    assert r.status_code == 200
    for run in r.json()["recent_runs"]:
        assert "details" in run
