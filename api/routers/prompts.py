import io
import zipfile
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg import Connection

from api.deps import get_conn
from api.services.freeze_store import fetch_latest_freeze, read_artifact_from_uri
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
def get_zip(
    ticker: str,
    mode: Optional[str] = Query(default=None),
    conn: Connection = Depends(get_conn),
):
    """분석 ZIP 반환.

    mode=verify 시:
    - weekend → daily_delta 순으로 frozen 검색.
    - 있으면 file:// 에서 읽어 반환 + X-Freeze-Origin=frozen.
    - 없으면 build_analysis_zip 재빌드 + X-Freeze-Origin=rebuilt
      + X-Freeze-Warning='원본 아님 (재빌드됨)…'.
    """
    from api.services.integrity_guard import DataIntegrityError

    if mode == "verify":
        for stage in ("weekend", "daily_delta"):
            frozen = fetch_latest_freeze(conn, ticker, stage)
            if frozen:
                try:
                    zip_bytes = read_artifact_from_uri(frozen.artifact_uri)
                except Exception:
                    continue  # 파일 없으면 다음 stage 시도
                today = date.today().isoformat().replace("-", "")
                return Response(
                    content=zip_bytes,
                    media_type="application/zip",
                    headers={
                        "Content-Disposition": f'attachment; filename="analysis-{ticker}-{today}.zip"',
                        "X-Freeze-Origin": "frozen",
                        "X-Freeze-Stage": frozen.stage,
                        "X-Freeze-Frozen-At": frozen.frozen_at.isoformat(),
                    },
                )
        # frozen 없음 → 재빌드 + warning
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
                "Content-Disposition": f'attachment; filename="analysis-{ticker}-{today}.zip"',
                "X-Freeze-Origin": "rebuilt",
                "X-Freeze-Warning": "not-original (rebuilt) -- freeze not available for classification time",
            },
        )

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
