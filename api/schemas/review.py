from datetime import date, datetime

from pydantic import BaseModel


class ReviewTriggerOut(BaseModel):
    evaluated_at: datetime
    d: date
    trigger_type: str
    decision: str
    close: float | None = None
    pivot_price: float | None = None
    reasoning: str | None = None


class ReviewRowOut(BaseModel):
    symbol: str
    name: str | None = None
    market: str | None = None
    source: str
    classified_at: datetime
    analyzed_for_date: date | None = None
    key_date: date
    classification: str
    pattern: str | None = None
    pivot_price: float | None = None
    status: str
    first_breakout_at: date | None = None
    first_breakout_type: str | None = None
    first_breakout_decision: str | None = None
    promotion_at: date | None = None
    trigger_count: int
    t5_pct: float | None = None
    t20_pct: float | None = None
    max_reach_pct: float | None = None
    corp_action_flag: bool = False
    spark: list[float] = []
    pivot_baseline: float | None = None
    triggers: list[ReviewTriggerOut] = []


class ReviewResponse(BaseModel):
    rows: list[ReviewRowOut]
    orphan_trigger_count: int
