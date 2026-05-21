"""신규 후보 추출 — T_today − recently_classified.

  T_today = daily_indicators WHERE minervini_pass = TRUE
  recently_classified = weekly_classification.symbol
    WHERE classified_at >= NOW() - INTERVAL '7 days'

drawdown_filter_pass 게이트는 2026-05-21 제거됨.
이유: rolling 252일 high-low 스프레드 (drawdown_52w_pct) 가 시간 순서를 무시해
"폭락 후 회복" 과 "저점에서 꾸준한 상승" 을 구분 못함. Minervini 가 명시한
"최고의 후보 (저점 대비 100~300%+ 상승)" 가 자동 탈락하던 false negative
편향을 해소. % from 52w high/low 가 이미 LLM payload 에 포함되어 LLM 이
판단함.
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
             WHERE i.date = %s
               AND i.minervini_pass = TRUE
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
