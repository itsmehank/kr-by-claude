"""그룹별 토큰버킷 — 초기 한도, 헤더 보정, 경로→그룹 매핑, Retry-After."""
from kr_trading.toss.ratelimit import GROUP_LIMITS, RateLimiter, group_for_path


def test_group_limits_seed():
    assert GROUP_LIMITS["ACCOUNT"] == 1 and GROUP_LIMITS["ORDER"] == 10 and GROUP_LIMITS["MARKET_DATA"] == 15


def test_group_for_path():
    assert group_for_path("/oauth2/token") == "AUTH"
    assert group_for_path("/api/v1/accounts") == "ACCOUNT"
    assert group_for_path("/api/v1/holdings") == "ASSET"
    assert group_for_path("/api/v1/prices") == "MARKET_DATA"
    assert group_for_path("/api/v1/orderbook") == "MARKET_DATA"
    assert group_for_path("/api/v1/price-limits") == "MARKET_DATA"
    assert group_for_path("/api/v1/stocks/005930/warnings") == "STOCK"
    assert group_for_path("/api/v1/orders") == "ORDER"
    assert group_for_path("/api/v1/orders/abc/cancel") == "ORDER"
    assert group_for_path("/api/v1/orders/abc") == "ORDER_HISTORY"
    assert group_for_path("/api/v1/buying-power") == "ORDER_INFO"
    assert group_for_path("/api/v1/sellable-quantity") == "ORDER_INFO"
    assert group_for_path("/api/v1/commissions") == "ORDER_INFO"


def test_acquire_sleeps_when_bucket_empty():
    now = [0.0]
    slept = []
    rl = RateLimiter(clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    rl.acquire("ACCOUNT")            # 용량 1 → 소진
    rl.acquire("ACCOUNT")            # 재충전 1초 필요
    assert len(slept) == 1 and 0.9 <= slept[0] <= 1.0


def test_update_from_headers_changes_capacity():
    # fake sleep 은 fake clock 을 반드시 전진시킨다 — 실제 time.sleep 이 time.monotonic 을
    # 전진시키는 것과 동형. 전진하지 않는 fake 는 acquire 의 재충전 루프를 영원히 굶긴다.
    now = [0.0]
    slept = []
    rl = RateLimiter(clock=lambda: now[0],
                     sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    rl.update_from_headers("ORDER", {"X-RateLimit-Limit": "2"})
    rl.acquire("ORDER"); rl.acquire("ORDER")
    assert slept == []
    rl.acquire("ORDER")
    # wait = (1 - 0) / capacity → 보정이 적용됐으면 0.5, 초기값 10 이면 0.1
    assert len(slept) == 1 and abs(slept[0] - 0.5) < 1e-9


def test_retry_after():
    rl = RateLimiter()
    assert rl.retry_after_seconds({"Retry-After": "3"}) == 3.0
    assert rl.retry_after_seconds({}) is None
