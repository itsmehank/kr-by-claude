"""FastAPI 의존성."""
from typing import Generator

from psycopg import Connection

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect


def get_conn() -> Generator[Connection, None, None]:
    """FastAPI Depends 용 DB connection.

    Yield 후 자동 commit/rollback/close (connect() 의 컨텍스트 매니저 사용).
    """
    cfg = Config.load()
    with connect(cfg.database_url) as conn:
        yield conn
