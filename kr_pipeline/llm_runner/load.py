"""DB 읽기 — active monitoring, qualifying tickers, prior analysis."""
from __future__ import annotations

from datetime import date

from psycopg import Connection


def get_qualifying_tickers(conn: Connection, as_of: date | None = None) -> list[dict]:
    """주말 (5) batch 후보 종목 조회.

    as_of 가 주어지면 그 날짜 이하 가장 최근 daily_indicators 의 날짜를 찾아 사용.
    (평일 수동 실행 시 오늘 데이터 없으면 직전 영업일 사용 — 토요일 cron 시나리오와 일관.)
    as_of=None 이면 daily_indicators 의 전체 MAX(date) 사용.

    Returns: [{"symbol", "market"}, ...]
    """
    with conn.cursor() as cur:
        if as_of is None:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
        else:
            cur.execute("SELECT MAX(date) FROM daily_indicators WHERE date <= %s", (as_of,))
        row = cur.fetchone()
        target_date = row[0] if row and row[0] else (as_of or date.today())

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.ticker, s.market
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date = %s
               AND i.minervini_pass = TRUE
               AND s.delisted_at IS NULL
             ORDER BY i.ticker
            """,
            (target_date,),
        )
        return [{"symbol": r[0], "market": r[1]} for r in cur.fetchall()]


def get_active_monitoring(conn: Connection) -> list[dict]:
    """현재 active entry/watch 모니터링 종목 (최신 분류 기준).

    Returns: [{"symbol", "classification", "pivot_price", "stop_loss",
               "base_low", "classified_at", ...}, ...]
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (symbol)
                   symbol, classified_at, market, classification, pattern,
                   pivot_price, base_low, base_high
              FROM weekly_classification
             ORDER BY symbol, classified_at DESC
            """
        )
        rows = cur.fetchall()

    return [
        {
            "symbol": r[0],
            "classified_at": r[1],
            "market": r[2],
            "classification": r[3],
            "pattern": r[4],
            "pivot_price": float(r[5]) if r[5] else None,
            "base_low": float(r[6]) if r[6] else None,
            "base_high": float(r[7]) if r[7] else None,
        }
        for r in rows
        if r[3] in ("entry", "watch")
    ]


def get_active_with_current(conn: Connection, as_of: date | None = None) -> list[dict]:
    """active 모니터링 + 오늘의 close/volume/sma_50/avg_volume_50d 조인."""
    if as_of is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
            row = cur.fetchone()
        as_of = row[0] if row and row[0] else date.today()

    active = get_active_monitoring(conn)
    if not active:
        return []

    tickers = [a["symbol"] for a in active]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.ticker, i.adj_close AS close, i.volume,
                   i.avg_volume_50d, i.sma_50
              FROM daily_indicators i
             WHERE i.ticker = ANY(%s) AND i.date = %s
            """,
            (tickers, as_of),
        )
        current = {r[0]: {"close": float(r[1]), "volume": int(r[2]) if r[2] else 0,
                          "avg_volume_50d": float(r[3]) if r[3] else 0,
                          "sma_50": float(r[4]) if r[4] else 0}
                   for r in cur.fetchall()}

    enriched = []
    for a in active:
        cur_data = current.get(a["symbol"])
        if cur_data is None:
            continue  # no data today
        enriched.append({**a, **cur_data, "stop_loss": a.get("base_low", 0)})
    return enriched
