from datetime import datetime
from pydantic import BaseModel


class SignalOut(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None
    market: str | None = None
    signal_at: datetime
    entry_mode: str | None = None
    trigger_price: float | None = None
    entry_price: float
    stop_loss: float
    stop_loss_pct_from_pivot: float | None = None
    stop_loss_pct_from_current_price: float | None = None
    expected_target_price: float | None = None
    expected_target_pct: float | None = None
    risk_reward_ratio: float | None = None
    position_size_pct: float | None = None
    known_warnings: list[str] = []
    notes: str | None = None


class PerformanceStats(BaseModel):
    period: str
    signal_count: int
    avg_return_pct: float | None = None
    avg_market_return_pct: float | None = None
    outperform_pct: float | None = None
    win_rate: float | None = None
