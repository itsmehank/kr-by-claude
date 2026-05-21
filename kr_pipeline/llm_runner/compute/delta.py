"""신규 후보 추출 — T_today − recently_classified.

  T_today = daily_indicators WHERE minervini_pass = TRUE
  recently_classified = weekly_classification.symbol
    WHERE classified_at >= NOW() - INTERVAL '7 days'
"""
from datetime import date, timedelta

from psycopg import Connection


RECENT_WINDOW_DAYS = 7


def find_new_tickers(conn: Connection, as_of: date | None = None) -> list[str]:
    """오늘 결정론 필터 통과 + 최근 7일 내 분류 없는 종목 리스트."""
    if as_of is None:
        as_of = date.today()
    cutoff = as_of - timedelta(days=RECENT_WINDOW_DAYS)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.ticker
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date = %s
               AND i.minervini_pass = TRUE
               AND s.delisted_at IS NULL
               AND NOT EXISTS (
                 SELECT 1 FROM weekly_classification wc
                  WHERE wc.symbol = i.ticker
                    AND wc.classified_at >= %s
               )
             ORDER BY i.ticker
            """,
            (as_of, cutoff),
        )
        return [r[0] for r in cur.fetchall()]
