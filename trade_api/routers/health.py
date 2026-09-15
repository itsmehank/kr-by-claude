from fastapi import APIRouter, Depends

from kr_trading.config import TradeConfig
from trade_api.deps import get_cfg
from trade_api.schemas import HealthOut

router = APIRouter(prefix="/trade-api", tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(cfg: TradeConfig = Depends(get_cfg)) -> HealthOut:
    return HealthOut(dryRun=cfg.dry_run, maxOrderKrw=cfg.max_order_krw,
                     maxDailyKrw=cfg.max_daily_krw, accountSeq=cfg.account_seq)
