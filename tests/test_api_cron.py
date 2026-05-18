import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_status_returns_required_fields(client, mocker):
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.get_current_crontab",
        return_value="",
    )
    r = client.get("/api/cron/status")
    assert r.status_code == 200
    data = r.json()
    assert "registered" in data
    assert "lines" in data
    assert "default_lines" in data


def test_preview_register_shows_diff(client, mocker):
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.get_current_crontab",
        return_value="0 5 * * * /backup\n",
    )
    r = client.get("/api/cron/preview?action=register")
    assert r.status_code == 200
    data = r.json()
    assert "diff" in data
    assert "new_crontab_preview" in data


def test_register_calls_install(client, mocker, tmp_path):
    state = {"crontab": "0 5 * * * /backup\n"}

    def fake_get():
        return state["crontab"]

    def fake_install(text):
        state["crontab"] = text

    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.get_current_crontab",
        side_effect=fake_get,
    )
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.install_crontab",
        side_effect=fake_install,
    )
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.BACKUP_DIR",
        tmp_path,
    )

    r = client.post("/api/cron/register")
    assert r.status_code == 200
    data = r.json()
    assert data["registered"] is True
    assert "kr-by-claude-llm-runner" in state["crontab"]


def test_unregister(client, mocker, tmp_path):
    from kr_pipeline.llm_runner.cron_manager import BEGIN_MARKER, END_MARKER

    initial = f"""0 5 * * * /backup
{BEGIN_MARKER}
30 16 * * 1-5 /path/llm_runner
{END_MARKER}
0 6 * * * /other"""
    state = {"crontab": initial}

    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.get_current_crontab",
        side_effect=lambda: state["crontab"],
    )
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.install_crontab",
        side_effect=lambda t: state.update(crontab=t),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.BACKUP_DIR",
        tmp_path,
    )

    r = client.post("/api/cron/unregister")
    assert r.status_code == 200
    assert "kr-by-claude-llm-runner" not in state["crontab"]
