"""#207 A안 — 기업행위 조정계수 자체 산출·적용 (회신 15·16). Naver 수정주가 의존 제거의 단일 정의.

정의(회신 15): 기준가 = close/(1+등락률/100). 기준가 ≠ 전일 종가인 날 = 조정일, 계수 = 기준가/전일 종가.
  거래재개일도 KRX 정의 그대로(회신 16 (i)) — 사유별 분기 없음. 사유 추정 기록 금지.
판정 정밀도: KRX 등락률(change_pct)은 소수 2자리 반올림 → 기준가 = 전일 종가이면
  |r_impl − change_pct| ≤ 0.005 (반올림 반폭; half-even 경계는 정확히 0.005). 실측(09-14~23 20,714행) 분포:
  ≤0.005 18,753 · (0.005,0.006] 21(경계) · (0.006,1.0] **0** · >1.0 21 → 빈 구간이 판정을 가른다. 따라서
  ADJ_ROUNDING_HALF_WIDTH + ADJ_BOUNDARY_EPS 초과 = 조정일. 새 임계 창작이 아니라 데이터 정밀도에서 유도.
적용: 조정일 e 의 계수는 e **이전** 전 행에 소급(adj_* × coef, adj_volume ÷ coef — Naver 구정의 관례 실측
  k=adj_vol/vol·close/adj_close=1/coef²). e 당일·이후 행은 raw 그대로(새 기준). F(t) = Π_{e>t} coef_e.
할트: nullify_halt_adj 단일 chokepoint 경유(adj OHLV NULL, adj_close 유지).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from psycopg import Connection

from kr_pipeline.ohlcv.transform import nullify_halt_adj

# 자체 산출 체제 시작일(= #207 오염 시작일, 3원천 대조로 확정). 이 날짜 이전 행의 adj_* 는 Naver 구정의 이력이
# 정본(후행 이벤트 소급 포함)이며 재적재가 덮어쓰지 않는다(store.upsert adj_from). 이후 행 = raw × F(t).
# 시임 이후 발생한 조정일의 계수는 시임 이전 행에도 소급된다(apply_event) — 이력 일관성은 재산출 스크립트가 1회 검증.
ADJ_SELF_START = date(2026, 9, 14)

ADJ_ROUNDING_HALF_WIDTH = 0.005   # KRX 등락률 소수 2자리 반올림 반폭(%p)
ADJ_BOUNDARY_EPS = 1e-4           # half-even 경계(정확히 0.005) 흡수 — 실측 빈 구간 (0.006, 1.0]


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def is_adjustment(close, prev_close, change_pct) -> bool:
    """기준가 ≠ 전일 종가 (등락률 정밀도 초과 차이). 입력 결측·전일 종가 0 → False(판정하지 않음)."""
    c, p, r = _num(close), _num(prev_close), _num(change_pct)
    if c is None or p is None or r is None or p <= 0:
        return False
    r_impl = (c / p - 1.0) * 100.0
    return abs(r_impl - r) > ADJ_ROUNDING_HALF_WIDTH + ADJ_BOUNDARY_EPS


def coefficient(close, prev_close, change_pct) -> float:
    """계수 = 기준가/전일 종가, 기준가 = close/(1+등락률/100)."""
    c, p, r = float(close), float(prev_close), float(change_pct)
    return (c / (1.0 + r / 100.0)) / p


def factor_curve(dates: list[date], events: list[tuple[date, float]]) -> dict[date, float]:
    """F(t) = Π_{e > t} coef_e — 최신일 1.0, 과거로 갈수록 누적. 조정일 당일은 새 기준(포함 안 함)."""
    ev = sorted(events)
    out: dict[date, float] = {}
    for d in dates:
        f = 1.0
        for ed, c in ev:
            if ed > d:
                f *= c
        out[d] = f
    return out


def derive_adj(raw: pd.DataFrame, events: list[tuple[date, float]]) -> pd.DataFrame:
    """raw OHLCV + 조정 이벤트 → adj_open/high/low/close = raw × F(t), adj_volume = volume / F(t), 할트 정규화."""
    if raw.empty:
        return raw.assign(adj_close=pd.Series(dtype=float), adj_high=pd.Series(dtype=float),
                          adj_low=pd.Series(dtype=float), adj_open=pd.Series(dtype=float),
                          adj_volume=pd.Series(dtype=float))
    f = factor_curve(list(raw["date"]), events)
    F = raw["date"].map(f).astype(float)
    out = raw.copy()
    out["adj_close"] = out["close"].astype(float) * F
    out["adj_high"] = out["high"].astype(float) * F
    out["adj_low"] = out["low"].astype(float) * F
    out["adj_open"] = out["open"].astype(float) * F
    out["adj_volume"] = out["volume"].astype(float) / F
    return nullify_halt_adj(out)


def events_in_frame(raw: pd.DataFrame, *, prev_close: float | None) -> list[tuple[date, float]]:
    """증분 배치(raw: date·close·change_pct, 날짜순)에서 조정일 검출. 첫 행의 전일 종가 = DB 직전 종가(prev_close).
    change_pct 결측 행은 판정하지 않되 다음 행의 전일 종가로는 쓴다."""
    out: list[tuple[date, float]] = []
    prev = _num(prev_close)
    has_cp = "change_pct" in raw.columns
    for _, r in raw.sort_values("date").iterrows():
        cp = r["change_pct"] if has_cp else None
        if is_adjustment(r["close"], prev, cp):
            out.append((r["date"], coefficient(r["close"], prev, cp)))
        prev = _num(r["close"])
    return out


def detect_events(conn: Connection, ticker: str, *, since: date, lookback_days: int = 30) -> list[tuple[date, float]]:
    """since 이후 행 중 조정일 → [(date, coef)]. 전일 종가는 DB 직전 행(LAG) — since 앞 lookback 으로 확보."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, close, change_pct, LAG(close) OVER (ORDER BY date) AS prev_close
              FROM daily_prices
             WHERE ticker = %s AND date >= %s
             ORDER BY date
            """,
            (ticker, since - timedelta(days=lookback_days)),
        )
        rows = cur.fetchall()
    out: list[tuple[date, float]] = []
    for d, close, cp, prev in rows:
        if d < since:
            continue
        if is_adjustment(close, prev, cp):
            out.append((d, coefficient(close, prev, cp)))
    return out


def record_events(conn: Connection, ticker: str, events: list[tuple[date, float]]) -> int:
    """adj_factor_events 에 (종목, 날짜, 계수) 기록 — 멱등(ON CONFLICT DO NOTHING). 반환 = 신규 기록 수."""
    if not events:
        return 0
    n = 0
    with conn.cursor() as cur:
        for d, coef in events:
            cur.execute(
                """
                INSERT INTO adj_factor_events (ticker, date, coef, prev_close, close, change_pct)
                SELECT %s, %s, %s,
                       (SELECT close FROM daily_prices p2 WHERE p2.ticker = %s AND p2.date < %s ORDER BY p2.date DESC LIMIT 1),
                       p.close, p.change_pct
                  FROM daily_prices p WHERE p.ticker = %s AND p.date = %s
                ON CONFLICT (ticker, date) DO NOTHING
                """,
                (ticker, d, coef, ticker, d, ticker, d),
            )
            n += cur.rowcount
    return n


def apply_event(conn: Connection, ticker: str, d: date, coef: float, *, until: date | None = None) -> int:
    """조정일 e 이전 전 행 소급: adj_* × coef, adj_volume ÷ coef (NULL 은 NULL 유지). 반환 = 갱신 행 수.
    until: 이 날짜 이후 행은 제외 — 증분 배치 행은 derive_adj 가 이미 F 를 적용했으므로 이중 적용 방지."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daily_prices
               SET adj_close = adj_close * %(c)s, adj_high = adj_high * %(c)s, adj_low = adj_low * %(c)s,
                   adj_open = adj_open * %(c)s, adj_volume = adj_volume / %(c)s, updated_at = NOW()
             WHERE ticker = %(t)s AND date < %(d)s AND (%(u)s::date IS NULL OR date < %(u)s::date)
            """,
            {"c": coef, "t": ticker, "d": d, "u": until},
        )
        return cur.rowcount


def load_events(conn: Connection, ticker: str) -> list[tuple[date, float]]:
    with conn.cursor() as cur:
        cur.execute("SELECT date, coef FROM adj_factor_events WHERE ticker = %s ORDER BY date", (ticker,))
        return [(d, float(c)) for d, c in cur.fetchall()]


def last_close_before(conn: Connection, ticker: str, d: date) -> float | None:
    with conn.cursor() as cur:
        cur.execute("SELECT close FROM daily_prices WHERE ticker = %s AND date < %s ORDER BY date DESC LIMIT 1", (ticker, d))
        row = cur.fetchone()
    return float(row[0]) if row else None
