from datetime import date
from pydantic import BaseModel


class DailyIndicatorOut(BaseModel):
    date: date
    adj_close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    avg_volume_50d: float | None = None
    sma_10: float | None = None
    sma_21: float | None = None
    sma_50: float | None = None
    sma_150: float | None = None
    sma_200: float | None = None
    w52_high: float | None = None
    w52_low: float | None = None
    rs_line: float | None = None
    rs_rating: int | None = None
    minervini_pass: bool | None = None
    volume_ratio_50d: float | None = None
    pocket_pivot_flag: bool | None = None
    distribution_day_flag: bool | None = None
    drawdown_filter_pass: bool | None = None
    drawdown_52w_pct: float | None = None


class MinerviniPassedOut(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    rs_rating: int
    adj_close: float
    volume_ratio_50d: float | None = None
    pocket_pivot_flag: bool | None = None


class SectorStockOut(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    market: str
    rs_rating: int | None = None
    adj_close: float
    volume_ratio_50d: float | None = None
    pocket_pivot_flag: bool | None = None
    minervini_pass: bool


class WeeklyIndicatorOut(BaseModel):
    date: date  # week_end_date
    adj_close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    sma_10w: float | None = None
    sma_30w: float | None = None
    sma_40w: float | None = None
    w52_high: float | None = None
    w52_low: float | None = None
    rs_line: float | None = None
    rs_rating: int | None = None
    minervini_pass: bool | None = None
