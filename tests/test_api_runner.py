"""POST /api/runner/run."""
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_run_invalid_pipeline_returns_400(client):
    r = client.post("/api/runner/run", json={"pipeline_id": "invalid", "mode_id": "default"})
    assert r.status_code in (400, 409)


def test_run_universe_spawns(client, mocker):
    fake_proc = mocker.Mock()
    fake_proc.pid = 99999
    mocker.patch("subprocess.Popen", return_value=fake_proc)

    r = client.post("/api/runner/run", json={"pipeline_id": "universe", "mode_id": "default"})
    assert r.status_code in (200, 409)  # 409 = duplicate (이미 오늘 돌았다면)
    if r.status_code == 200:
        data = r.json()
        assert "pid" in data
        assert "command" in data
        assert data["pipeline_id"] == "universe"


def test_run_with_params(client, mocker):
    fake_proc = mocker.Mock()
    fake_proc.pid = 11111
    mock_popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    r = client.post("/api/runner/run", json={
        "pipeline_id": "ohlcv",
        "mode_id": "backfill",
        "force": True,  # 오늘 success 있어도 강제 실행
        "params": {"years": 3}
    })
    assert r.status_code in (200, 409)
    if r.status_code == 200:
        args = mock_popen.call_args[0][0]
        assert "--years=3" in args


def test_run_duplicate_returns_409(client, db):
    from datetime import datetime, timezone
    from api.deps import get_conn

    def override_get_conn():
        yield db

    app.dependency_overrides[get_conn] = override_get_conn
    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
                   VALUES ('llm_performance', 'performance', 'success', %s, %s)""",
                (datetime.now(timezone.utc), datetime.now(timezone.utc)),
            )
        db.commit()

        r = client.post("/api/runner/run", json={"pipeline_id": "llm-performance", "mode_id": "default"})
        assert r.status_code == 409
        assert "existing_run_id" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_run_concurrent_request_blocked_by_advisory_lock(client, db, test_db_url, mocker):
    """check_can_run(SELECT)→spawn(Popen) 사이에 잠금이 없어, 더블클릭 동시 요청
    2건이 모두 check 를 통과해 같은 파이프라인이 2개 실행될 수 있다(TOCTOU).
    advisory lock 으로 check+spawn 을 직렬화 — 락 선점 중이면 409."""
    import psycopg
    from api.deps import get_conn

    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    mocker.patch("subprocess.Popen")  # 혹시 통과해도 실 spawn 방지

    # 동시 요청 1번째 흉내: 다른 세션이 같은 파이프라인 락 보유
    other = psycopg.connect(test_db_url)
    try:
        with other.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtext('runner:universe')::bigint)")

        r = client.post("/api/runner/run", json={
            "pipeline_id": "universe", "mode_id": "default", "force": True,
        })
        assert r.status_code == 409, f"동시 요청이 차단되지 않음: {r.status_code}"
        assert r.json()["detail"]["reason"] == "concurrent_request"
    finally:
        other.close()  # 세션 종료로 락 해제
        app.dependency_overrides.pop(get_conn, None)
