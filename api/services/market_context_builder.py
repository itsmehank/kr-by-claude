"""market_context_daily → payload.market_context dict."""
import logging
from datetime import date
from psycopg import Connection


log = logging.getLogger(__name__)

INDEX_CODE_MAP = {"KOSPI": "1001", "KOSDAQ": "2001"}


def build_market_context(conn: Connection, market: str, on_date: date) -> dict:
    """주어진 (market, on_date) 이하 가장 최근 market_context_daily 행을 dict 로 변환.

    오늘 행 없으면 직전 평일 데이터로 fallback (LLM 분석이 market-context 적재 전에
    돌아도 가장 최근 시장 상태를 쓰도록). 어떤 행도 없으면 모든 필드 None.

    as_of_date: 실제 사용한 행의 날짜 (P1-4 관측성 짝). fallback 이 무음으로
    지나가지 않도록 — on_date 와 다르면 warning 로그 + payload/freeze 에 영구 기록.
    additive 필드라 기존 소비자(프롬프트)는 무시해도 무방.
    """
    index_code = INDEX_CODE_MAP.get(market)
    if index_code is None:
        return _empty()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, current_status, distribution_day_count_last_25,
                   last_follow_through_day, days_since_follow_through,
                   pct_stocks_above_200d_ma
              FROM market_context_daily
             WHERE date <= %s AND index_code = %s
             ORDER BY date DESC LIMIT 1
            """,
            (on_date, index_code),
        )
        row = cur.fetchone()

    if row is None:
        return _empty()

    row_date = row[0]
    if row_date != on_date:
        log.warning(
            "market_context fallback: %s(%s) 요청에 %s 행 사용 (당일 행 없음 — 휴일/적재 실패)",
            on_date, market, row_date,
        )

    return {
        "as_of_date": row_date.isoformat(),
        "current_status": row[1],
        "distribution_day_count_last_25_sessions": row[2],
        "last_follow_through_day": row[3].isoformat() if row[3] else None,
        "days_since_follow_through": row[4],
        "pct_stocks_above_200d_ma": float(row[5]) if row[5] is not None else None,
    }


def _empty() -> dict:
    return {
        "as_of_date": None,
        "current_status": None,
        "distribution_day_count_last_25_sessions": None,
        "last_follow_through_day": None,
        "days_since_follow_through": None,
        "pct_stocks_above_200d_ma": None,
    }
