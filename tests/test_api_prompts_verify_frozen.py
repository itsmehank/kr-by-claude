"""verify endpoint — frozen 우선 + warning 헤더 테스트."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.freeze_store import save_freeze


@pytest.fixture
def client():
    return TestClient(app)


def test_verify_mode_returns_frozen_when_available(db, tmp_path, monkeypatch):
    """freeze 가 있을 때 verify mode 는 frozen ZIP 반환 + X-Freeze-Origin=frozen."""
    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)

    fake_zip = b"PK\x03\x04frozen content"
    rec = save_freeze(
        db,
        artifact_bytes=fake_zip,
        content_type="application/zip",
        ticker="005850",
        stage="weekend",
        classification_id=None,
    )
    assert rec is not None

    # 라우터가 test DB conn 을 사용하도록 override
    from api.deps import get_conn
    from api.main import app

    def override_get_conn():
        yield db

    app.dependency_overrides[get_conn] = override_get_conn
    try:
        client = TestClient(app)
        resp = client.get("/api/prompts/005850.zip?mode=verify")
        assert resp.status_code == 200
        assert resp.content == fake_zip
        assert resp.headers.get("X-Freeze-Origin") == "frozen"
        assert resp.headers.get("X-Freeze-Stage") == "weekend"
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_verify_mode_falls_back_with_warning_when_no_freeze(db, tmp_path, monkeypatch):
    """freeze 없을 때 verify mode 는 재빌드 + X-Freeze-Origin=rebuilt + warning."""
    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)

    from api.deps import get_conn
    from api.main import app

    def override_get_conn():
        yield db

    fake_rebuilt = b"PK\x03\x04rebuilt zip"
    monkeypatch.setattr(
        "api.routers.prompts.build_analysis_zip",
        lambda *a, **k: fake_rebuilt,
    )

    app.dependency_overrides[get_conn] = override_get_conn
    try:
        client = TestClient(app)
        resp = client.get("/api/prompts/UNKNOWN_TICKER.zip?mode=verify")
        assert resp.status_code == 200
        assert resp.content == fake_rebuilt
        assert resp.headers.get("X-Freeze-Origin") == "rebuilt"
        warning = resp.headers.get("X-Freeze-Warning", "")
        assert warning  # warning header must be present
    finally:
        app.dependency_overrides.pop(get_conn, None)
