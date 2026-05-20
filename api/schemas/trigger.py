from datetime import datetime
from pydantic import BaseModel


class TriggerOut(BaseModel):
    symbol: str
    name: str | None = None
    market: str | None = None
    evaluated_at: datetime
    trigger_type: str
    close: float | None = None
    volume: int | None = None
    avg_volume_50d_ratio: float | None = None
    pivot_price: float | None = None
    pivot_delta_pct: float | None = None
    decision: str
    confidence: float | None = None
    reasoning: str | None = None
    abort_reason: str | None = None
