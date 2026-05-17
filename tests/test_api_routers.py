"""FastAPI 라우터 통합 테스트."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_stocks(client):
    r = client.get("/api/stocks?limit=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_stock_not_found(client):
    r = client.get("/api/stocks/NOEXIST_TICKER")
    assert r.status_code == 404


def test_get_daily_indicators(client):
    r = client.get("/api/indicators/daily/NOEXIST?start=2026-01-01&end=2026-01-31")
    assert r.status_code == 200
    assert r.json() == []


def test_get_minervini_passed(client):
    r = client.get("/api/indicators/minervini-passed?min_rs=80&limit=10")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_sectors_heatmap(client):
    r = client.get("/api/heatmap/sectors")
    assert r.status_code == 200


def test_get_market_context(client):
    r = client.get("/api/market-context")
    assert r.status_code == 200


def test_list_runs(client):
    r = client.get("/api/runs?limit=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_zip_not_found(client):
    r = client.get("/api/prompts/NOEXIST_TICKER.zip")
    assert r.status_code == 404
