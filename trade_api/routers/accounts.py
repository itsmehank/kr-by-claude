"""GET /trade-api/accounts — 계좌 헤더 불필요. TOSS_ACCOUNT_SEQ 미설정 상태에서 accountSeq 확인용.
ACCOUNT 그룹 1/s → 5분 캐시."""
import time

from fastapi import APIRouter, Depends

from kr_trading.toss.client import TossClient
from kr_trading.toss.models import Account
from trade_api.deps import get_toss, register_reset_hook

router = APIRouter(prefix="/trade-api", tags=["accounts"])
_cache: tuple[float, list[Account]] | None = None
CACHE_TTL = 300.0


def reset_cache() -> None:
    """테스트/클라이언트 교체 시 모듈 레벨 캐시 누수 방지 — deps 의 리셋 훅 레지스트리에 등록."""
    global _cache
    _cache = None


register_reset_hook(reset_cache)   # deps 가 accounts 를 import 하는 대신 accounts 가 등록


@router.get("/accounts", response_model=list[Account])
def accounts(toss: TossClient = Depends(get_toss)) -> list[Account]:
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < CACHE_TTL:
        return _cache[1]
    out = toss.accounts()
    _cache = (now, out)
    return out
