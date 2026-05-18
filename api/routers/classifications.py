from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection

from api.deps import get_conn
from api.schemas.classification import ClassificationRow


router = APIRouter(prefix="/api/classifications", tags=["classifications"])


SORT_CLAUSES = {
    "classified_at_desc": "l.classified_at DESC",
    "confidence_desc": "l.confidence DESC NULLS LAST, l.classified_at DESC",
}


@router.get("", response_model=list[ClassificationRow])
def get_classifications(
    lookback_days: int = 14,
    classifications: list[str] | None = Query(default=None),
    sources: list[str] | None = Query(default=None),
    min_confidence: float = 0.0,
    sort: str = "classified_at_desc",
    limit: int = 100,
    conn: Connection = Depends(get_conn),
):
    """LLM 분류 결과 — 종목별 최신 1건 (DISTINCT ON), 필터 + 정렬 + 제한."""
    if sort not in SORT_CLAUSES:
        raise HTTPException(400, f"Unknown sort: {sort}. Allowed: {list(SORT_CLAUSES.keys())}")
    sort_clause = SORT_CLAUSES[sort]

    sql = f"""
        WITH latest AS (
          SELECT DISTINCT ON (symbol)
                 symbol, classified_at, market, classification, pattern,
                 pivot_price, pivot_basis, base_high, base_low, base_depth_pct,
                 base_start_date, risk_flags, confidence, reasoning, source,
                 expires_at, llm_call_duration_s, llm_input_tokens, llm_output_tokens
            FROM weekly_classification
           WHERE classified_at >= NOW() - (%(lookback_days)s || ' days')::interval
           ORDER BY symbol, classified_at DESC
        )
        SELECT l.symbol, s.name, l.market, s.sector,
               l.classification, l.pattern, l.pivot_price, l.pivot_basis,
               l.base_high, l.base_low, l.base_depth_pct, l.base_start_date,
               l.risk_flags, l.confidence, l.reasoning, l.source,
               l.classified_at, l.expires_at,
               l.llm_call_duration_s, l.llm_input_tokens, l.llm_output_tokens
          FROM latest l
          JOIN stocks s ON s.ticker = l.symbol
         WHERE (%(classifications)s::text[] IS NULL OR l.classification = ANY(%(classifications)s::text[]))
           AND (%(sources)s::text[] IS NULL OR l.source = ANY(%(sources)s::text[]))
           AND COALESCE(l.confidence, 0) >= %(min_confidence)s
         ORDER BY {sort_clause}
         LIMIT %(limit)s
    """

    params = {
        "lookback_days": lookback_days,
        "classifications": classifications,
        "sources": sources,
        "min_confidence": min_confidence,
        "limit": limit,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    result = []
    for r in rows:
        rf = r[12] if r[12] is not None else []
        result.append(ClassificationRow(
            symbol=r[0],
            name=r[1],
            market=r[2],
            sector=r[3],
            classification=r[4],
            pattern=r[5],
            pivot_price=float(r[6]) if r[6] is not None else None,
            pivot_basis=r[7],
            base_high=float(r[8]) if r[8] is not None else None,
            base_low=float(r[9]) if r[9] is not None else None,
            base_depth_pct=float(r[10]) if r[10] is not None else None,
            base_start_date=r[11],
            risk_flags=rf if isinstance(rf, list) else [],
            confidence=float(r[13]) if r[13] is not None else None,
            reasoning=r[14],
            source=r[15],
            classified_at=r[16],
            expires_at=r[17],
            llm_call_duration_s=float(r[18]) if r[18] is not None else None,
            llm_input_tokens=r[19],
            llm_output_tokens=r[20],
        ))
    return result
