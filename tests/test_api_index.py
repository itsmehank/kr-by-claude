import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_index(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override

    with db.cursor() as cur:
        cur.execute("DELETE FROM index_daily WHERE index_code IN ('IDXTEST1','IDXTEST2')")
        cur.execute(
            """INSERT INTO index_daily
                 (index_code, date, open, high, low, close, volume)
               VALUES
                 ('IDXTEST1','2026-05-18',2540.10,2562.00,2535.70,2558.30,412345678),
                 ('IDXTEST1','2026-05-19',2558.30,2570.00,2550.00,2565.50,400000000),
                 ('IDXTEST1','2026-05-20',2565.50,2580.10,2560.00,2575.00,420000000),
                 ('IDXTEST2','2026-05-20', 850.00, 860.50, 845.00, 855.10,180000000)"""
        )
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_unknown_index_returns_empty(client, seed_index):
    r = client.get("/api/index/daily/9999")
    assert r.status_code == 200
    assert r.json() == []


def test_returns_rows_ordered_asc(client, seed_index):
    r = client.get("/api/index/daily/IDXTEST1?start=2026-05-18&end=2026-05-20")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    assert [row["date"] for row in rows] == ["2026-05-18", "2026-05-19", "2026-05-20"]
    assert rows[0]["close"] == 2558.30
    assert rows[2]["close"] == 2575.00
    assert rows[0]["volume"] == 412345678


def test_start_end_filter(client, seed_index):
    r = client.get("/api/index/daily/IDXTEST1?start=2026-05-19&end=2026-05-20")
    dates = [row["date"] for row in r.json()]
    assert dates == ["2026-05-19", "2026-05-20"]


def test_default_window_returns_recent(client, seed_index):
    r = client.get("/api/index/daily/IDXTEST1")
    dates = {row["date"] for row in r.json()}
    assert {"2026-05-18", "2026-05-19", "2026-05-20"}.issubset(dates)
