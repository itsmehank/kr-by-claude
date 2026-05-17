from datetime import date
from pydantic import BaseModel


class StockOut(BaseModel):
    ticker: str
    name: str
    market: str
    sector: str | None = None
    delisted_at: date | None = None
