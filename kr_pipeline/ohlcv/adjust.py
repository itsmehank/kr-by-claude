"""#207 A안 — 기업행위 조정계수 자체 산출·적용 (회신 15·16). Naver 수정주가 의존 제거의 단일 정의.

정의(회신 15): 기준가 = close/(1+등락률/100). 기준가 ≠ 전일 종가인 날 = 조정일, 계수 = 기준가/전일 종가.
  거래재개일도 KRX 정의 그대로(회신 16 (i)) — 사유별 분기 없음. 사유 추정 기록 금지.
판정 정밀도: KRX 등락률(change_pct)은 소수 2자리 반올림 → 기준가 = 전일 종가이면
  |r_impl − change_pct| ≤ 0.005 (반올림 반폭; half-even 경계는 정확히 0.005). 실측(09-14~23 20,714행) 분포:
  ≤0.005 18,753 · (0.005,0.006] 21(경계) · (0.006,1.0] **0** · >1.0 21 → 빈 구간이 판정을 가른다. 따라서
  ADJ_ROUNDING_HALF_WIDTH + ADJ_BOUNDARY_EPS 초과 = 조정일. 새 임계 창작이 아니라 데이터 정밀도에서 유도.
전일 = 직전 **거래일**: 직전 '행'이 직전 거래일이 아니면(스냅샷 차단·종목 누락으로 하루 결측) r_impl 은 2일 수익률이라
  가짜 조정일이 된다 → 사이에 거래일(open_days: 달력 index_daily·이번 배치 스냅샷·차단 일자)이 있으면 판정 보류.
적용: 조정일 e 의 계수는 e **이전** 전 행에 소급(adj_* × coef, adj_volume ÷ coef — Naver 구정의 관례 실측
  k=adj_vol/vol·close/adj_close=1/coef²). e 당일·이후 행은 raw 그대로(새 기준). F(t) = Π_{e>t} coef_e.
두 체제의 경계:
  ADJ_SELF_START(시임) 이전 행의 adj_* = Naver 구정의 이력(정본, 후행 이벤트 소급 포함) — 재적재가 덮지 않는다.
  ADJ_NAVER_HISTORY_THROUGH 이전 조정일은 그 이력에 **이미 소급돼 있다**(실측: 시임 이후 16건 전부 R(08-01)=R(09-11)=Π coef)
  → 기록만 하고 시임 이전 행에 다시 적용하지 않는다(배포 순서·재실행 무관, 이중 소급 방지). 그 이후 조정일만 소급.
  시임 이후 행은 항상 DB 기준 raw × F 로 재유도할 수 있다(rederive_post_seam) — 배치에 없던 행도 포함.
할트: nullify_halt_adj 단일 chokepoint 경유(adj OHLV NULL, adj_close 유지).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd
from psycopg import Connection

from kr_pipeline.ohlcv.store import update_adj_prices
from kr_pipeline.ohlcv.transform import nullify_halt_adj

# 자체 산출 체제 시작일(= #207 오염 시작일, 3원천 대조로 확정).
ADJ_SELF_START = date(2026, 9, 14)
# Naver 이력이 소급 반영한 마지막 날짜 = 구 코드(Naver 경로) 마지막 데이터 적재일(2026-09-26 토 주말 체인 전체 스윕).
# 이 날짜 이하 조정일은 기록만(시임 이전 행에 다시 소급하지 않음). 전제: 라이브 전환(머지·pull)은 09-28(월) 평일 체인 실행
# **전** — 그 뒤 첫 실행부터 새 경로. 재산출 스크립트가 이벤트별 내재 여부를 updated_at 경계로 검증한다.
ADJ_NAVER_HISTORY_THROUGH = date(2026, 9, 26)

ADJ_ROUNDING_HALF_WIDTH = 0.005   # KRX 등락률 소수 2자리 반올림 반폭(%p)
ADJ_BOUNDARY_EPS = 1e-4           # half-even 경계(정확히 0.005) 흡수 — 실측 빈 구간 (0.006, 1.0]

Event = tuple[date, float]


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


def _gap_has_open_day(prev_date: date | None, d: date, open_days: Iterable[date]) -> bool:
    if prev_date is None:
        return False
    return any(prev_date < x < d for x in open_days)


def events_in_frame(raw: pd.DataFrame, *, prev_close: float | None, prev_date: date | None = None,
                    open_days: Iterable[date] = (), min_date: date | None = ADJ_SELF_START) -> list[Event]:
    """배치(raw: date·close·change_pct, 날짜순)에서 조정일 검출. 첫 행의 전일 = DB 직전 행(prev_close/prev_date).
    - change_pct 결측 행은 판정하지 않되 다음 행의 전일로는 쓴다.
    - min_date(기본 시임) 이전 날짜는 조정일로 보지 않는다(Naver 이력에 내재). 신규 종목 자체 산출만 None.
    - 직전 행과 사이에 거래일(open_days)이 있으면 그 행은 판정 보류(직전 행 ≠ 직전 거래일)."""
    out: list[Event] = []
    prev, pdate = _num(prev_close), prev_date
    has_cp = "change_pct" in raw.columns
    days = set(open_days)
    for _, r in raw.sort_values("date").iterrows():
        d = r["date"]
        cp = r["change_pct"] if has_cp else None
        eligible = (min_date is None or d >= min_date) and not _gap_has_open_day(pdate, d, days)
        if eligible and is_adjustment(r["close"], prev, cp):
            out.append((d, coefficient(r["close"], prev, cp)))
        prev, pdate = _num(r["close"]), d
    return out


def factor_curve(dates: list[date], events: list[Event]) -> dict[date, float]:
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


def derive_adj(raw: pd.DataFrame, events: list[Event]) -> pd.DataFrame:
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


# ---------- 달력·DB 조회 ----------

def trading_days(conn: Connection, start: date, end: date | None = None) -> set[date]:
    """index_daily(KOSPI 1001) 날짜 = 거래일 달력(휴일은 적재되지 않음)."""
    with conn.cursor() as cur:
        if end is None:
            cur.execute("SELECT DISTINCT date FROM index_daily WHERE date >= %s", (start,))
        else:
            cur.execute("SELECT DISTINCT date FROM index_daily WHERE date BETWEEN %s AND %s", (start, end))
        return {r[0] for r in cur.fetchall()}


def last_row_before(conn: Connection, ticker: str, d: date) -> tuple[date, float] | tuple[None, None]:
    with conn.cursor() as cur:
        cur.execute("SELECT date, close FROM daily_prices WHERE ticker = %s AND date < %s ORDER BY date DESC LIMIT 1", (ticker, d))
        row = cur.fetchone()
    return (row[0], float(row[1])) if row else (None, None)


def last_close_before(conn: Connection, ticker: str, d: date) -> float | None:
    return last_row_before(conn, ticker, d)[1]


def load_events(conn: Connection, ticker: str) -> list[Event]:
    with conn.cursor() as cur:
        cur.execute("SELECT date, coef FROM adj_factor_events WHERE ticker = %s ORDER BY date", (ticker,))
        return [(d, float(c)) for d, c in cur.fetchall()]


def unrecorded(conn: Connection, ticker: str, events: list[Event]) -> list[Event]:
    known = {d for d, _ in load_events(conn, ticker)}
    return [(d, c) for d, c in events if d not in known]


def detect_events(conn: Connection, ticker: str, *, since: date, lookback_days: int = 30,
                  min_date: date | None = ADJ_SELF_START) -> list[Event]:
    """since 이후 행 중 조정일 → [(date, coef)] (DB 행 + index_daily 달력, events_in_frame 위임)."""
    start = since - timedelta(days=lookback_days)
    with conn.cursor() as cur:
        cur.execute("SELECT date, close, change_pct FROM daily_prices WHERE ticker = %s AND date >= %s ORDER BY date",
                    (ticker, start))
        df = pd.DataFrame(cur.fetchall(), columns=["date", "close", "change_pct"])
    if df.empty:
        return []
    ev = events_in_frame(df, prev_close=None, prev_date=None, open_days=trading_days(conn, start), min_date=min_date)
    return [(d, c) for d, c in ev if d >= since]


def detect_events_all(conn: Connection, *, since: date, tickers: list[str] | None = None,
                      lookback_days: int = 30, min_date: date | None = ADJ_SELF_START) -> dict[str, list[Event]]:
    """전 종목(또는 tickers) 단일 쿼리로 미기록 조정일 검출 → {ticker: [(date, coef)]}. 접촉 0.
    LAG 로 직전 행, index_daily 달력으로 직전 거래일 결측 판정, adj_factor_events LEFT JOIN 으로 기록 여부."""
    start = since - timedelta(days=lookback_days)
    floor = max(since, min_date) if min_date else since
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH r AS (
              SELECT p.ticker, p.date, p.close, p.change_pct,
                     LAG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close,
                     LAG(p.date)  OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_date
                FROM daily_prices p JOIN stocks s ON s.ticker = p.ticker
               WHERE p.date >= %(start)s AND s.delisted_at IS NULL
                 AND (%(tickers)s::text[] IS NULL OR p.ticker = ANY(%(tickers)s::text[]))
            )
            SELECT r.ticker, r.date, r.close, r.change_pct, r.prev_close, r.prev_date
              FROM r LEFT JOIN adj_factor_events e ON e.ticker = r.ticker AND e.date = r.date
             WHERE r.date >= %(floor)s AND r.change_pct IS NOT NULL AND r.prev_close IS NOT NULL AND e.ticker IS NULL
               AND NOT EXISTS (SELECT 1 FROM index_daily i WHERE i.date > r.prev_date AND i.date < r.date)
             ORDER BY r.ticker, r.date
            """,
            {"start": start, "floor": floor, "tickers": tickers},
        )
        rows = cur.fetchall()
    out: dict[str, list[Event]] = {}
    for t, d, close, cp, prev, _pd in rows:
        if is_adjustment(close, prev, cp):
            out.setdefault(t, []).append((d, coefficient(close, prev, cp)))
    return out


