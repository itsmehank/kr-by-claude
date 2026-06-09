"""signal_performance backfill — 시그널의 N일 후 가격 + 시장 대비 수익률."""
from __future__ import annotations

import logging
from datetime import date, timedelta, timezone

from psycopg import Connection


log = logging.getLogger("kr_pipeline.llm_runner.performance")


PERIODS = [
    ("1w", 7),
    ("2w", 14),
    ("4w", 28),
    ("8w", 56),
]


def run(conn: Connection, *, as_of: date | None = None) -> dict:
    if as_of is None:
        as_of = date.today()

    # 1) entry_params 의 모든 signal 중 performance 가 incomplete 한 것
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ep.symbol, ep.signal_at, ep.analyzed_for_date, ep.entry_price,
                   sp.price_1w, sp.price_2w, sp.price_4w, sp.price_8w,
                   sp.market_return_1w_pct, sp.market_return_2w_pct,
                   sp.market_return_4w_pct, sp.market_return_8w_pct
              FROM entry_params ep
              LEFT JOIN signal_performance sp
                ON sp.symbol = ep.symbol AND sp.signal_at = ep.signal_at
             WHERE COALESCE(ep.analyzed_for_date, (ep.signal_at AT TIME ZONE 'UTC')::date) >= %s - INTERVAL '90 days'
               AND COALESCE(ep.analyzed_for_date, (ep.signal_at AT TIME ZONE 'UTC')::date) <= %s
            """,
            (as_of, as_of),
        )
        rows = cur.fetchall()

    backfilled = 0
    market_base_missing: list[dict] = []
    for (symbol, signal_at, analyzed_for_date, entry_price,
         p1w, p2w, p4w, p8w,
         mr1w, mr2w, mr4w, mr8w) in rows:
        prices = {"1w": p1w, "2w": p2w, "4w": p4w, "8w": p8w}
        market_returns = {"1w": mr1w, "2w": mr2w, "4w": mr4w, "8w": mr8w}
        # analyzed_for_date(데이터 날짜) 우선; NULL 이면 signal_at UTC 날짜로 fallback
        signal_date = analyzed_for_date or signal_at.astimezone(timezone.utc).date()
        any_updated = False

        # market_index_code 조회 (KOSPI: 1001, KOSDAQ: 2001)
        with conn.cursor() as cur:
            cur.execute("SELECT market FROM stocks WHERE ticker = %s", (symbol,))
            mrow = cur.fetchone()
        if not mrow:
            continue
        market_code = "1001" if mrow[0] == "KOSPI" else "2001"

        updates = {}
        adj_entry: float | None = None
        adj_entry_fetched = False
        base_close: float | None = None
        base_fetched = False
        base_missing = False
        for period_name, days in PERIODS:
            # 가격과 시장수익률이 모두 이미 있으면 스킵
            if prices[period_name] is not None and market_returns[period_name] is not None:
                continue
            target_date = signal_date + timedelta(days=days)
            if target_date > as_of:
                continue
            # 종목 가격
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT adj_close FROM daily_prices
                     WHERE ticker = %s AND date <= %s
                     ORDER BY date DESC LIMIT 1
                    """,
                    (symbol, target_date),
                )
                price_row = cur.fetchone()
            if not price_row:
                continue
            future_price = float(price_row[0])
            # 가격이 이미 있는 경우엔 기존 값 재사용 (market return 만 채우는 경우)
            if prices[period_name] is None:
                if not adj_entry_fetched:
                    adj_entry_fetched = True
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT close, adj_close FROM daily_prices WHERE ticker = %s AND date = %s",
                            (symbol, signal_date),
                        )
                        arow = cur.fetchone()
                    if arow and arow[0] and float(arow[0]) != 0 and float(arow[1]) != 0:
                        adj_entry = float(entry_price) * (float(arow[1]) / float(arow[0]))
                    else:
                        adj_entry = float(entry_price)
                updates[f"price_{period_name}"] = future_price
                updates[f"return_{period_name}_pct"] = (
                    (future_price - adj_entry) / adj_entry * 100
                )
            else:
                future_price = float(prices[period_name])
            # 시장 수익률 — base 는 시그널당 1회만 조회 (lazy)
            if not base_fetched:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT close FROM index_daily WHERE index_code = %s AND date = %s",
                        (market_code, signal_date),
                    )
                    brow = cur.fetchone()
                base_fetched = True
                if brow:
                    base_close = float(brow[0])
                else:
                    base_missing = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT close FROM index_daily WHERE index_code = %s AND date <= %s "
                    "ORDER BY date DESC LIMIT 1",
                    (market_code, target_date),
                )
                end_row = cur.fetchone()
            if base_close is not None and end_row:
                updates[f"market_return_{period_name}_pct"] = (
                    (float(end_row[0]) - base_close) / base_close * 100
                )

        if base_missing:
            log.warning(
                "market base index missing — symbol=%s signal_date=%s code=%s",
                symbol, signal_date, market_code,
            )
            market_base_missing.append({
                "symbol": symbol,
                "signal_date": signal_date.isoformat(),
                "market_code": market_code,
            })

        if updates:
            cols_assignments = ", ".join(f"{k} = %s" for k in updates.keys())
            with conn.cursor() as cur:
                # UPSERT (insert if missing)
                cur.execute(
                    f"""
                    INSERT INTO signal_performance (symbol, signal_at, entry_price, {", ".join(updates.keys())})
                    VALUES (%s, %s, %s, {", ".join(["%s"] * len(updates))})
                    ON CONFLICT (symbol, signal_at) DO UPDATE
                       SET {cols_assignments},
                           updated_at = NOW()
                    """,
                    (
                        symbol, signal_at, (adj_entry if adj_entry is not None else float(entry_price)),
                        *updates.values(),
                        *updates.values(),
                    ),
                )
            conn.commit()
            any_updated = True

        if any_updated:
            backfilled += 1

    log.info("performance backfill: %d signals updated", backfilled)
    return {"backfilled": backfilled, "market_base_missing": market_base_missing}
