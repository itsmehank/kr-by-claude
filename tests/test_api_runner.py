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
    fake_proc.poll.return_value = 0  # 초단기 정상 종료 → 등록 대기 즉시 통과
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
    fake_proc.poll.return_value = 0  # 초단기 정상 종료 → 등록 대기 즉시 통과
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


def test_run_returns_error_when_child_dies_before_registering(client, db, mocker):
    """spawn 직후 자식이 run 행 등록 전에 즉사(argparse exit 2, import error 등)하면
    API 가 200+pid 를 돌려주고 pipeline_runs 엔 아무것도 안 남아 '눌렀는데 아무 일
    없음'이 된다. 즉사를 감지해 502 로 가시화해야 한다."""
    from api.deps import get_conn

    def override():
        yield db
    app.dependency_overrides[get_conn] = override

    fake_proc = mocker.Mock()
    fake_proc.pid = 77777
    fake_proc.poll.return_value = 2       # 이미 종료 (argparse exit 2)
    fake_proc.returncode = 2
    mocker.patch("subprocess.Popen", return_value=fake_proc)

    try:
        r = client.post("/api/runner/run", json={
            "pipeline_id": "universe", "mode_id": "default", "force": True,
        })
        assert r.status_code == 502, f"자식 즉사가 가시화되지 않음: {r.status_code}"
        assert "exit" in r.json()["detail"]["message"] or "종료" in r.json()["detail"]["message"]
    finally:
        app.dependency_overrides.pop(get_conn, None)


def test_batch_zip_skips_integrity_failure_per_ticker(client, mocker):
    """batch ZIP: 1종목의 DataIntegrityError 가 전체 503 으로 번지면 안 된다 —
    그 종목만 skip + manifest 사유 기록, 나머지는 정상 포함."""
    import io, zipfile
    from api.services.integrity_guard import DataIntegrityError
    from datetime import date as _date

    def fake_build(conn, t, **kw):
        if t == "BADT1":
            raise DataIntegrityError(
                ticker=t, on_date=_date(2026, 6, 10), column="adj_close",
                p_value=100.0, i_value=50.0,
            )
        return b"PK\x03\x04fake"
    mocker.patch("api.routers.prompts.build_analysis_zip", side_effect=fake_build)

    r = client.get("/api/prompts/batch.zip?tickers=GOODT1,BADT1")
    assert r.status_code == 200, f"1종목 integrity 실패로 전체 {r.status_code}"
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        assert "analysis-GOODT1.zip" in names
        assert "analysis-BADT1.zip" not in names
        manifest = z.read("manifest.txt").decode()
    assert "BADT1" in manifest and ("integrity" in manifest or "정합" in manifest)
