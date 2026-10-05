# tests/test_api_positions.py — (#47) 포지션 조회 API
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_conn, None)


@pytest.fixture
def seed_position(db):
    from kr_pipeline.trade_management.store import open_position
    with db.cursor() as cur:
        cur.execute("DELETE FROM position_stop_evaluations WHERE position_id IN "
                    "(SELECT id FROM positions WHERE symbol='APITEST1')")
        cur.execute("DELETE FROM positions WHERE symbol='APITEST1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES "
                    "('APITEST1','에이피아이','KOSPI') ON CONFLICT DO NOTHING")
    pid = open_position(db, symbol="APITEST1", entry_date=date(2026, 7, 1),
                        entry_price=10000.0)
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO position_stop_evaluations
               (position_id, eval_date, close, effective_stop, binding,
                breakeven_armed, triggered)
               VALUES (%s, '2026-07-10', 10500, 9200, 'initial_stop', FALSE, FALSE)""",
            (pid,))
    db.commit()
    yield pid
    with db.cursor() as cur:
        cur.execute("DELETE FROM position_stop_evaluations WHERE position_id=%s", (pid,))
        cur.execute("DELETE FROM positions WHERE id=%s", (pid,))
        cur.execute("DELETE FROM stocks WHERE ticker='APITEST1'")
    db.commit()


def test_list_positions_with_latest_eval(client, seed_position):
    r = client.get("/api/positions?status=open")
    assert r.status_code == 200
    mine = [p for p in r.json() if p["symbol"] == "APITEST1"]
    assert len(mine) == 1
    p = mine[0]
    assert p["entry_price"] == 10000.0 and p["name"] == "에이피아이"
    assert p["last_eval"]["effective_stop"] == 9200.0
    assert p["last_eval"]["binding"] == "initial_stop"
    assert p["last_eval"]["triggered"] is False


def test_list_evaluations(client, seed_position):
    r = client.get(f"/api/positions/{seed_position}/evaluations")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["close"] == 10500.0


def test_list_positions_exposes_volume_regime_flag(client, seed_position, db):
    """최신 보유 climax(T2) 평가의 volume_regime_flag 를 노출(spec D9 PR-3). decline 행은 읽지 않는다(같은 창·같은 값 — 회신 23 Q-D)."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO position_climax_evaluations (position_id, eval_date, fired, suppressed, hold_days, triggers, mode, volume_regime_flag) "
                    "VALUES (%s, '2026-10-01', FALSE, FALSE, 1, '[]', 'quality', 'mixed')", (seed_position,))
        cur.execute("INSERT INTO position_decline_evaluations (position_id, eval_date, fired, hold_days, signals, mode, climax_also_fired, volume_regime_flag) "
                    "VALUES (%s, '2026-10-01', FALSE, 1, '[]', 'quality', FALSE, NULL)", (seed_position,))
    db.commit()
    try:
        p = [x for x in client.get("/api/positions?status=open").json() if x["symbol"] == "APITEST1"][0]
        assert p["volume_regime_flag"] == "mixed"
        with db.cursor() as cur:                                  # decline 행의 값은 노출에 영향 없음
            cur.execute("UPDATE position_climax_evaluations SET volume_regime_flag = NULL WHERE position_id=%s", (seed_position,))
            cur.execute("UPDATE position_decline_evaluations SET volume_regime_flag = 'mixed' WHERE position_id=%s", (seed_position,))
        db.commit()
        p = [x for x in client.get("/api/positions?status=open").json() if x["symbol"] == "APITEST1"][0]
        assert p["volume_regime_flag"] is None
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM position_climax_evaluations WHERE position_id=%s", (seed_position,))
            cur.execute("DELETE FROM position_decline_evaluations WHERE position_id=%s", (seed_position,))
        db.commit()
