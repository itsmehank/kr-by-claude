"""#122 — 확정 누락 이벤트의 참조 adj 소급 재적재(DART 배율 기반, 1회성). 외부 접촉 0.

대상 = 1단계 판독 JSON 의 missing_confirmed 행. 조정일 = gap_date(무상=권리락일, 병합=거래 재개일 —
raw 가 실제로 뛴 날; KRX 기준가 정의와 동일), 계수 = expected_ratio(무상 1/(1+배정), 병합 N).
적용 = adjust.apply_event(조정일 이전 전 행 adj_* × coef, adj_volume ÷ coef) + adj_factor_events 기록.
adjust.ingest_events 를 쓰지 않는 이유: 시임(ADJ_NAVER_HISTORY_THROUGH) 이전 이벤트를 "Naver 이력에
내재"로 보고 소급하지 않는 정책이 바로 이 18건에서 틀린 가정이기 때문(판독 §5).
사전 검사: 조정일 직전 행 factor(adj/close) ÷ 당일 factor 가 ≈1 일 때만 적용(아직 누락). 이미 coef 근방이면
그 사이 조정된 것 → 거부(이중 소급 방지). 기록이 있으면 skip(멱등).
지표 재계산 = pipeline.drift.reload_ticker 동형(일봉 Phase A → 주봉 재집계 → 주봉 Phase A, 그 종목만;
횡단면 RS 는 체인이 확정 — 전 종목 과거 RS 는 건드리지 않음, #124).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from psycopg import Connection

from kr_pipeline.indicators import modes as indicators
from kr_pipeline.ohlcv import adjust
from kr_pipeline.weekly import modes as weekly

MISSING_TOL = 1.15        # factor 비 ≈1 판정 폭(1단계 SIZE_TOL 동일)
ADJUSTED_TOL = 1.5        # factor 비가 coef 근방(이미 조정됨) 판정 폭(1단계 CR_SIZE_TOL 동일)


@dataclass(frozen=True)
class Target:
    ticker: str
    date: date            # 조정일(gap_date)
    coef: float
    kind: str
    ex_date: date
    rcept_no: str | None


def load_targets(audit: dict) -> list[Target]:
    out = []
    for r in audit["rows"]:
        if r.get("status") != "missing_confirmed":
            continue
        d = r.get("gap_date") or r["ex_date"]
        out.append(Target(r["ticker"], date.fromisoformat(d), float(r["expected_ratio"]), r["kind"],
                          date.fromisoformat(r["ex_date"]), r.get("rcept_no")))
    return sorted(out, key=lambda t: (t.ticker, t.date))


def _factor_ratio(conn: Connection, t: Target) -> float | None:
    """직전 행 factor / 조정일 행 factor (factor = adj_close/close). 어느 한쪽이 없으면 None."""
    with conn.cursor() as cur:
        cur.execute("SELECT adj_close::float / close::float FROM daily_prices WHERE ticker=%s AND date<%s "
                    "AND close>0 AND adj_close>0 ORDER BY date DESC LIMIT 1", (t.ticker, t.date))
        prev = cur.fetchone()
        cur.execute("SELECT adj_close::float / close::float FROM daily_prices WHERE ticker=%s AND date=%s "
                    "AND close>0 AND adj_close>0", (t.ticker, t.date))
        day = cur.fetchone()
    if not prev or not day:
        return None
    return prev[0] / day[0]


def _state(ratio: float | None, coef: float) -> str:
    if ratio is None:
        return "no_rows"
    if abs(math.log(ratio)) <= math.log(MISSING_TOL):
        return "missing"
    if abs(math.log(ratio / coef)) <= math.log(ADJUSTED_TOL):
        return "already_adjusted"
    return "ambiguous"


def plan_target(conn: Connection, t: Target) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM daily_prices WHERE ticker=%s AND date<%s", (t.ticker, t.date))
        rows_before = cur.fetchone()[0]
        cur.execute("SELECT 1 FROM adj_factor_events WHERE ticker=%s AND date=%s", (t.ticker, t.date))
        recorded = cur.fetchone() is not None
    ratio = _factor_ratio(conn, t)
    return {"ticker": t.ticker, "date": t.date.isoformat(), "coef": t.coef, "kind": t.kind,
            "rows_before": rows_before, "recorded": recorded, "factor_ratio": ratio,
            "state": "recorded" if recorded else _state(ratio, t.coef)}


def backup_rows(conn: Connection, t: Target) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT date, adj_close, adj_high, adj_low, adj_open, adj_volume FROM daily_prices "
                    "WHERE ticker=%s AND date<%s ORDER BY date", (t.ticker, t.date))
        return [{"date": d.isoformat(), "adj_close": _f(a), "adj_high": _f(h), "adj_low": _f(lo),
                 "adj_open": _f(o), "adj_volume": _f(v)} for d, a, h, lo, o, v in cur.fetchall()]


def _f(v):
    return None if v is None else float(v)


def apply_target(conn: Connection, t: Target) -> dict:
    """적용(기록 + 소급). 호출부가 트랜잭션 경계(commit/rollback)를 관리한다."""
    p = plan_target(conn, t)
    base = {"ticker": t.ticker, "date": t.date.isoformat(), "coef": t.coef, "plan": p,
            "applied_rows": 0, "recorded": 0, "skipped": None, "factor_ratio_after": None}
    if p["recorded"]:
        return {**base, "skipped": "recorded"}
    if p["state"] != "missing":
        return {**base, "skipped": p["state"]}
    recorded = adjust.record_events(conn, t.ticker, [(t.date, t.coef)])
    if recorded != 1:
        raise RuntimeError(f"{t.ticker} {t.date}: 조정일 행이 없어 이벤트 기록 실패")
    applied = adjust.apply_event(conn, t.ticker, t.date, t.coef, until=None)
    after = _factor_ratio(conn, t)
    if after is None or abs(math.log(after / t.coef)) > math.log(MISSING_TOL):
        raise RuntimeError(f"{t.ticker} {t.date}: 적용 후 factor 점프 {after} ≠ coef {t.coef}")
    return {**base, "applied_rows": applied, "recorded": recorded, "factor_ratio_after": after}


def restore_rows(conn: Connection, t: Target, backup: list[dict]) -> int:
    n = 0
    with conn.cursor() as cur:
        for r in backup:
            cur.execute("UPDATE daily_prices SET adj_close=%s, adj_high=%s, adj_low=%s, adj_open=%s, adj_volume=%s, "
                        "updated_at=NOW() WHERE ticker=%s AND date=%s",
                        (r["adj_close"], r["adj_high"], r["adj_low"], r["adj_open"], r["adj_volume"],
                         t.ticker, date.fromisoformat(r["date"])))
            n += cur.rowcount
        cur.execute("DELETE FROM adj_factor_events WHERE ticker=%s AND date=%s", (t.ticker, t.date))
    return n


def recompute_ticker(conn: Connection, ticker: str) -> dict:
    r_d = indicators.recompute_ticker_daily(conn, ticker)
    r_w = weekly.run(conn, weekly.Mode.FULL_REFRESH, only_tickers=[ticker])
    r_iw = indicators.recompute_ticker_weekly(conn, ticker)
    return {"indicators_daily": r_d, "weekly": r_w.rows_affected, "indicators_weekly": r_iw}
