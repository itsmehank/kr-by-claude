"""변형 시장 사다리 (옵션 c) — 사전등록 v3.2. 백테스트 로컬, production 무접촉.

현행 6규칙 사다리에서 규칙 4·5 만 교체(우선순위 보존):
  4′ confirmed_uptrend = 유효한 FTD 존재 AND dist<6  (close>SMA50 대기·90일 창 제거)
  FTD 유효성 = 발생일 ~ 랠리 저점(FTD 포함 직전 15세션 최저 low) 종가 이탈 시까지
FTD 이력 = market_context_daily.last_follow_through_day carry-forward 복원
(90일 창 내 기록이라 각 이벤트는 누락 없이 포착됨).
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection

from kr_pipeline.common.thresholds import (
    STATUS_CORRECTION_OFF_HIGH_PCT,
    STATUS_DOWNTREND_OFF_HIGH_PCT,
    STATUS_DIST_COUNT_FOR_FTD_INVALIDATION,
    STATUS_FTD_INVALIDATION_DAYS,
)

RALLY_LOW_WINDOW = 15   # FTD 는 저점 후 3~15세션 발생 → 이 윈도가 랠리 바닥 포함


def variant_ladder(*, close: float, sma_50: float | None, sma_200: float | None,
                   off_high_pct: float, dist_count: int,
                   ftd_valid: bool, days_since_ftd: int | None) -> str:
    """v3.2 사다리 — 규칙 1·2·3 은 현행(status.py)과 동일, 4′·5′ 만 교체."""
    # 1. downtrend (현행 동일)
    if (sma_200 is not None and sma_50 is not None
            and close < sma_200 and sma_50 < sma_200
            and off_high_pct < STATUS_DOWNTREND_OFF_HIGH_PCT):
        return "downtrend"
    # 2. correction — 가격 기준 (현행 동일)
    if (off_high_pct < STATUS_CORRECTION_OFF_HIGH_PCT
            and sma_50 is not None and close < sma_50):
        return "correction"
    # 3. correction — distribution 에 의한 FTD 무효화 (현행 동일)
    if (dist_count >= STATUS_DIST_COUNT_FOR_FTD_INVALIDATION
            and ftd_valid and days_since_ftd is not None
            and days_since_ftd > STATUS_FTD_INVALIDATION_DAYS):
        return "correction"
    # 4'. confirmed — FTD 당일부터, 시간 만료 없음, close>SMA50 대기 없음
    if ftd_valid and dist_count < STATUS_DIST_COUNT_FOR_FTD_INVALIDATION:
        return "confirmed_uptrend"
    # 5'. rally_attempt
    if sma_50 is not None and close > sma_50:
        return "rally_attempt"
    return "correction"


def ftd_validity_series(dates: list[date], closes: list[float],
                        lows: list[float], ftd_dates: set[date]) -> dict[date, bool]:
    """일별 'FTD 유효' 여부. 유효 = 최근 FTD 발생 후 랠리 저점 종가 미이탈.

    랠리 저점 = FTD 일 포함 직전 RALLY_LOW_WINDOW 세션의 최저 low.
    새 FTD 발생 시 유효성·저점 갱신(최신 이벤트 기준).
    """
    out: dict[date, bool] = {}
    rally_low: float | None = None
    valid = False
    for i, d in enumerate(dates):
        if d in ftd_dates:
            lo = max(0, i - RALLY_LOW_WINDOW + 1)
            rally_low = min(lows[lo:i + 1])
            valid = True
        if valid and rally_low is not None and closes[i] < rally_low:
            valid = False
        out[d] = valid
    return out


def bottoming_series(dates: list[date], closes: list[float],
                     lows: list[float]) -> dict[date, tuple]:
    """v4.1 bottoming_attempt: 15세션 신저가(레그 저점) → 이후 첫 상승 마감일부터
    랠리 활성, 레그 저점 종가 이탈 시 리셋, 신저가 갱신 시 에피소드 교체.

    반환: date -> (active: bool, episode_id: 레그 저점일 | None).
    O'Neil 변형(신저가일 중간이상 마감 기산)은 미포함 — prereg v4.1 design-judgment.
    """
    out: dict[date, tuple] = {}
    leg_low: float | None = None
    leg_low_d: date | None = None
    leg_low_i: int | None = None
    rally = False
    for i, d in enumerate(dates):
        w = lows[max(0, i - 15):i]
        if not w or lows[i] < min(w):        # 15세션 신저가 → 레그 교체·랠리 리셋
            leg_low, leg_low_d, leg_low_i, rally = lows[i], d, i, False
        elif leg_low is not None:
            if closes[i] < leg_low:          # 레그 저점 종가 이탈 → 랠리 무효
                rally = False
            elif (not rally and leg_low_i is not None and i > leg_low_i
                  and closes[i] > closes[i - 1]):
                rally = True                 # 첫 상승 마감 → 카운트 시작
        out[d] = (rally, leg_low_d if rally else None)
    return out


def compute_market_extras(conn: Connection, index_code: str,
                          end: date) -> dict[date, dict]:
    """v4 파일럿용 시장 부가 시계열: bottoming(활성·에피소드) + FTD 유효 여부."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, close, low FROM index_daily WHERE index_code = %s "
            "AND date <= %s ORDER BY date", (index_code, end))
        rows = cur.fetchall()
        cur.execute(
            "SELECT DISTINCT last_follow_through_day FROM market_context_daily "
            "WHERE index_code = %s AND last_follow_through_day IS NOT NULL",
            (index_code,))
        ftd_dates = {r[0] for r in cur.fetchall()}
    dates = [r[0] for r in rows]
    closes = [float(r[1]) for r in rows]
    lows = [float(r[2]) for r in rows]
    bott = bottoming_series(dates, closes, lows)
    ftd_valid = ftd_validity_series(dates, closes, lows, ftd_dates)
    return {d: {"bottoming": bott[d], "ftd_valid": ftd_valid[d]} for d in dates}


