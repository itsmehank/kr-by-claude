"""토스증권 매매 API (:8001). 분석 API(api.main, :8000)와 별도 프로세스 — spec §4.

  uv run uvicorn trade_api.main:app --port 8001      # --workers 금지(토큰 1개), --reload 기본 미사용

토스 호출 코드는 이 프로세스에만 존재한다(CLAUDE.md 운영규칙 6).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from kr_trading.toss.errors import GuardError, TossApiError
from trade_api import deps
from trade_api.routers import accounts, health

log = logging.getLogger("trade_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    deps.init_singletons()
    cfg = deps.get_cfg()
    log.warning("trade_api 기동 — dry_run=%s max_order_krw=%s max_daily_krw=%s account_seq=%s",
                cfg.dry_run, cfg.max_order_krw, cfg.max_daily_krw, cfg.account_seq)
    try:
        yield
    finally:
        deps.close_singletons()


app = FastAPI(title="kr-by-claude trade API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=False,
                   allow_methods=["GET", "POST"], allow_headers=["*"])


@app.exception_handler(TossApiError)
async def _toss_error(_: Request, e: TossApiError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={"error": {
        "code": e.code, "message": e.message, "data": e.data, "requestId": e.request_id}})


@app.exception_handler(GuardError)
async def _guard_error(_: Request, e: GuardError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": {
        "code": e.code, "message": e.message, "data": e.data, "requestId": None}})


app.include_router(health.router)
app.include_router(accounts.router)
