# trade_api/routers/orders.py
"""주문 라우트 (spec §6).

흐름: preview(가드 전부·clientOrderId 생성·토큰) → submit(previewToken consume → _begin_audit[advisory
lock+상한 재검+INSERT+commit] → _dispatch[DRY_RUN 가드 뒤 토스 호출 → finish]). 토스 에러도 감사 finish
후 그대로 재던짐(핸들러가 envelope 전달)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from kr_trading.audit import TRANSPORT_ERROR_STATUS, AuditLog, kst_today
from kr_trading.config import TradeConfig
from kr_trading.guard import GuardResult, check_order
from kr_trading.preview import PreviewStore, new_client_order_id
from kr_trading.toss.client import TossClient
from kr_trading.toss.errors import GuardError, TossApiError
from kr_trading.toss.models import Order, OrderCreateRequest, PaginatedOrderResponse
from trade_api.daycache import cached_price_limits, commissions_cache
from trade_api.deps import get_cfg, get_conn, get_preview, get_toss
from trade_api.schemas import (
    EstimateOut, ModifyPreviewIn, ModifySubmitIn, OperationOut, OrderSubmitIn, OrderSubmitOut,
    PreviewIn, PreviewOut, kr_int_str,
)

router = APIRouter(prefix="/trade-api/orders", tags=["orders"])
DRY_RUN_STATUS = 0          # 감사 http_status: 전송 없음 표식(1일 누적은 200 만 집계)
PREVIEW_TTL_SEC = 300


def _begin_audit(conn: Connection, log: AuditLog, cfg: TradeConfig, *, kind: str, symbol: str,
                 side: str | None, client_order_id: str | None, amount: Decimal | None,
                 payload: dict, lock_cap: bool = False) -> int:
    """상한 재검(선택)+INSERT(pending) 를 한 트랜잭션에서 — advisory lock 으로 동시 제출을 직렬화.

    lock_cap=True 일 때만 `pg_advisory_xact_lock` 을 잡고 1일 매수 누적을 재검한다(모두 BUY·live
    submit 전용, modify/cancel 은 상한이 없어 lock 불필요). 트랜잭션 종료(with 블록 탈출)와 함께
    lock 도 해제된다 — psycopg `conn.transaction()` 은 autocommit 연결에서도 블록 트랜잭션을 연다.
    """
    with conn.transaction():
        if lock_cap:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('toss_daily_cap'))")
            total = log.daily_buy_total_krw(kst_today())
            if total + amount > cfg.max_daily_krw:
                raise GuardError("guard/max-daily-amount", "1일 매수 누적 상한 초과(제출 시점 재검)",
                                 {"amountKrw": str(amount), "dailyTotalKrw": str(total),
                                  "maxDailyKrw": str(cfg.max_daily_krw)})
        audit_id = log.begin(kind, symbol, side, client_order_id, amount, payload, dry_run=cfg.dry_run)
    # 명시적 commit(#187 최종 수정웨이브): 풀링된 non-autocommit 연결에 이미 열린 트랜잭션이 있으면
    # 위 conn.transaction() 은 savepoint 로 강등돼 커밋되지 않는다 — pending 행의 durability·advisory
    # lock 해제를 연결의 이전 상태와 무관하게 만든다.
    conn.commit()
    return audit_id


def _dispatch(conn: Connection, log: AuditLog, cfg: TradeConfig, toss: TossClient, audit_id: int,
             call: Callable[[], Any]) -> tuple[int, Any | None]:
    """pending 행을 먼저 커밋(전송 전 확정) 한 뒤 호출 → 결과에 따라 감사행을 마감.

    - dry_run: 전송 없이 http_status=0 으로 마감.
    - TossApiError: 토스가 거부/오류를 확정 응답 — 그 상태 코드로 마감 후 재던짐(핸들러가 envelope 전달).
    - 그 외 모든 예외(타임아웃·검증 오류 등): 응답 미수신 — TRANSPORT_ERROR_STATUS(-1) 로 마감 후
      재던짐. 이 행은 1일 상한 집계에 포함된다(토스가 실제로 접수했을 수 있으므로 fail-closed).
    - 성공: http_status=200 으로 마감.
    """
    if cfg.dry_run:
        log.finish(audit_id, http_status=DRY_RUN_STATUS)
        conn.commit()
        return audit_id, None
    try:
        res = call()
    except TossApiError as e:
        log.finish(audit_id, http_status=e.status, error_code=e.code, request_id=e.request_id)
        conn.commit()
        raise
    except Exception as e:
        log.finish(audit_id, http_status=TRANSPORT_ERROR_STATUS, error_code=type(e).__name__)
        conn.commit()
        raise
    log.finish(audit_id, http_status=200, order_id=res.orderId,
              response_json=res.model_dump(mode="json"), request_id=toss.last_request_id)
    conn.commit()
    return audit_id, res


def _audited_call(conn: Connection, log: AuditLog, cfg: TradeConfig, toss: TossClient, *, kind: str,
                  symbol: str, side: str | None, client_order_id: str | None, amount: Decimal | None,
                  payload: dict, call: Callable[[], Any], lock_cap: bool = False) -> tuple[int, Any | None]:
    audit_id = _begin_audit(conn, log, cfg, kind=kind, symbol=symbol, side=side,
                            client_order_id=client_order_id, amount=amount, payload=payload,
                            lock_cap=lock_cap)
    return _dispatch(conn, log, cfg, toss, audit_id, call)


def _kr_commission_rate(toss: TossClient) -> Decimal | None:
    """국내(KR) 수수료율 — 일 단위 캐시 경유(#187 리뷰 추가 정리). 실패(TossApiError)는 캐시하지
    않아 다음 preview 가 재시도한다."""
    cached = commissions_cache.get("commissions")
    if cached is not None:
        return cached
    try:
        for c in toss.commissions():
            if c.marketCountry == "KR":
                commissions_cache.put("commissions", value=c.commissionRate)
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
           count_toward_daily: bool, skip_sellable: bool = False) -> GuardResult:
    limits = cached_price_limits(toss, req.symbol)
    sellable = (toss.sellable_quantity(req.symbol).sellableQuantity
               if (req.side == "SELL" and not skip_sellable) else None)
    daily = log.daily_buy_total_krw(kst_today()) if (req.side == "BUY" and count_toward_daily) else Decimal("0")
    return check_order(req, cfg=cfg, upper_limit=limits.upperLimitPrice, lower_limit=limits.lowerLimitPrice,
                       daily_buy_total=daily, sellable_qty=sellable, count_toward_daily=count_toward_daily,
                       skip_sellable=skip_sellable)


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
    meta = store.consume(body.previewToken, payload)   # 1회 소비 — 동일 토큰 재제출 차단(#187 리뷰 I-3)
    log = AuditLog(conn)
    audit_id, res = _audited_call(
        conn, log, cfg, toss, kind="create", symbol=body.request.symbol, side=body.request.side,
        client_order_id=body.request.clientOrderId, amount=Decimal(meta["amount"]), payload=payload,
        call=lambda: toss.create_order(body.request),
        lock_cap=(body.request.side == "BUY" and not cfg.dry_run),
    )
    if cfg.dry_run:
        return OrderSubmitOut(dryRun=True, orderId=None, clientOrderId=body.request.clientOrderId,
                              auditId=audit_id, request=payload)
    return OrderSubmitOut(dryRun=False, orderId=res.orderId, clientOrderId=res.clientOrderId,
                          auditId=audit_id, request=payload)


@router.post("/modify/preview", response_model=PreviewOut)
def modify_preview(body: ModifyPreviewIn, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
                   store: PreviewStore = Depends(get_preview), conn: Connection = Depends(get_conn)) -> PreviewOut:
    original = toss.get_order(body.orderId)
    synthetic = OrderCreateRequest(symbol=original.symbol, side=original.side, orderType=body.orderType,
                                   quantity=body.quantity, price=body.price,
                                   confirmHighValueOrder=body.confirmHighValueOrder)
    g = _guard(synthetic, cfg=cfg, toss=toss, log=AuditLog(conn), count_toward_daily=False, skip_sellable=True)
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
    audit_id, res = _audited_call(
        conn, log, cfg, toss, kind="modify", symbol=meta["symbol"], side=meta["side"],
        client_order_id=None, amount=Decimal(meta["amount"]), payload=payload,
        call=lambda: toss.modify_order(order_id, body.request),
    )
    if cfg.dry_run:
        return OperationOut(dryRun=True, orderId=None, auditId=audit_id)
    return OperationOut(dryRun=False, orderId=res.orderId, auditId=audit_id)


@router.post("/{order_id}/cancel", response_model=OperationOut)
def cancel(order_id: str, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
           conn: Connection = Depends(get_conn)) -> OperationOut:
    original = toss.get_order(order_id)
    log = AuditLog(conn)
    audit_id, res = _audited_call(
        conn, log, cfg, toss, kind="cancel", symbol=original.symbol, side=original.side,
        client_order_id=None, amount=None, payload={"orderId": order_id},
        call=lambda: toss.cancel_order(order_id),
    )
    if cfg.dry_run:
        return OperationOut(dryRun=True, orderId=None, auditId=audit_id)
    return OperationOut(dryRun=False, orderId=res.orderId, auditId=audit_id)


def _normalize_kr_order(order: Order) -> Order:
    """KR(원화) 주문은 quantity·price·체결수량·체결단가가 정수 — 토스 decimal scale 을 출력 시 정규화
    (#187 최종 수정웨이브). currency!='KRW' 는 그대로 통과."""
    if order.currency != "KRW":
        return order
    execution = order.execution.model_copy(update={
        "filledQuantity": kr_int_str(order.execution.filledQuantity),
        "averageFilledPrice": kr_int_str(order.execution.averageFilledPrice),
    })
    return order.model_copy(update={
        "quantity": kr_int_str(order.quantity),
        "price": kr_int_str(order.price),
        "execution": execution,
    })


@router.get("", response_model=PaginatedOrderResponse)
def list_orders(status: str = Query(..., pattern="^(OPEN|CLOSED)$"), cursor: str | None = None,
                limit: int | None = Query(None, ge=1, le=100), toss: TossClient = Depends(get_toss)) -> PaginatedOrderResponse:
    resp = toss.list_orders(status, cursor=cursor, limit=limit)
    return resp.model_copy(update={"orders": [_normalize_kr_order(o) for o in resp.orders]})


@router.get("/{order_id}", response_model=Order)
def detail(order_id: str, toss: TossClient = Depends(get_toss)) -> Order:
    return _normalize_kr_order(toss.get_order(order_id))