def _sma(vals: list[float], n: int, i: int) -> float | None:
    if i + 1 < n:
        return None
    return sum(vals[i - n + 1:i + 1]) / n


def compute_variant_status(conn: Connection, index_code: str,
                           start: date, end: date) -> dict[date, str]:
    """index_daily + market_context_daily 저장 이력으로 v3.2 사다리 재계산.

    지수 SMA/52주 고점은 index_daily 종가로 재계산(현행 정의 동일), dist_count 와
    FTD 이벤트는 market_context_daily 저장값(carry-forward 복원) 사용.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, close, low FROM index_daily WHERE index_code = %s "
            "AND date <= %s ORDER BY date", (index_code, end))
        rows = cur.fetchall()
        cur.execute(
            "SELECT date, distribution_day_count_last_25, last_follow_through_day "
            "FROM market_context_daily WHERE index_code = %s AND date <= %s "
            "ORDER BY date", (index_code, end))
        ctx = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    dates = [r[0] for r in rows]
    closes = [float(r[1]) for r in rows]
    lows = [float(r[2]) for r in rows]

    # FTD 이벤트 집합 복원 (carry-forward: 컬럼에 등장하는 모든 고유 날짜)
    ftd_dates = {v[1] for v in ctx.values() if v[1] is not None}
    validity = ftd_validity_series(dates, closes, lows, ftd_dates)

    # 최근 FTD 날짜 carry-forward (days_since 계산용 — 90일 창 밖도 유지)
    last_ftd_cf: dict[date, date | None] = {}
    cur_ftd = None
    for d in dates:
        if d in ftd_dates:
            cur_ftd = d
        last_ftd_cf[d] = cur_ftd

    out: dict[date, str] = {}
    for i, d in enumerate(dates):
        if d < start:
            continue
        sma50 = _sma(closes, 50, i)
        sma200 = _sma(closes, 200, i)
        yr_high = max(closes[max(0, i - 251):i + 1])
        off = (closes[i] / yr_high - 1) * 100 if yr_high > 0 else 0.0
        dist = ctx.get(d, (0, None))[0] or 0
        ftd = last_ftd_cf[d]
        out[d] = variant_ladder(
            close=closes[i], sma_50=sma50, sma_200=sma200, off_high_pct=off,
            dist_count=dist, ftd_valid=validity[d] if ftd else False,
            days_since_ftd=(d - ftd).days if ftd else None)
    return out
