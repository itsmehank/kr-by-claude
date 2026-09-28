"""/api/issues 라우터 — 목록(open 만)·override·refresh 시작/상태/503."""
import pytest
from fastapi.testclient import TestClient

from api.deps import get_conn
from api.main import app
from api.services.issue_brief.github import IssueRaw
from api.services.issue_brief.store import mark_closed, set_brief, upsert_observed
from api.services.issue_brief.summarize import Brief
import api.routers.issues as issues_router
import api.services.issue_brief.refresh as refresh_mod

N1, N2 = 920001, 920002


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_conn, None)


@pytest.fixture
def seeded(db):
    def raw(n):
        return IssueRaw(number=n, title=f"t{n}", body="", labels=("x",),
                        updated_at="2026-09-27T00:00:00Z", comments=())
    upsert_observed(db, raw(N1))
    upsert_observed(db, raw(N2))
    set_brief(db, N1, Brief(summary="s", group="ops", start_status="ready",
                            start_reason="r", depends_on=[]), "m", "h")
    mark_closed(db, [N2])
    db.commit()
    yield
    with db.cursor() as cur:
        cur.execute("DELETE FROM issue_briefs WHERE number IN (%s, %s)", (N1, N2))
    db.commit()


def test_list_returns_open_only_with_brief(client, seeded):
    r = client.get("/api/issues")
    assert r.status_code == 200
    items = {i["number"]: i for i in r.json()["items"]}
    assert N1 in items and N2 not in items
    assert items[N1]["brief"]["summary"] == "s" and r.json()["updated_at"] is not None
    assert N2 in r.json()["closed_numbers"] and N1 not in r.json()["closed_numbers"]


def test_override_put_and_clear_and_404(client, seeded):
    r = client.put(f"/api/issues/{N1}/override", json={"status": "blocked", "note": "n"})
    assert r.status_code == 200 and r.json()["override_status"] == "blocked"
    r = client.put(f"/api/issues/{N1}/override", json={"status": None, "note": None})
    assert r.json()["override_status"] is None
    assert client.put("/api/issues/1/override", json={"status": "ready"}).status_code == 404
    assert client.put(f"/api/issues/{N1}/override", json={"status": "weird"}).status_code == 422


def test_refresh_status_get(client, monkeypatch):
    monkeypatch.setattr(refresh_mod, "STATE", refresh_mod.RefreshState(total=3, done=1, running=True))
    r = client.get("/api/issues/refresh")
    assert r.status_code == 200 and r.json()["total"] == 3 and r.json()["running"] is True


def test_refresh_post_starts_or_409(client, monkeypatch):
    monkeypatch.setattr(issues_router, "gh_available", lambda: (True, ""))
    monkeypatch.setattr(issues_router, "is_running", lambda: False)
    started = [True, False]
    monkeypatch.setattr(issues_router, "start_refresh", lambda: started.pop(0))
    assert client.post("/api/issues/refresh").status_code == 202
    r = client.post("/api/issues/refresh")
    assert r.status_code == 409 and r.json()["reason"] == "already_running"


def test_refresh_post_409_checked_before_gh_probe(client, monkeypatch):
    probed = []
    monkeypatch.setattr(issues_router, "gh_available", lambda: probed.append(1) or (True, ""))
    monkeypatch.setattr(issues_router, "is_running", lambda: True)
    r = client.post("/api/issues/refresh")
    assert r.status_code == 409 and probed == []


def test_refresh_delete_cancels_or_409(client, monkeypatch):
    monkeypatch.setattr(issues_router, "request_cancel", lambda: True)
    r = client.delete("/api/issues/refresh")
    assert r.status_code == 202 and r.json()["cancel_requested"] is True
    monkeypatch.setattr(issues_router, "request_cancel", lambda: False)
    r = client.delete("/api/issues/refresh")
    assert r.status_code == 409 and r.json()["reason"] == "not_running"


def test_refresh_post_503_without_gh(client, monkeypatch):
    monkeypatch.setattr(issues_router, "is_running", lambda: False)
    monkeypatch.setattr(issues_router, "gh_available", lambda: (False, "not logged in"))
    r = client.post("/api/issues/refresh")
    assert r.status_code == 503 and r.json()["reason"] == "gh_unavailable"
    assert r.json()["detail"] == "not logged in"
