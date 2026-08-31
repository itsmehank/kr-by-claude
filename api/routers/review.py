from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from api.deps import get_conn
from api.schemas.review import (
    CandlesResponse, ReviewResponse, ReviewRowOut, ReviewTriggerOut,
    StockRowsResponse,
)
from api.services.review_builder import (
    BREAKOUT_TYPES, build_spark, chain_tn, corp_action_flags,
    count_orphan_triggers, derive_status, fetch_analysis_rows, fetch_candles,
    fetch_price_series, first_breakout, first_promotion_d, max_reach,
)
from api.services.review_streaks import build_stock_rows

router = APIRouter(prefix="/api/review", tags=["review"])

SPARK_TRADING_DAYS = 20


@router.get("/analyses", response_model=ReviewResponse)
def list_analyses(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    classification: str | None = None,
    source: str | None = None,
    triggered: bool | None = None,
    pattern: str | None = None,
    ticker: str | None = None,
    include_pivot_null: bool = False,
    limit: int = Query(default=200, ge=0),
    offset: int = Query(default=0, ge=0),
    conn: Connection = Depends(get_conn),
):
    today = date.today()
    date_to = to or today
    date_from = from_ or (date_to - timedelta(days=28))
    limit = min(limit, 500)

    rows = fetch_analysis_rows(
        conn, date_from=date_from, date_to=date_to, classification=classification,
        source=source, pattern=pattern, ticker=ticker,
        include_pivot_null=include_pivot_null, limit=limit, offset=offset,
    )
    flags = corp_action_flags(
        conn, [(r["symbol"], r["key_date"]) for r in rows], today=today)

    out: list[ReviewRowOut] = []
    for r in rows:
        fb = first_breakout(r["triggers"])
        series = fetch_price_series(conn, r["symbol"], r["key_date"], today)
        t5 = t20 = reach = baseline = None
        spark: list[float] = []
        if fb is not None and fb["close"] and fb["pivot_price"]:
            pivot_delta = (fb["close"] - fb["pivot_price"]) / fb["pivot_price"]
            t5 = chain_tn(series, fb["d"], pivot_delta, 5)
            t20 = chain_tn(series, fb["d"], pivot_delta, 20)
            idx = {dt: i for i, (dt, _) in enumerate(series)}
            if fb["d"] in idx:
                d_i = idx[fb["d"]]
                baseline = series[d_i][1] / (1.0 + pivot_delta)
                end_i = min(d_i + SPARK_TRADING_DAYS, len(series) - 1)
                spark = build_spark(series, fb["d"], series[end_i][0])
        elif r["pivot_price"]:
            reach = max_reach(series, r["key_date"], r["next_key_date"],
                              r["pivot_price"], today=today)
            baseline = r["pivot_price"]
            end = r["next_key_date"] or today
            window = [(dt, v) for dt, v in series if r["key_date"] < dt
                      and (dt < end if r["next_key_date"] else dt <= end)]
            if window:
                spark = build_spark(window, window[0][0], window[-1][0])

        status = derive_status(r["triggers"], t5, t20)
        out.append(ReviewRowOut(
            symbol=r["symbol"], name=r["name"], market=r["market"],
            source=r["source"], classified_at=r["classified_at"],
            analyzed_for_date=r["analyzed_for_date"], key_date=r["key_date"],
            classification=r["classification"], pattern=r["pattern"],
            pivot_price=r["pivot_price"], backfilled=r["backfilled"], status=status,
            first_breakout_at=fb["d"] if fb else None,
            first_breakout_type=fb["trigger_type"] if fb else None,
            first_breakout_decision=fb["decision"] if fb else None,
            promotion_at=first_promotion_d(r["triggers"]),
            trigger_count=len(r["triggers"]),
            t5_pct=t5, t20_pct=t20, max_reach_pct=reach,
            corp_action_flag=(r["symbol"], r["key_date"]) in flags,
            spark=spark, pivot_baseline=baseline,
            triggers=[ReviewTriggerOut(
                evaluated_at=t["evaluated_at"], d=t["d"],
                trigger_type=t["trigger_type"], decision=t["decision"],
                close=t["close"], pivot_price=t["pivot_price"],
                reasoning=t["reasoning"]) for t in r["triggers"]],
        ))
    if triggered is True:
        out = [r for r in out if r.first_breakout_at is not None]
    elif triggered is False:
        out = [r for r in out if r.first_breakout_at is None]
    orphans = count_orphan_triggers(conn, date_from=date_from, date_to=date_to)
    return ReviewResponse(rows=out, orphan_trigger_count=orphans)


@router.get("/stocks/{symbol}/candles", response_model=CandlesResponse)
def stock_candles(
    symbol: str,
    from_: date = Query(alias="from"),
    to: date = Query(),
    conn: Connection = Depends(get_conn),
):
    """상세 패널 캔들(#143) — 행 선택 시에만 호출되는 경량 조회.
    날짜축 정합·null 정책은 fetch_candles(review_builder) 참조."""
    return CandlesResponse(candles=fetch_candles(conn, symbol, from_, to))


@router.get("/stocks", response_model=StockRowsResponse)
def list_stocks(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    source: str | None = None,
    ticker: str | None = None,
    status: str | None = None,
    limit: int = Query(default=200, ge=0),
    offset: int = Query(default=0, ge=0),
    conn: Connection = Depends(get_conn),
):
    today = date.today()
    date_to = to or today
    date_from = from_ or (date_to - timedelta(days=28))
    limit = min(limit, 500)
    result = build_stock_rows(conn, date_from=date_from, date_to=date_to,
                              source=source, ticker=ticker, status=status,
                              limit=limit, offset=offset, today=today)
    names = {}
    if result["rows"]:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, name FROM stocks WHERE ticker = ANY(%s)",
                        ([r["symbol"] for r in result["rows"]],))
            names = dict(cur.fetchall())
    for r in result["rows"]:
        r["name"] = names.get(r["symbol"])
    return StockRowsResponse(**result)
