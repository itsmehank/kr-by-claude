"""DB 읽기 — active monitoring, qualifying tickers, prior analysis."""
from __future__ import annotations

from datetime import date

from psycopg import Connection


def get_qualifying_tickers(
    conn: Connection, as_of: date | None = None, tickers: list[str] | None = None
) -> list[dict]:
    """주말 (5) batch 후보 종목 조회.

    as_of 가 주어지면 그 날짜 이하 가장 최근 daily_indicators 의 날짜를 찾아 사용.
    tickers 가 주어지면 그 종목들로 한정 (minervini 통과분만 반환 — 미통과는 자동 제외).
    tickers=None 이면 그 날짜 minervini 통과 전 종목.

    Returns: [{"symbol", "market"}, ...]
    """
    with conn.cursor() as cur:
        if as_of is None:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
        else:
            cur.execute("SELECT MAX(date) FROM daily_indicators WHERE date <= %s", (as_of,))
        row = cur.fetchone()
        target_date = row[0] if row and row[0] else (as_of or date.today())

    sql = """
        SELECT i.ticker, s.market
          FROM daily_indicators i
          JOIN stocks s ON s.ticker = i.ticker
         WHERE i.date = %s
           AND i.minervini_pass = TRUE
           AND i.rs_line_not_declining_7m = TRUE
           AND s.delisted_at IS NULL
           -- #4 현재 정지 제외: as_of 당일 거래정지(adj_low NULL)면 거래 불가 → 후보 제외.
           -- min_periods 임계(장기정지 NaN)와 상보 — 오늘 정지/재개 직후 슬쩍통과 차단.
           AND NOT EXISTS (
               SELECT 1 FROM daily_prices p
                WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL
           )
    """
    params: list = [target_date]
    if tickers:
        sql += " AND i.ticker = ANY(%s)"
        params.append(list(tickers))
    sql += " ORDER BY i.ticker"

    with conn.cursor() as cur:
        cur.execute(sql, params)
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
                   pivot_price, base_low, base_high, watch_reason
              FROM weekly_classification
             ORDER BY symbol, COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
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
            "watch_reason": r[8],
        }
        for r in rows
        if r[3] in ("entry", "watch")
    ]


def get_classified_losing_minervini(conn: Connection, as_of: date) -> list[dict]:
    """최신 분류가 entry/watch/ignore 인데 as_of 의 minervini_pass=false 인 종목.

    이미 disqualified 인 종목은 IN 절에서 제외 → 멱등(재강등 안 함).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest AS (
              SELECT DISTINCT ON (symbol) symbol, market, classification
                FROM weekly_classification
               ORDER BY symbol, COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
            )
            SELECT l.symbol, l.market
              FROM latest l
              JOIN daily_indicators i ON i.ticker = l.symbol AND i.date = %s
             WHERE l.classification IN ('entry', 'watch', 'ignore')
               AND i.minervini_pass = FALSE
            """,
            (as_of,),
        )
        return [{"symbol": r[0], "market": r[1]} for r in cur.fetchall()]


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
        # NULL 은 None 유지 — 0 강제 시 evaluate_pivot 의 None 가드가 무력화되어
        # volume >= 0×mult 가 항상 참(거래량 확인 없이 트리거), close < sma_50(=0)
        # invalidation 영구 미발동이 된다. 가드가 None 계약을 기대한다.
        current = {r[0]: {"close": float(r[1]),
                          "volume": int(r[2]) if r[2] is not None else None,
                          "avg_volume_50d": float(r[3]) if r[3] is not None else None,
                          "sma_50": float(r[4]) if r[4] is not None else None}
                   for r in cur.fetchall()}

        # 직전 거래일 종가 (fresh_cross 판정용). as_of 이전 가장 최근 1행/종목.
        cur.execute(
            """
            SELECT DISTINCT ON (ticker) ticker, adj_close
              FROM daily_indicators
             WHERE ticker = ANY(%s) AND date < %s
             ORDER BY ticker, date DESC
            """,
            (tickers, as_of),
        )
        prev = {r[0]: float(r[1]) for r in cur.fetchall() if r[1] is not None}

    enriched = []
    for a in active:
        cur_data = current.get(a["symbol"])
        if cur_data is None:
            continue  # no data today
        enriched.append({
            **a, **cur_data,
            "stop_loss": a.get("base_low"),
            "prev_close": prev.get(a["symbol"]),
        })
    return enriched


def resolve_as_of(conn: Connection, explicit_date: date | None = None) -> date:
    """파이프라인 as_of(데이터 날짜) 결정 — __main__ 과 run-게이트 공유.

    explicit_date 있으면 그 값, 없으면 MAX(daily_indicators.date), 둘 다 없으면 today.
    """
    if explicit_date is not None:
        return explicit_date
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(date) FROM daily_indicators")
        row = cur.fetchone()
    return row[0] if row and row[0] else date.today()
