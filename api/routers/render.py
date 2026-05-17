from fastapi import APIRouter, Depends, Response
from psycopg import Connection

from api.deps import get_conn
from api.services.chart_render import render_daily_chart, render_weekly_chart


router = APIRouter(prefix="/api/render", tags=["render"])


@router.get("/{ticker}/daily.png")
def render_daily(ticker: str, range_days: int = 365, conn: Connection = Depends(get_conn)):
    png_bytes = render_daily_chart(conn, ticker, range_days)
    return Response(content=png_bytes, media_type="image/png")


@router.get("/{ticker}/weekly.png")
def render_weekly(ticker: str, range_weeks: int = 104, conn: Connection = Depends(get_conn)):
    png_bytes = render_weekly_chart(conn, ticker, range_weeks)
    return Response(content=png_bytes, media_type="image/png")
