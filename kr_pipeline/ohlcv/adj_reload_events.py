"""#122 — 확정 누락 이벤트의 참조 adj 소급 재적재(DART 배율 기반, 1회성). 외부 접촉 0.

대상 = 1단계 판독 JSON 의 missing_confirmed 행 — 본 모듈의 FROZEN_TARGETS(18건) 와 집합이 같아야 한다(동결;
JSON 재생성으로 날짜·계수가 바뀌어 같은 이벤트가 다른 날짜로 이중 적용되는 것을 막는다 — 리뷰 R1 ②).
조정일 = gap_date(무상=권리락일, 병합=거래 재개일 — raw 가 실제로 뛴 날; KRX 기준가 정의와 동일),
계수 = expected_ratio(무상 1/(1+배정), 병합 cr_rt 기반 — 003060·007460 은 14.9925 로 명목 15 와 0.05% 차, 임계 밖 무해).
적용 = adjust.apply_event(조정일 이전 전 행 adj_* × coef, adj_volume ÷ coef) + adj_factor_events 기록.
adjust.ingest_events 를 쓰지 않는 이유: 시임(ADJ_NAVER_HISTORY_THROUGH) 이전 이벤트를 "Naver 이력에
내재"로 보고 소급하지 않는 정책이 바로 이 18건에서 틀린 가정이기 때문(판독 §5). 역으로 시임 이후 조정일은
본 경로가 아니라 ingest_events 몫 — 거부(리뷰 R1 ③).
사전 검사(plan): 조정일 직전 행 factor(adj/close) ÷ 당일 factor 가 ≈1 일 때만 'missing'(아직 누락). 이미 coef
근방이면 'already_adjusted'(이중 소급 방지), 두 밴드가 겹치면 'ambiguous'(무상 밴드 1.15·병합 1.5 — 1단계
SIZE_TOL/CR_SIZE_TOL). 같은 종목 ±60일 안에 coef 근방 이벤트 기록이 있으면 'ambiguous_nearby_event'.
적용 후 검증 = 물리 불변식: adj_close(직전)/adj_close(당일) 이 KRX 일일 가격제한 밴드(±30%) 안 — 항등식이 아님(리뷰 R1 ①).
지표 재계산 = pipeline.drift.reload_ticker 동형(일봉 Phase A → 주봉 재집계 → 주봉 Phase A, 그 종목만).
Phase B/C(rs_rating·minervini_pass)·bt_rs 는 횡단면이라 재계산하지 않는다(사용자 결정 11-03, #124 로) — 즉
오염 창의 과거 minervini_pass 는 그대로 남고 소급 표기만 유지된다(리뷰 R1 메모 ⑨).
부작용: 적용 행 updated_at=NOW()(restore 도 원복 안 함), adj_factor_events 에 출처 열 없음(DART 유래는 결과 JSON 의
rcept_no 로만 식별, change_pct NULL).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from psycopg import Connection

from kr_pipeline.indicators import modes as indicators
from kr_pipeline.ohlcv import adjust
from kr_pipeline.weekly import modes as weekly

MISSING_TOL = 1.15                       # factor 비 ≈1 판정 폭(1단계 SIZE_TOL)
ADJUSTED_TOL = {"fric": 1.15, "cr": 1.5}  # factor 비가 coef 근방(이미 조정됨) 판정 폭(1단계 SIZE_TOL / CR_SIZE_TOL)
CONTINUITY_TOL = 1.30                    # 적용 후 adj_close 직전/당일 비 허용 밴드(KRX 일일 가격제한 ±30%)
NEARBY_DAYS = 60

# 동결 대상(판독 §5 확정 18건): (ticker, 조정일 gap_date, coef). JSON 과 집합 동일성을 load_targets 가 검사.
FROZEN_TARGETS: frozenset[tuple[str, str, float]] = frozenset({
    ("003060", "2026-05-08", 14.9925), ("007460", "2026-05-08", 14.9925), ("009310", "2026-05-11", 5.0),
    ("012170", "2025-03-06", 10.0), ("050090", "2023-05-08", 4.0), ("067370", "2021-01-07", 0.6667),
    ("078860", "2023-12-27", 20.0), ("079970", "2024-08-21", 10.0), ("179530", "2021-05-26", 0.3333),
    ("221800", "2023-02-23", 0.25), ("228760", "2017-11-09", 0.3333), ("228760", "2018-09-14", 0.5),
    ("232680", "2017-06-22", 0.6667), ("232830", "2020-09-04", 0.2), ("253840", "2018-12-07", 0.5),
    ("270660", "2021-02-17", 0.25), ("303360", "2020-07-21", 0.5), ("388610", "2023-07-24", 0.3333),
})


@dataclass(frozen=True)
class Target:
    ticker: str
    date: date            # 조정일(gap_date)
    coef: float
    kind: str
    ex_date: date
    rcept_no: str | None


def load_targets(audit: dict, *, frozen: frozenset | None = FROZEN_TARGETS) -> list[Target]:
    out = []
    for r in audit["rows"]:
        if r.get("status") != "missing_confirmed":
            continue
        d = r.get("gap_date") or r["ex_date"]
        out.append(Target(r["ticker"], date.fromisoformat(d), float(r["expected_ratio"]), r["kind"],
                          date.fromisoformat(r["ex_date"]), r.get("rcept_no")))
    if frozen is not None:
        got = {(t.ticker, t.date.isoformat(), round(t.coef, 4)) for t in out}
        if got != frozen:
            raise ValueError(f"대상 집합이 동결본과 다름: +{sorted(got - frozen)} -{sorted(frozen - got)}")
    return sorted(out, key=lambda t: (t.ticker, t.date))


def _rows(conn: Connection, t: Target) -> tuple[tuple | None, tuple | None]:
    """직전 행·조정일 행 (close, adj_close). 없으면 None."""
    with conn.cursor() as cur:
        cur.execute("SELECT close::float, adj_close::float FROM daily_prices WHERE ticker=%s AND date<%s "
                    "AND close>0 AND adj_close>0 ORDER BY date DESC LIMIT 1", (t.ticker, t.date))
        prev = cur.fetchone()
        cur.execute("SELECT close::float, adj_close::float FROM daily_prices WHERE ticker=%s AND date=%s "
                    "AND close>0 AND adj_close>0", (t.ticker, t.date))
        day = cur.fetchone()
    return prev, day


def _factor_ratio(prev, day) -> float | None:
    if not prev or not day:
        return None
    return (prev[1] / prev[0]) / (day[1] / day[0])


def _within(x: float, tol: float) -> bool:
    return abs(math.log(x)) <= math.log(tol)


def _state(ratio: float | None, coef: float, kind: str) -> str:
    if ratio is None:
        return "no_rows"
    missing = _within(ratio, MISSING_TOL)
    adjusted = _within(ratio / coef, ADJUSTED_TOL.get(kind, 1.5))
    if missing and adjusted:
        return "ambiguous"
    if missing:
        return "missing"
    if adjusted:
        return "already_adjusted"
    return "ambiguous"


def plan_target(conn: Connection, t: Target) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM daily_prices WHERE ticker=%s AND date<%s", (t.ticker, t.date))
        rows_before = cur.fetchone()[0]
        cur.execute("SELECT 1 FROM adj_factor_events WHERE ticker=%s AND date=%s", (t.ticker, t.date))
        recorded = cur.fetchone() is not None
        cur.execute("SELECT date, coef::float FROM adj_factor_events WHERE ticker=%s AND date<>%s "
                    "AND date BETWEEN %s AND %s", (t.ticker, t.date, t.date - timedelta(days=NEARBY_DAYS),
                                                   t.date + timedelta(days=NEARBY_DAYS)))
        nearby = [(d.isoformat(), c) for d, c in cur.fetchall() if _within(c / t.coef, 1.5)]
    prev, day = _rows(conn, t)
    ratio = _factor_ratio(prev, day)
    raw_gap_x_coef = (prev[0] / day[0]) * t.coef if prev and day else None   # 적용 후 adj 연속성 예상치(≈1)
    if t.date > adjust.ADJ_NAVER_HISTORY_THROUGH:
        state = "post_seam_use_ingest_events"
    elif recorded:
        state = "recorded"
    elif nearby:
        state = "ambiguous_nearby_event"
    else:
        state = _state(ratio, t.coef, t.kind)
    return {"ticker": t.ticker, "date": t.date.isoformat(), "coef": t.coef, "kind": t.kind,
            "rows_before": rows_before, "recorded": recorded, "factor_ratio": ratio,
            "raw_gap_x_coef": raw_gap_x_coef, "nearby_events": nearby, "state": state}


def backup_rows(conn: Connection, t: Target) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT date, adj_close, adj_high, adj_low, adj_open, adj_volume FROM daily_prices "
                    "WHERE ticker=%s AND date<%s ORDER BY date", (t.ticker, t.date))
        return [{"date": d.isoformat(), "adj_close": _f(a), "adj_high": _f(h), "adj_low": _f(lo),
                 "adj_open": _f(o), "adj_volume": _f(v)} for d, a, h, lo, o, v in cur.fetchall()]


def _f(v):
    return None if v is None else float(v)


def apply_target(conn: Connection, t: Target) -> dict:
    """적용(기록 + 소급). 호출부가 트랜잭션 경계(commit/rollback)를 관리한다. 적용 조건 = plan state 'missing'."""
    p = plan_target(conn, t)
    base = {"ticker": t.ticker, "date": t.date.isoformat(), "coef": t.coef, "plan": p,
            "applied_rows": 0, "recorded": 0, "skipped": None, "continuity_after": None}
    if p["state"] != "missing":
        return {**base, "skipped": p["state"]}
    recorded = adjust.record_events(conn, t.ticker, [(t.date, t.coef)])
    if recorded != 1:
        raise RuntimeError(f"{t.ticker} {t.date}: 조정일 행이 없어 이벤트 기록 실패")
    applied = adjust.apply_event(conn, t.ticker, t.date, t.coef, until=None)
    prev, day = _rows(conn, t)
    cont = prev[1] / day[1] if prev and day else None      # 적용 후 adj_close 직전/당일 — 물리 불변식
    if cont is None or not _within(cont, CONTINUITY_TOL):
        raise RuntimeError(f"{t.ticker} {t.date}: 적용 후 adj_close 연속성 {cont} 이 ±30% 밴드 밖")
    return {**base, "applied_rows": applied, "recorded": recorded, "continuity_after": cont}


def restore_rows(conn: Connection, t: Target, backup: list[dict], *, backup_time=None) -> dict:
    """백업으로 복원. 이벤트 기록이 없으면(적용된 적 없음) 아무것도 하지 않는다. backup_time 이후 갱신된 행이 있으면 경고."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM adj_factor_events WHERE ticker=%s AND date=%s", (t.ticker, t.date))
        if cur.fetchone() is None:
            return {"restored_rows": 0, "skipped": "not_applied", "warning": None}
        warning = None
        if backup_time is not None:
            cur.execute("SELECT count(*) FROM daily_prices WHERE ticker=%s AND date<%s AND updated_at>%s",
                        (t.ticker, t.date, backup_time))
            later = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM daily_prices WHERE ticker=%s AND date<%s", (t.ticker, t.date))
            total = cur.fetchone()[0]
            if later != total:    # 적용으로 전 행이 갱신됐어야 함 — 그 외 패턴은 다른 갱신 혼입 가능
                warning = f"백업 이후 갱신 행 {later}/{total} — 적용 외 갱신 혼입 가능"
        n = 0
        for r in backup:
            cur.execute("UPDATE daily_prices SET adj_close=%s, adj_high=%s, adj_low=%s, adj_open=%s, adj_volume=%s, "
                        "updated_at=NOW() WHERE ticker=%s AND date=%s",
                        (r["adj_close"], r["adj_high"], r["adj_low"], r["adj_open"], r["adj_volume"],
                         t.ticker, date.fromisoformat(r["date"])))
            n += cur.rowcount
        cur.execute("DELETE FROM adj_factor_events WHERE ticker=%s AND date=%s", (t.ticker, t.date))
    return {"restored_rows": n, "skipped": None, "warning": warning}


def recompute_ticker(conn: Connection, ticker: str) -> dict:
    """drift.reload_ticker 동형. weekly.run 이 자체 commit 하므로 종목 단위 원자성은 없음 — 실패 시 복구는
    drift.reload_ticker(멱등) 재실행."""
    r_d = indicators.recompute_ticker_daily(conn, ticker)
    r_w = weekly.run(conn, weekly.Mode.FULL_REFRESH, only_tickers=[ticker])
    r_iw = indicators.recompute_ticker_weekly(conn, ticker)
    return {"indicators_daily": r_d, "weekly": r_w.rows_affected, "indicators_weekly": r_iw}
