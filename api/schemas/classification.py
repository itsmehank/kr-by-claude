from datetime import date, datetime
from pydantic import BaseModel


class ClassificationRow(BaseModel):
    symbol: str
    name: str
    market: str
    sector: str | None
    classification: str
    pattern: str | None
    pivot_price: float | None
    pivot_basis: str | None
    # (#253) 래칫 적용 후 트리거 기준 pivot — 판독값(pivot_price)과 다를 수 있음. 레거시 행은 None.
    effective_pivot: float | None = None
    base_high: float | None
    base_low: float | None
    base_depth_pct: float | None
    base_start_date: date | None
    risk_flags: list[str]
    confidence: float | None
    reasoning: str | None
    source: str
    classified_at: datetime
    analyzed_for_date: date | None
    llm_call_duration_s: float | None
    llm_input_tokens: int | None
    llm_output_tokens: int | None


class ClassificationHistoryRow(BaseModel):
    symbol: str
    date: date
    classification: str
    source: str
    pattern: str | None = None       # disqualified/구형 행은 NULL
    confidence: float | None = None
    reasoning: str | None = None
    # 그 분석이 제시한 pivot(돌파 기준가) — 실격/미확정 행은 NULL (#149)
    pivot_price: float | None = None
    # (#253) 래칫 적용 후 트리거 기준 pivot — 라이브 행만(백필 행·레거시 행은 None)
    effective_pivot: float | None = None
