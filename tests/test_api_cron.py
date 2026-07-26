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


def test_register_disabled(client, mocker):
    """register 는 launchd 이전(#86) 후 하드 차단 — 409, crontab 미변경."""
    installed = mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.install_crontab"
    )
    r = client.post("/api/cron/register")
    assert r.status_code == 409
    assert "launchd" in r.json()["detail"]
    installed.assert_not_called()  # 실제 crontab 설치 시도 자체가 없어야


def test_unregister_disabled(client, mocker):
    """unregister 는 데이터 cron 전멸 위험 — 하드 차단 409, crontab 미변경."""
    installed = mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.install_crontab"
    )
    r = client.post("/api/cron/unregister")
    assert r.status_code == 409
    assert "launchd" in r.json()["detail"]
    installed.assert_not_called()
