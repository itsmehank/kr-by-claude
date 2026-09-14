"""OrderGuard — spec §5 1~8 규칙별 표 케이스. IO 없음."""
from decimal import Decimal

import pytest

from kr_trading.config import TradeConfig
from kr_trading.guard import check_order, order_amount_krw
from kr_trading.toss.errors import GuardError
from kr_trading.toss.models import OrderCreateRequest

CFG = TradeConfig(client_id="", client_secret="", account_seq=1, base_url="x", dry_run=True,
                  max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
D = Decimal


def buy(qty="10", price="70000", order_type="LIMIT", side="BUY"):
    return OrderCreateRequest(symbol="005930", side=side, orderType=order_type,
                              quantity=D(qty), price=D(price) if price is not None else None)


def run(req, **kw):
    base = dict(cfg=CFG, upper_limit=D("91000"), lower_limit=D("49000"), daily_buy_total=D("0"), sellable_qty=None)
    base.update(kw)
    return check_order(req, **base)


def test_limit_ok():
    r = run(buy())
    assert r.amount_krw == D("700000") and r.amount_basis == "limit"


@pytest.mark.parametrize("req,code", [
    (buy(price=None), "guard/price-required"),
    (buy(order_type="MARKET", price="70000"), "guard/price-forbidden"),
    (buy(qty="0"), "guard/quantity-invalid"),
    (buy(qty="1.5"), "guard/quantity-invalid"),
    (buy(price="70050"), "guard/tick-size"),           # 5만~20만 구간 tick 100
    (buy(price="95000"), "guard/price-out-of-range"),  # 상한 91000 초과
    (buy(price="48000"), "guard/price-out-of-range"),  # 하한 49000 미달
    (buy(qty="100", price="70000"), "guard/max-order-amount"),   # 700만 > 500만
])
def test_rejections_in_order(req, code):
    with pytest.raises(GuardError) as ei:
        run(req)
    assert ei.value.code == code


def test_tick_size_error_carries_correct_tick():
    with pytest.raises(GuardError) as ei:
        run(buy(price="70050"))
    assert ei.value.data == {"tickSize": "100"}


def test_market_uses_upper_limit_basis():
    r = run(buy(order_type="MARKET", price=None, qty="10"))
    assert r.amount_krw == D("910000") and r.amount_basis == "upper_limit"


def test_market_without_upper_limit_is_blocked():
    with pytest.raises(GuardError) as ei:
        run(buy(order_type="MARKET", price=None), upper_limit=None)
    assert ei.value.code == "guard/price-limit-unavailable"


def test_daily_cap_counts_existing_total():
    with pytest.raises(GuardError) as ei:
        run(buy(qty="50", price="70000"), daily_buy_total=D("7000000"))   # 350만 + 700만 > 1000만
    assert ei.value.code == "guard/max-daily-amount"
    assert ei.value.data["dailyTotalKrw"] == "7000000"


def test_daily_cap_skipped_for_modify_recheck():
    r = run(buy(qty="50", price="70000"), daily_buy_total=D("7000000"), count_toward_daily=False)
    assert r.amount_krw == D("3500000")


def test_sell_is_exempt_from_daily_cap_but_checks_sellable():
    r = run(buy(side="SELL", qty="5"), daily_buy_total=D("99000000"), sellable_qty=D("5"))
    assert r.amount_krw == D("350000")
    with pytest.raises(GuardError) as ei:
        run(buy(side="SELL", qty="6"), sellable_qty=D("5"))
    assert ei.value.code == "guard/sellable-exceeded"


def test_high_value_flags():
    big = TradeConfig(**{**CFG.__dict__, "max_order_krw": D("99999999999"), "max_daily_krw": D("99999999999")})
    with pytest.raises(GuardError) as ei:
        run(buy(qty="2000", price="70000"), cfg=big)   # 1.4억, confirm 없음
    assert ei.value.code == "guard/confirm-high-value-required"
    ok = OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT", quantity=D("2000"),
                            price=D("70000"), confirmHighValueOrder=True)
    assert "high_value" in run(ok, cfg=big).warnings
    with pytest.raises(GuardError) as ei:
        run(OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT", quantity=D("50000"),
                               price=D("70000"), confirmHighValueOrder=True), cfg=big)   # 35억
    assert ei.value.code == "guard/max-order-amount-exceeded"


def test_order_amount_krw_direct():
    assert order_amount_krw(buy(), None) == D("700000")
    assert order_amount_krw(buy(order_type="MARKET", price=None), D("91000")) == D("910000")