# ---------- 기록·적용 ----------

def record_events(conn: Connection, ticker: str, events: list[Event]) -> int:
    """adj_factor_events 에 (종목, 날짜, 계수 + 사실 컬럼 prev_close/close/change_pct) 기록 — 멱등. 반환 = 신규 기록 수."""
    n = 0
    with conn.cursor() as cur:
        for d, coef in events:
            prev = last_close_before(conn, ticker, d)
            cur.execute(
                """
                INSERT INTO adj_factor_events (ticker, date, coef, prev_close, close, change_pct)
                SELECT %s, %s, %s, %s, p.close, p.change_pct FROM daily_prices p WHERE p.ticker = %s AND p.date = %s
                ON CONFLICT (ticker, date) DO NOTHING
                """,
                (ticker, d, coef, prev, ticker, d),
            )
            n += cur.rowcount
    return n


def apply_event(conn: Connection, ticker: str, d: date, coef: float, *, until: date | None = None) -> int:
    """조정일 e 이전 행 소급: adj_* × coef, adj_volume ÷ coef (NULL 은 NULL 유지). until 이후 행 제외. 반환 = 갱신 행 수."""
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


def rederive_post_seam(conn: Connection, ticker: str, *, end: date | None = None) -> int:
    """시임 이후 DB 행을 raw × F(기록된 전 이벤트) 로 재유도(adj 컬럼만, update_adj_prices). 멱등. 반환 = 갱신 행 수."""
    events = load_events(conn, ticker)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, open, high, low, close, volume, value FROM daily_prices "
            "WHERE ticker = %s AND date >= %s AND (%s::date IS NULL OR date <= %s::date) ORDER BY date",
            (ticker, ADJ_SELF_START, end, end))
        raw = pd.DataFrame(cur.fetchall(), columns=["date", "open", "high", "low", "close", "volume", "value"])
    if raw.empty:
        return 0
    for c in ("open", "high", "low", "close", "volume", "value"):
        raw[c] = raw[c].astype(float)
    merged = derive_adj(raw, events)

    def _n(v):
        return None if pd.isna(v) else float(v)
    rows = [(ticker, r["date"], _n(r["adj_close"]), _n(r["adj_high"]), _n(r["adj_low"]), _n(r["adj_open"]), _n(r["adj_volume"]))
            for _, r in merged.iterrows()]
    return update_adj_prices(conn, rows)


def ingest_events(conn: Connection, ticker: str, events: list[Event]) -> dict:
    """신규 조정일 반영의 단일 진입점(증분·drift reload·재산출 스크립트 공용):
    미기록 이벤트만 → 기록 → ADJ_NAVER_HISTORY_THROUGH 이후 이벤트만 시임 이전 행 소급(until=시임) →
    시임 이후 전 행 DB 기준 재유도(배치에 없던 행 포함). 반환 {recorded, applied_rows, rederived_rows}."""
    new = unrecorded(conn, ticker, events)
    if not new:
        return {"recorded": 0, "applied_rows": 0, "rederived_rows": 0}
    recorded = record_events(conn, ticker, new)
    applied = 0
    for d, c in new:
        if d > ADJ_NAVER_HISTORY_THROUGH:
            applied += apply_event(conn, ticker, d, c, until=ADJ_SELF_START)
    rederived = rederive_post_seam(conn, ticker)
    return {"recorded": recorded, "applied_rows": applied, "rederived_rows": rederived}
