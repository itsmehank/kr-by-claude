import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


def test_by_sector_returns_stocks_in_sector(client, db):
    """sector=금융 으로 조회하면 그 섹터의 종목들만 반환."""
    def override_get_conn():
        yield db
    app.dependency_overrides[get_conn] = override_get_conn
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_indicators WHERE date='2026-05-15' AND ticker LIKE 'BYSEC%'")
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'BYSEC%'")
            cur.execute(
                """INSERT INTO stocks (ticker, name, market, sector, listed_at)
                   VALUES ('BYSEC01','금융A','KOSPI','금융','2020-01-01'),
                          ('BYSEC02','금융B','KOSPI','금융','2020-01-01'),
                          ('BYSEC03','반도체A','KOSPI','반도체','2020-01-01')"""
            )
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, adj_close, rs_rating, minervini_pass)
                   VALUES ('BYSEC01','2026-05-15',1000.0, 85, TRUE),
                          ('BYSEC02','2026-05-15',2000.0, 60, FALSE),
                          ('BYSEC03','2026-05-15',3000.0, 90, TRUE)"""
            )
        db.commit()

        r = client.get("/api/indicators/by-sector?sector=금융&date_=2026-05-15&limit=10")
        assert r.status_code == 200
        data = r.json()
        tickers = {row["ticker"] for row in data}
        assert "BYSEC01" in tickers
        assert "BYSEC02" in tickers
        assert "BYSEC03" not in tickers  # 반도체 sector

        # RS desc 정렬
        rs_list = [row["rs_rating"] for row in data if row["rs_rating"] is not None]
        assert rs_list == sorted(rs_list, reverse=True)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_by_sector_includes_minervini_pass_flag(client, db):
    """각 row 에 minervini_pass 필드 포함."""
    def override_get_conn():
        yield db
    app.dependency_overrides[get_conn] = override_get_conn
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_indicators WHERE date='2026-05-15' AND ticker = 'BYSECMP'")
            cur.execute("DELETE FROM stocks WHERE ticker = 'BYSECMP'")
            cur.execute(
                """INSERT INTO stocks (ticker, name, market, sector, listed_at)
                   VALUES ('BYSECMP','TestMP','KOSPI','보험','2020-01-01')"""
            )
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, adj_close, rs_rating, minervini_pass)
                   VALUES ('BYSECMP','2026-05-15',500.0, 75, TRUE)"""
            )
        db.commit()

        r = client.get("/api/indicators/by-sector?sector=보험&date_=2026-05-15")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        for row in data:
            assert "minervini_pass" in row
            assert isinstance(row["minervini_pass"], bool)
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_by_sector_respects_limit(client):
    """limit 파라미터 동작."""
    r = client.get("/api/indicators/by-sector?sector=금융&limit=5")
    assert r.status_code == 200
    assert len(r.json()) <= 5
