import io
import zipfile
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg import Connection

from api.deps import get_conn
from api.services.zip_builder import build_analysis_zip


router = APIRouter(prefix="/api/prompts", tags=["prompts"])


MAX_BATCH_TICKERS = 200


@router.get("/batch.zip")
def batch_zip(
    tickers: str,
    conn: Connection = Depends(get_conn),
):
    """여러 종목의 분석 ZIP 을 묶어서 하나의 outer ZIP 으로 반환.

    Query: tickers=A,B,C (comma-separated). 최대 200개.
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(400, "No tickers provided")
    if len(ticker_list) > MAX_BATCH_TICKERS:
        raise HTTPException(
            400, f"Too many tickers (max {MAX_BATCH_TICKERS})"
        )

    buf = io.BytesIO()
    skipped: list[str] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as outer:
        for t in ticker_list:
            try:
                inner_bytes = build_analysis_zip(conn, t)
                outer.writestr(f"analysis-{t}.zip", inner_bytes)
            except ValueError:
                skipped.append(t)
                continue
            except Exception as e:
                # Re-raise data integrity errors as 503 to signal transient/data issue
                from api.services.integrity_guard import DataIntegrityError
                if isinstance(e, DataIntegrityError):
                    raise HTTPException(status_code=503, detail=str(e))
                raise

        manifest_lines = [
            f"# Batch analysis package — {date.today().isoformat()}",
            f"# Included: {len(ticker_list) - len(skipped)} tickers",
            f"# Skipped:  {len(skipped)} tickers",
            "",
        ]
        for t in ticker_list:
            if t in skipped:
                manifest_lines.append(f"  - {t}  [SKIPPED — not found]")
            else:
                manifest_lines.append(f"  - {t}")
        outer.writestr("manifest.txt", "\n".join(manifest_lines))

    today = date.today().isoformat().replace("-", "")
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="analysis-batch-{today}.zip"'
        },
    )


@router.get("/{ticker}.zip")
def get_zip(ticker: str, conn: Connection = Depends(get_conn)):
    from api.services.integrity_guard import DataIntegrityError
    try:
        zip_bytes = build_analysis_zip(conn, ticker)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except DataIntegrityError as e:
        raise HTTPException(status_code=503, detail=str(e))
    today = date.today().isoformat().replace("-", "")
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="analysis-{ticker}-{today}.zip"'
        },
    )
