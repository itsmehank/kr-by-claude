# trade_api/routers/orders.py
"""주문 라우트 (spec §6). 실주문 코드는 _submit_live 안에만 있고 DRY_RUN 가드 뒤에 위치.

흐름: preview(가드 전부·clientOrderId 생성·토큰) → submit(토큰 검증 → 감사 begin → [DRY_RUN 종료]
→ 토스 호출 → 감사 finish). 토스 에러도 감사 finish 후 그대로 재던짐(핸들러가 envelope 전달).
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from kr_trading.audit import AuditLog, kst_today
from kr_trading.config import TradeConfig
from kr_trading.guard import GuardResult, check_order
from kr_trading.preview import PreviewStore, new_client_order_id
from kr_trading.toss.client import TossClient
from kr_trading.toss.errors import GuardError, TossApiError
from kr_trading.toss.models import Order, OrderCreateRequest, PaginatedOrderResponse
from trade_api.deps import get_cfg, get_conn, get_preview, get_toss
from trade_api.schemas import (
    EstimateOut, ModifyPreviewIn, ModifySubmitIn, OperationOut, OrderSubmitIn, OrderSubmitOut,
    PreviewIn, PreviewOut,
)

router = APIRouter(prefix="/trade-api/orders", tags=["orders"])
DRY_RUN_STATUS = 0          # 감사 http_status: 전송 없음 표식(1일 누적은 200 만 집계)
PREVIEW_TTL_SEC = 300


def _kr_commission_rate(toss: TossClient) -> Decimal | None:
    try:
        for c in toss.commissions():
            if c.marketCountry == "KR":
                return c.commissionRate
    except TossApiError:
        return None
    return None


def _estimate(side: str, g: GuardResult, rate: Decimal | None) -> EstimateOut:
    commission = (g.amount_krw * rate) if rate is not None else None
    fee = commission or Decimal("0")
    total = g.amount_krw + fee if side == "BUY" else g.amount_krw - fee
    return EstimateOut(amount=g.amount_krw, amountBasis=g.amount_basis, commission=commission, total=total)


def _guard(req: OrderCreateRequest, *, cfg: TradeConfig, toss: TossClient, log: AuditLog,
           count_toward_daily: bool) -> GuardResult:
    limits = toss.price_limits(req.symbol)
    sellable = toss.sellable_quantity(req.symbol).sellableQuantity if req.side == "SELL" else None
    daily = log.daily_buy_total_krw(kst_today()) if (req.side == "BUY" and count_toward_daily) else Decimal("0")
    return check_order(req, cfg=cfg, upper_limit=limits.upperLimitPrice, lower_limit=limits.lowerLimitPrice,
                       daily_buy_total=daily, sellable_qty=sellable, count_toward_daily=count_toward_daily)


@router.post("/preview", response_model=PreviewOut)
def preview(body: PreviewIn, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
            store: PreviewStore = Depends(get_preview), conn: Connection = Depends(get_conn)) -> PreviewOut:
    req = OrderCreateRequest(**body.model_dump(), clientOrderId=new_client_order_id())
    g = _guard(req, cfg=cfg, toss=toss, log=AuditLog(conn), count_toward_daily=True)
    est = _estimate(req.side, g, _kr_commission_rate(toss))
    payload = req.to_toss_json()
    token = store.put(payload, {"amount": str(g.amount_krw), "basis": g.amount_basis})
    return PreviewOut(previewToken=token, clientOrderId=req.clientOrderId, request=payload, estimate=est,
                      warnings=g.warnings, dryRun=cfg.dry_run, expiresInSec=PREVIEW_TTL_SEC)


@router.post("", response_model=OrderSubmitOut)
def submit(body: OrderSubmitIn, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
           store: PreviewStore = Depends(get_preview), conn: Connection = Depends(get_conn)) -> OrderSubmitOut:
    payload = body.request.to_toss_json()
    meta = store.verify(body.previewToken, payload)
    log = AuditLog(conn)
    if body.request.side == "BUY" and not cfg.dry_run:
        total = log.daily_buy_total_krw(kst_today())
        if total + Decimal(meta["amount"]) > cfg.max_daily_krw:
            raise GuardError("guard/max-daily-amount", "1일 매수 누적 상한 초과(제출 시점 재검)",
                             {"amountKrw": meta["amount"], "dailyTotalKrw": str(total), "maxDailyKrw": str(cfg.max_daily_krw)})
    audit_id = log.begin("create", body.request.symbol, body.request.side, body.request.clientOrderId,
                         Decimal(meta["amount"]), payload, dry_run=cfg.dry_run)
    conn.commit()                                     # pending 행을 전송 전에 확정
    if cfg.dry_run:
        log.finish(audit_id, http_status=DRY_RUN_STATUS)
        return OrderSubmitOut(dryRun=True, orderId=None, clientOrderId=body.request.clientOrderId,
                              auditId=audit_id, request=payload)
    # ── 실주문 경로 (DRY_RUN 가드 뒤) ────────────────────────────────
    try:
        res = toss.create_order(body.request)
    except TossApiError as e:
        log.finish(audit_id, http_status=e.status, error_code=e.code, request_id=e.request_id)
        conn.commit()
        raise
    log.finish(audit_id, http_status=200, order_id=res.orderId, response_json=res.model_dump(mode="json"), request_id=toss.last_request_id)
    conn.commit()
    return OrderSubmitOut(dryRun=False, orderId=res.orderId, clientOrderId=res.clientOrderId,
                          auditId=audit_id, request=payload)


@router.post("/modify/preview", response_model=PreviewOut)
def modify_preview(body: ModifyPreviewIn, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
                   store: PreviewStore = Depends(get_preview), conn: Connection = Depends(get_conn)) -> PreviewOut:
    original = toss.get_order(body.orderId)
    synthetic = OrderCreateRequest(symbol=original.symbol, side=original.side, orderType=body.orderType,
                                   quantity=body.quantity, price=body.price,
                                   confirmHighValueOrder=body.confirmHighValueOrder)
    g = _guard(synthetic, cfg=cfg, toss=toss, log=AuditLog(conn), count_toward_daily=False)
    est = _estimate(original.side, g, _kr_commission_rate(toss))
    payload = {"orderId": body.orderId, **body.model_dump(mode="json", exclude={"orderId"}, exclude_none=True)}
    token = store.put(payload, {"amount": str(g.amount_krw), "basis": g.amount_basis,
                                "symbol": original.symbol, "side": original.side})
    return PreviewOut(previewToken=token, clientOrderId=None, request=payload, estimate=est,
                      warnings=g.warnings, dryRun=cfg.dry_run, expiresInSec=PREVIEW_TTL_SEC)


@router.post("/{order_id}/modify", response_model=OperationOut)
def modify(order_id: str, body: ModifySubmitIn, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
           store: PreviewStore = Depends(get_preview), conn: Connection = Depends(get_conn)) -> OperationOut:
    payload = {"orderId": order_id, **body.request.model_dump(mode="json", exclude_none=True)}
    meta = store.verify(body.previewToken, payload)
    log = AuditLog(conn)
    audit_id = log.begin("modify", meta["symbol"], meta["side"], None, Decimal(meta["amount"]), payload, dry_run=cfg.dry_run)
    conn.commit()
    if cfg.dry_run:
        log.finish(audit_id, http_status=DRY_RUN_STATUS)
        return OperationOut(dryRun=True, orderId=None, auditId=audit_id)
    try:
        res = toss.modify_order(order_id, body.request)
    except TossApiError as e:
        log.finish(audit_id, http_status=e.status, error_code=e.code, request_id=e.request_id)
        conn.commit()
        raise
    log.finish(audit_id, http_status=200, order_id=res.orderId, response_json=res.model_dump(mode="json"), request_id=toss.last_request_id)
    conn.commit()
    return OperationOut(dryRun=False, orderId=res.orderId, auditId=audit_id)


@router.post("/{order_id}/cancel", response_model=OperationOut)
def cancel(order_id: str, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
           conn: Connection = Depends(get_conn)) -> OperationOut:
    original = toss.get_order(order_id)
    log = AuditLog(conn)
    audit_id = log.begin("cancel", original.symbol, original.side, None, None, {"orderId": order_id}, dry_run=cfg.dry_run)
    conn.commit()
    if cfg.dry_run:
        log.finish(audit_id, http_status=DRY_RUN_STATUS)
        return OperationOut(dryRun=True, orderId=None, auditId=audit_id)
    try:
        res = toss.cancel_order(order_id)
    except TossApiError as e:
        log.finish(audit_id, http_status=e.status, error_code=e.code, request_id=e.request_id)
        conn.commit()
        raise
    log.finish(audit_id, http_status=200, order_id=res.orderId, response_json=res.model_dump(mode="json"), request_id=toss.last_request_id)
    conn.commit()
    return OperationOut(dryRun=False, orderId=res.orderId, auditId=audit_id)


@router.get("", response_model=PaginatedOrderResponse)
def list_orders(status: str = Query(..., pattern="^(OPEN|CLOSED)$"), cursor: str | None = None,
                limit: int | None = Query(None, ge=1, le=100), toss: TossClient = Depends(get_toss)) -> PaginatedOrderResponse:
    return toss.list_orders(status, cursor=cursor, limit=limit)


@router.get("/{order_id}", response_model=Order)
def detail(order_id: str, toss: TossClient = Depends(get_toss)) -> Order:
    return toss.get_order(order_id)
