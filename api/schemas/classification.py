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
    base_high: float | None
    base_low: float | None
    base_depth_pct: float | None
    base_start_date: date | None
    risk_flags: list[str]
    confidence: float | None
    reasoning: str | None
    source: str
    classified_at: datetime
    expires_at: datetime | None
    llm_call_duration_s: float | None
    llm_input_tokens: int | None
    llm_output_tokens: int | None
