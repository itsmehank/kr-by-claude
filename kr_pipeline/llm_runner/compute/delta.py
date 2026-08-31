"""신규 후보 추출 — T_today − recently_llm_classified.

  T_today = daily_indicators WHERE minervini_pass = TRUE
  recently_llm_classified = weekly_classification.symbol
    WHERE source IN ('weekend', 'daily_delta')       -- LLM 실행 기록만 (#145)
      AND classified_at >= NOW() - INTERVAL '7 days'

  system_disqualify 행은 LLM 미호출 기록이라 세지 않는다 — 실격 직후 재통과
  종목이 취지(호출 비용 절약) 밖에서 막히지 않게(#145).
"""
from datetime import date, timedelta

from psycopg import Connection

from kr_pipeline.common.thresholds import RECENT_CLASSIFICATION_WINDOW_DAYS

# 기존 module-level 상수는 SSOT 로 이전. 호환성 별칭 유지.
RECENT_WINDOW_DAYS = RECENT_CLASSIFICATION_WINDOW_DAYS


def find_new_tickers(conn: Connection, as_of: date | None = None) -> list[str]:
    """오늘 결정론 필터 통과 + 최근 7일 내 LLM 분류(weekend·daily_delta) 없는 종목 리스트."""
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
               -- NOTE: 이 7일 가드는 "최근에 LLM을 실행했나"(실행 비용 절약)를 보는 것이라
               --       의도적으로 classified_at 을 쓴다. 데이터 기준 최신성(analyzed_for_date)
               --       으로 바꾸지 않는다. (sub-project ① 설계 결정)
               -- (#145) LLM 실행 기록(weekend·daily_delta)만 센다 — 양성 목록.
               --       system_disqualify 같은 비-LLM 기록이 가드를 트리거하면 실격 직후
               --       재통과 종목이 취지(비용 절약) 밖에서 막힌다. 새 비-LLM source 가
               --       생겨도 실패 방향이 '호출 1회 추가'라는 싼 쪽이 되게 IN 으로 표현
               --       (review_builder 의 source IN 전례). 반복 호출 상한은 LLM 분류 행
               --       가드 + 실격 멱등이 구조로 보장(≤7일 1회).
               AND NOT EXISTS (
                 SELECT 1 FROM weekly_classification wc
                  WHERE wc.symbol = i.ticker
                    AND wc.source IN ('weekend', 'daily_delta')
                    AND wc.classified_at >= %s
               )
             ORDER BY i.ticker
            """,
            (as_of, cutoff),
        )
        return [r[0] for r in cur.fetchall()]
