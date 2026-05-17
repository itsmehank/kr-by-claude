from pydantic import BaseModel


class SectorHeatmapOut(BaseModel):
    sector: str
    stock_count: int
    avg_rs_rating: float | None = None
    minervini_pass_count: int = 0
    minervini_pass_rate: float = 0.0
