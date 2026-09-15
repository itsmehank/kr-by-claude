"""trade_api 의존성 — TradeConfig·TossClient·PreviewStore 프로세스 싱글톤 + DB 풀(api/deps.py 동형).

토스 토큰은 클라이언트당 1개 → TossClient(=TokenManager) 는 이 프로세스에 정확히 1개.
테스트는 set_test_overrides 로 MockTransport 클라이언트를 주입(토스 접촉 0).
"""
from __future__ import annotations

import os
from typing import Callable, Generator
from urllib.parse import urlparse

from psycopg import Connection
from psycopg_pool import ConnectionPool

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect
from kr_trading.config import TradeConfig
from kr_trading.preview import PreviewStore
from kr_trading.toss.client import TossClient

_pool: ConnectionPool | None = None
_cfg: TradeConfig | None = None
_toss: TossClient | None = None
_preview: PreviewStore | None = None
_reset_hooks: list[Callable[[], None]] = []   # 상태를 가진 라우터가 등록 — deps 는 라우터를 import 하지 않는다(계층 방향 유지)


def register_reset_hook(fn: Callable[[], None]) -> None:
    _reset_hooks.append(fn)


def _run_reset_hooks() -> None:
    for fn in _reset_hooks:
        fn()


def init_singletons() -> None:
    global _pool, _cfg, _toss, _preview
    _cfg = _cfg or TradeConfig.load()
    _toss = _toss or TossClient(_cfg)
    _preview = _preview or PreviewStore()
    if _pool is None:
        _pool = ConnectionPool(Config.load().database_url, min_size=1, max_size=5, open=True)


def close_singletons() -> None:
    """프로세스 종료 시 정리. DB 풀은 close(), 토스 HTTP 클라이언트도 함께 닫는다.

    TossClient 는 close() 를 노출하지 않지만(httpx.Client 를 내부 보유), 소켓/커넥션
    누수 없이 정상 종료하려면 여기서 닫아야 한다 — 단일 장수 프로세스라 실제 위험은
    작지만(프로세스 종료 시 OS 가 회수), lifespan finally 에서 명시적으로 정리하는 편이
    재기동(uvicorn --reload 등) 시 소켓 누적을 막는다. TossClient._http 는 private 이지만
    현재 이 클래스에 공개 close() 가 없어(Task 5 리뷰 기록) 여기서만 최소로 접근한다.
    """
    global _pool, _toss
    if _pool is not None:
        _pool.close()
        _pool = None
    if _toss is not None:
        _toss._http.close()
        _toss = None


def set_test_overrides(*, cfg: TradeConfig | None = None, toss: TossClient | None = None,
                       preview: PreviewStore | None = None) -> None:
    global _cfg, _toss, _preview
    if cfg is not None: _cfg = cfg
    if toss is not None:
        _toss = toss
        _run_reset_hooks()          # 클라이언트 교체 시 라우터 캐시(예: accounts) 무효화 — 설계로 보장
    if preview is not None: _preview = preview


def reset_overrides() -> None:
    global _cfg, _toss, _preview
    _cfg = _toss = _preview = None
    _run_reset_hooks()


def get_cfg() -> TradeConfig:
    global _cfg
    if _cfg is None:
        _cfg = TradeConfig.load()
    return _cfg


def get_toss() -> TossClient:
    global _toss
    if _toss is None:
        _toss = TossClient(get_cfg())
    return _toss


def get_preview() -> PreviewStore:
    global _preview
    if _preview is None:
        _preview = PreviewStore()
    return _preview


def get_conn() -> Generator[Connection, None, None]:
    if _pool is not None:
        with _pool.connection() as conn:
            yield conn
        return
    url = Config.load().database_url
    if os.environ.get("PYTEST_CURRENT_TEST") and "test" not in urlparse(url).path.rsplit("/", 1)[-1]:
        raise RuntimeError(
            "trade_api get_conn: pytest 에서 비-test DB 폴백 금지 — dependency_overrides 누락"
        )
    with connect(url) as conn:
        yield conn
