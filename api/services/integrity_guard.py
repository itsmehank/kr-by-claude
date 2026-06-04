"""Data integrity guard — cross-table divergence detection.

Phase 0 Step 3 (검증자 v2 §1-2):
- 검사: 최신 거래일에 대해 daily_indicators.adj_close == daily_prices.adj_close,
        daily_prices.adj_volume(보정) == daily_indicators.volume(보정).
- 불일치 → DataIntegrityError raise.
- **명시적 한계**: 본 가드는 *divergence* 검출, *finalized* 가 아니다.
  두 테이블이 동일하게 partial 인 경우 (원인 1 모드) 미검출.
  진짜 freshness 신호는 (γ) pipeline_runs.finished_at 점검 — 별도 백로그.
"""
from __future__ import annotations
from datetime import date
from typing import NamedTuple

from psycopg import Connection


class DataIntegrityError(Exception):
    """Cross-table divergence 감지 시 raise. ticker·date·detail 포함."""

    def __init__(self, ticker: str, on_date: date, p_value: float, i_value: float, column: str):
        self.ticker = ticker
        self.on_date = on_date
        self.p_value = p_value
        self.i_value = i_value
        self.column = column
        self.ratio = (p_value / i_value) if i_value else 0.0
        super().__init__(
            f"Data integrity guard: ticker={ticker} date={on_date} "
            f"daily_prices.{column}={p_value} vs daily_indicators.{column}={i_value} "
            f"(ratio={self.ratio:.4f})"
        )


class IntegrityCheckResult(NamedTuple):
    """단순 OK/FAIL 보다 디테일 — 검사 통과해도 어떤 컬럼 어떤 값 비교했는지 노출."""
    ticker: str
    on_date: date
    p_close: float | None
    i_close: float | None
    p_volume: float | None  # daily_prices.adj_volume(보정) — NUMERIC, float
    i_volume: float | None
    ok: bool
    failed_column: str | None  # ok=False 면 'close' 또는 'volume'


# 허용 오차. float 비교라 정확 일치 대신 1원·1주 미만은 통과.
PRICE_TOLERANCE = 0.01
VOLUME_TOLERANCE = 1.0


def check_data_integrity(conn: Connection, ticker: str, on_date: date) -> IntegrityCheckResult:
    """가장 최근 daily_prices 거래일에 대해 daily_indicators 와 정합 확인.

    Args:
        conn: 활성 DB 연결.
        ticker: 종목 코드.
        on_date: 호출자 시점 (가장 최근 거래일을 이 시점 이전으로 정의).

    Returns:
        IntegrityCheckResult — ok=True 면 통과, ok=False 면 어디 어떻게 불일치.

    Raises:
        DataIntegrityError — 불일치 시 (호출자가 catch 또는 propagate).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.date, p.adj_close, p.adj_volume, i.adj_close, i.volume
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s AND p.date <= %s
             ORDER BY p.date DESC
             LIMIT 1
            """,
            (ticker, on_date),
        )
        row = cur.fetchone()

    if row is None:
        # daily_prices 데이터 자체 없음 — 가드 적용 불가, 호출자가 별도 처리.
        return IntegrityCheckResult(ticker, on_date, None, None, None, None, ok=True, failed_column=None)

    actual_date, p_close, p_volume, i_close, i_volume = row

    # daily_indicators 행 자체가 없으면 LEFT JOIN 에서 NULL — 가드 미적용 (분류 전 종목 등)
    if i_close is None:
        return IntegrityCheckResult(
            ticker, actual_date,
            float(p_close) if p_close is not None else None,
            None,
            float(p_volume) if p_volume is not None else None,  # adj_volume(보정) NUMERIC → float
            None,
            ok=True, failed_column=None,
        )

    p_close_f = float(p_close)
    i_close_f = float(i_close)
    # p_volume = daily_prices.adj_volume(보정), i_volume = daily_indicators.volume(보정)
    p_volume_f = float(p_volume) if p_volume is not None else None
    i_volume_f = float(i_volume) if i_volume is not None else None

    if abs(p_close_f - i_close_f) > PRICE_TOLERANCE:
        raise DataIntegrityError(ticker, actual_date, p_close_f, i_close_f, "adj_close")

    if p_volume_f is not None and i_volume_f is not None:
        if abs(p_volume_f - i_volume_f) > VOLUME_TOLERANCE:
            raise DataIntegrityError(ticker, actual_date, p_volume_f, i_volume_f, "volume")

    return IntegrityCheckResult(
        ticker, actual_date, p_close_f, i_close_f, p_volume_f, i_volume_f,
        ok=True, failed_column=None,
    )
