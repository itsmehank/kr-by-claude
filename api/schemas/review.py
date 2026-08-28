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
    # #132 — 합성 이력(classification_backfill, 현재 프롬프트 재생성) 여부. 세대 표기.
    backfilled: bool = False
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


class StreakAnalysisOut(BaseModel):
    symbol: str
    key_date: date
    classified_at: datetime
    source: str
    classification: str
    pattern: str | None = None
    pivot_price: float | None = None
    backfilled: bool
    triggers: list[ReviewTriggerOut] = []


class StreakMetricsOut(BaseModel):
    stage: str
    t5_pct: float | None = None
    t20_pct: float | None = None
    max_reach_pct: float | None = None
    corp_action_flag: bool = False
    first_breakout_at: date | None = None


class StreakOut(BaseModel):
    start: date
    end: date | None = None
    closed_by: str | None = None
    closed_reason: str | None = None
    censored: bool
    backfilled: bool
    has_gap: bool
    stage: str
    analyses: list[StreakAnalysisOut] = []
    metrics: StreakMetricsOut


class StockLatestOut(BaseModel):
    status: str
    closed_by: str | None = None
    stage: str
    t5_pct: float | None = None
    t20_pct: float | None = None
    max_reach_pct: float | None = None
    corp_action_flag: bool = False
    first_breakout_at: date | None = None
    censored: bool
    backfilled: bool
    streak_count: int


class StockRowOut(BaseModel):
    symbol: str
    name: str | None = None
    market: str | None = None
    latest: StockLatestOut
    streaks: list[StreakOut] = []
    series: list[tuple[date, float]] = []
    pivot_steps: list[tuple[date, date | None, float]] = []


class StockRowsResponse(BaseModel):
    rows: list[StockRowOut]
    orphan_trigger_count: int
