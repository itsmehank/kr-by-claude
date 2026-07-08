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


def test_volume_ratio_zero_is_not_none(client, db):
    """P2: volume_ratio_50d = 0(무거래일)이 None('데이터 없음')으로 위장되면 안 된다.

    `if r[n] else None` 은 Decimal('0') 을 falsy 로 오변환 — signals.py 는
    이미 `is not None` 으로 고쳐진 선례(주석 포함)가 있는데 indicators 2곳에
    옛 패턴이 잔존.
    """
    def override_get_conn():
        yield db
    app.dependency_overrides[get_conn] = override_get_conn
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_indicators WHERE ticker LIKE 'VRZ%'")
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'VRZ%'")
            cur.execute(
                "INSERT INTO stocks (ticker, name, market, sector) "
                "VALUES ('VRZ01','무거래','KOSPI','테스트섹터VRZ')"
            )
            cur.execute(
                """INSERT INTO daily_indicators
                     (ticker, date, adj_close, rs_rating, minervini_pass, volume_ratio_50d)
                   VALUES ('VRZ01','2026-05-15',1000.0, 95, TRUE, 0)"""
            )
        db.commit()

        # by-sector 경로
        r = client.get("/api/indicators/by-sector?sector=테스트섹터VRZ&date_=2026-05-15&limit=10")
        assert r.status_code == 200
        row = next(x for x in r.json() if x["ticker"] == "VRZ01")
        assert row["volume_ratio_50d"] == 0.0, f"0 이 None 으로 위장: {row['volume_ratio_50d']!r}"

        # minervini-passed 경로
        r2 = client.get("/api/indicators/minervini-passed?date_=2026-05-15&min_rs=70&limit=500")
        assert r2.status_code == 200
        row2 = next((x for x in r2.json() if x["ticker"] == "VRZ01"), None)
        assert row2 is not None, "seed 종목이 minervini-passed 응답에 없음"
        assert row2["volume_ratio_50d"] == 0.0, f"0 이 None 으로 위장: {row2['volume_ratio_50d']!r}"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_indicators WHERE ticker LIKE 'VRZ%'")
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'VRZ%'")
        db.commit()
        app.dependency_overrides.pop(get_conn, None)
