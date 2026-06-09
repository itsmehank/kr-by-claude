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
                updates[f"price_{period_name}"] = future_price
                updates[f"return_{period_name}_pct"] = (
                    (future_price - float(entry_price)) / float(entry_price) * 100
                )
            else:
                future_price = float(prices[period_name])
            # 시장 수익률
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT close FROM index_daily
                     WHERE index_code = %s AND date = %s
                    """,
                    (market_code, signal_date),
                )
                base_row = cur.fetchone()
                cur.execute(
                    """
                    SELECT close FROM index_daily
                     WHERE index_code = %s AND date <= %s
                     ORDER BY date DESC LIMIT 1
                    """,
                    (market_code, target_date),
                )
                end_row = cur.fetchone()
            if base_row and end_row:
                updates[f"market_return_{period_name}_pct"] = (
                    (float(end_row[0]) - float(base_row[0]))
                    / float(base_row[0]) * 100
                )

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
                        symbol, signal_at, float(entry_price),
                        *updates.values(),
                        *updates.values(),
                    ),
                )
            conn.commit()
            any_updated = True

        if any_updated:
            backfilled += 1

    log.info("performance backfill: %d signals updated", backfilled)
    return {"backfilled": backfilled}
