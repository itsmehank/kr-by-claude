"""FastAPI 앱 진입점."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import stocks, indicators, heatmap, render, prompts, runs, market_context


app = FastAPI(title="kr-by-claude API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(stocks.router)
app.include_router(indicators.router)
app.include_router(heatmap.router)
app.include_router(render.router)
app.include_router(prompts.router)
app.include_router(runs.router)
app.include_router(market_context.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
