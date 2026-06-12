"""API DB 연결 풀 — lifespan 풀 사용 + 풀 부재 시 per-request 폴백."""
from fastapi.testclient import TestClient

from api.main import app
from api import deps


def test_lifespan_opens_pool_and_serves_requests():
    """with TestClient(앱) = lifespan 실행 → 풀 생성, 요청은 풀 커넥션 사용.

    기존엔 요청마다 Config.load()+신규 TCP 연결 — 차트/배치 ZIP 처럼 요청당
    수십 쿼리를 날리는 엔드포인트에서 누적 오버헤드가 컸다."""
    with TestClient(app) as client:
        assert deps._pool is not None, "lifespan 에서 풀이 생성되어야 함"
        r = client.get("/api/performance/stats?period=2w")
        assert r.status_code == 200
    assert deps._pool is None, "lifespan 종료 시 풀 정리"


def test_get_conn_falls_back_without_pool():
    """lifespan 밖(기존 테스트들의 TestClient(app) 직접 사용)에선 풀 없이
    per-request 연결 폴백 — 기존 테스트·동작 계약 유지."""
    assert deps._pool is None
    client = TestClient(app)  # 컨텍스트 없이 = lifespan 미실행
    r = client.get("/api/performance/stats?period=2w")
    assert r.status_code == 200
