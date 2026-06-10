"""적재 완전성 게이트 — 최신 daily_prices 커버리지가 미달이면 지표 계산을 막는다."""
from __future__ import annotations

from psycopg import Connection

DEFAULT_COVERAGE_THRESHOLD = 0.90


class IncompleteIngestionError(RuntimeError):
    """최신 daily_prices 적재 커버리지가 임계 미만 — 지표 계산 중단(fail-fast)."""


def check_daily_ohlcv_complete(
    conn: Connection,
    *,
    active_count: int,
    threshold: float = DEFAULT_COVERAGE_THRESHOLD,
) -> None:
    """최신 daily_prices 날짜의 종목 커버리지가 threshold 미만이면 IncompleteIngestionError.

    active_count: 기대 종목 수(활성 유니버스). coverage = (최신일 행수) / active_count.
    """
    if active_count == 0:
        raise IncompleteIngestionError("활성 종목 없음 — stocks 테이블 확인 필요")
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(date) FROM daily_prices")
        latest = cur.fetchone()[0]
        if latest is None:
            raise IncompleteIngestionError("daily_prices 비어 있음 — 적재 선행 필요")
        cur.execute("SELECT count(*) FROM daily_prices WHERE date = %s", (latest,))
        rows = cur.fetchone()[0]
    coverage = rows / active_count
    if coverage < threshold:
        raise IncompleteIngestionError(
            f"최신 적재 불완전: date={latest} rows={rows}/{active_count} "
            f"coverage={coverage:.1%} < threshold {threshold:.0%}"
        )
