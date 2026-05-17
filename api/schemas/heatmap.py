from datetime import date as _date
from pydantic import BaseModel


class SectorHeatmapOut(BaseModel):
    sector: str
    stock_count: int
    avg_rs_rating: float | None = None
    minervini_pass_count: int = 0
    minervini_pass_rate: float = 0.0
    avg_return_pct: float | None = None


class SectorTimeseriesPoint(BaseModel):
    date: _date
    value: float


class SectorTimeseries(BaseModel):
    sector: str
    points: list[SectorTimeseriesPoint]


class SectorTimeseriesResponse(BaseModel):
    lookback_days: int
    series: list[SectorTimeseries]
