from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg import Connection

from kr_pipeline.common.config import Config


@contextmanager
def connect(url: str | None = None) -> Iterator[Connection]:
    target = url or Config.load().database_url
    conn = psycopg.connect(target, autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
