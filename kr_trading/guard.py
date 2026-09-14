"""OrderGuard (spec §5 1~8) — 순수 함수. 하나라도 걸리면 GuardError, 토스 주문 API 미호출.

호가단위 판정은 kr_pipeline/common/krx.py:krx_tick_size 재사용(신설 금지). 로컬 검증은
API 왕복 전 편의이며 최종 판정권은 API(에러 data 에 올바른 단위가 옴).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from kr_pipeline.common.krx import krx_tick_size
from kr_trading.config import TradeConfig
from kr_trading.toss.errors import GuardError
from kr_trading.toss.models import OrderCreateRequest

HIGH_VALUE_KRW = Decimal("100000000")        # 1억 — confirmHighValueOrder 필수
MAX_ORDER_KRW_ABSOLUTE = Decimal("3000000000")  # 30억 — 스펙 422 max-order-amount-exceeded


@dataclass
class GuardResult:
    amount_krw: Decimal
    amount_basis: str            # "limit" | "upper_limit"
    warnings: list[str] = field(default_factory=list)


def order_amount_krw(req: OrderCreateRequest, upper_limit: Decimal | None) -> Decimal:
    if req.orderType == "MARKET":
        if upper_limit is None:
            raise GuardError("guard/price-limit-unavailable", "상한가 조회 불가 — 시장가 금액 산정 불가")
        return upper_limit * req.quantity
    if req.price is None:   # assert 금지 — python -O 에서도 방어선 유지
        raise GuardError("guard/price-required", "지정가 주문은 가격이 필요합니다")
    return req.price * req.quantity


def check_order(req: OrderCreateRequest, *, cfg: TradeConfig,
                upper_limit: Decimal | None, lower_limit: Decimal | None,
                daily_buy_total: Decimal, sellable_qty: Decimal | None,
                count_toward_daily: bool = True) -> GuardResult:
    # 1. LIMIT ↔ price 정합
    if req.orderType == "LIMIT" and req.price is None:
        raise GuardError("guard/price-required", "지정가 주문은 가격이 필요합니다")
    if req.orderType == "MARKET" and req.price is not None:
        raise GuardError("guard/price-forbidden", "시장가 주문에는 가격을 보내지 않습니다")
    # 2. 수량 양의 정수
    if req.quantity <= 0 or req.quantity != req.quantity.to_integral_value():
        raise GuardError("guard/quantity-invalid", "수량은 양의 정수", {"quantity": str(req.quantity)})
    # 3. 호가단위 / 4. 상하한
    if req.price is not None:
        if req.price != req.price.to_integral_value():
            raise GuardError("guard/tick-size", "KR 가격은 정수(원)", {"tickSize": "1"})
        tick = Decimal(krx_tick_size(float(req.price)))
        if req.price % tick != 0:
            raise GuardError("guard/tick-size", f"호가 단위 {tick}원 배수가 아닙니다", {"tickSize": str(tick)})
        # KR 종목은 상·하한가가 항상 있다 — None 은 상류 이상이므로 MARKET 과 동일하게 fail-closed
        if upper_limit is None or lower_limit is None:
            raise GuardError("guard/price-limit-unavailable", "상·하한가 조회 불가 — 가격 범위 검증 불가")
        if req.price > upper_limit or req.price < lower_limit:
            raise GuardError("guard/price-out-of-range", "상·하한가 범위 밖",
                             {"upperLimitPrice": str(upper_limit), "lowerLimitPrice": str(lower_limit)})
    # 5. 1건 상한
    amount = order_amount_krw(req, upper_limit)
    basis = "upper_limit" if req.orderType == "MARKET" else "limit"
    if amount > cfg.max_order_krw:
        raise GuardError("guard/max-order-amount", "1건 주문 금액 상한 초과",
                         {"amountKrw": str(amount), "maxOrderKrw": str(cfg.max_order_krw), "amountBasis": basis})
    # 6. 1일 누적 (BUY, create 만)
    if req.side == "BUY" and count_toward_daily and daily_buy_total + amount > cfg.max_daily_krw:
        raise GuardError("guard/max-daily-amount", "1일 매수 누적 상한 초과",
                         {"amountKrw": str(amount), "dailyTotalKrw": str(daily_buy_total), "maxDailyKrw": str(cfg.max_daily_krw)})
    # 7. 매도 가능 수량
    if req.side == "SELL" and sellable_qty is not None and req.quantity > sellable_qty:
        raise GuardError("guard/sellable-exceeded", "판매 가능 수량 초과",
                         {"sellableQuantity": str(sellable_qty), "quantity": str(req.quantity)})
    # 8. 고액
    warnings: list[str] = []
    if amount >= MAX_ORDER_KRW_ABSOLUTE:
        raise GuardError("guard/max-order-amount-exceeded", "30억 이상 주문은 접수 불가", {"amountKrw": str(amount)})
    if amount >= HIGH_VALUE_KRW:
        if not req.confirmHighValueOrder:
            raise GuardError("guard/confirm-high-value-required", "1억 이상 주문은 confirmHighValueOrder=true 필요",
                             {"amountKrw": str(amount)})
        warnings.append("high_value")
    return GuardResult(amount_krw=amount, amount_basis=basis, warnings=warnings)
