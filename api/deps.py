"""FastAPI 의존성."""
from typing import Generator

from psycopg import Connection
from psycopg_pool import ConnectionPool

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect

# lifespan(api.main)에서 init_pool/close_pool 로 관리. 테스트 등 lifespan 밖
# 호출은 _pool=None → 기존 per-request 연결 폴백 (동작 계약 동일).
_pool: ConnectionPool | None = None


def init_pool() -> None:
    global _pool
    _pool = ConnectionPool(
        Config.load().database_url,
        min_size=1,
        max_size=10,
        open=True,
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_conn() -> Generator[Connection, None, None]:
    """FastAPI Depends 용 DB connection.

    풀 사용 시: pool.connection() 컨텍스트가 성공 commit / 예외 rollback 후
    풀에 반환 — 기존 connect() 컨텍스트와 같은 트랜잭션 의미.
    풀 부재 시(lifespan 밖): 기존 per-request 연결 (요청마다 Config 파싱 +
    신규 TCP — 차트/배치 ZIP 처럼 다쿼리 엔드포인트에서 누적 오버헤드).
    """
    if _pool is not None:
        with _pool.connection() as conn:
            yield conn
        return
    cfg = Config.load()
    with connect(cfg.database_url) as conn:
        yield conn
