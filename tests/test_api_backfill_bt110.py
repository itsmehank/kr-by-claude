"""(#242) /api/backfill/bt110 — 스위치는 DB 값만 바꾼다. 분류 결과 미노출."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client(db):
    app.dependency_overrides[get_conn] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_status_without_row(client):
    r = client.get("/api/backfill/bt110/status")
    assert r.status_code == 200
    d = r.json()
    assert d["exists"] is False and d["enabled"] is False and d["cells_count"] == 0
    assert d["slice"] == [["2021-01-02", "2021-12-25"], ["2024-01-06", "2024-12-28"]]


def test_switch_on_then_off_keeps_snapshot(client, monkeypatch):
    import kr_pipeline.backtest.bt110 as bt110
    monkeypatch.setattr(bt110, "enumerate_cells", lambda conn, slice_, groups=None: [["T1", "2021-01-02", "KOSPI"]])
    r = client.post("/api/backfill/bt110/switch", json={"enabled": True, "note": "test"})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["cells_count"] == 1
    s = client.get("/api/backfill/bt110/status").json()
    assert s["enabled"] is True and s["cells_count"] == 1 and s["progress"]["target"] == 1
    assert "verdict" not in str(s) and "classification" not in str(s)   # 미열람 보존 — 결과 키 없음
    r = client.post("/api/backfill/bt110/switch", json={"enabled": False})
    assert r.json()["enabled"] is False and r.json()["cells_count"] == 1


def test_switch_rejects_bad_body(client):
    assert client.post("/api/backfill/bt110/switch", json={}).status_code == 422
