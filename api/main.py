"""FastAPI 앱 진입점."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import init_pool, close_pool
from api.routers import stocks, indicators, heatmap, render, prompts, runs, market_context, signals, performance, runner, pipelines, classifications, triggers, index, positions
from api.routers import cron as cron_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()   # 요청당 신규 TCP 연결 대신 풀 재사용
    try:
        yield
    finally:
        close_pool()


app = FastAPI(title="kr-by-claude API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(stocks.router)
app.include_router(indicators.router)
app.include_router(heatmap.router)
app.include_router(render.router)
app.include_router(prompts.router)
app.include_router(runs.router)
app.include_router(market_context.router)
app.include_router(signals.router)
app.include_router(performance.router)
app.include_router(runner.router)
app.include_router(cron_router.router)
app.include_router(pipelines.router)
app.include_router(classifications.router)
app.include_router(triggers.router)
app.include_router(index.router)
app.include_router(positions.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
