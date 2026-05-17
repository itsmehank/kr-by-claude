from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg import Connection

from api.deps import get_conn
from api.services.zip_builder import build_analysis_zip


router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("/{ticker}.zip")
def get_zip(ticker: str, conn: Connection = Depends(get_conn)):
    try:
        zip_bytes = build_analysis_zip(conn, ticker)
    except ValueError as e:
        raise HTTPException(404, str(e))
    today = date.today().isoformat().replace("-", "")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="analysis-{ticker}-{today}.zip"'},
    )
