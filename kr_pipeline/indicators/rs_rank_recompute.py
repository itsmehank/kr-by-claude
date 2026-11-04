"""#124 — 저장 지표의 RS 순위(rs_rating)를 저장 수정종가로부터 현재 빈티지로 다시 매기는 표적 재계산.

배경: 증분 파이프라인은 최근 창(일봉 30일·주봉 4주)만 Phase B(날짜별 전 종목 백분위)를 다시 돌리므로, 기업행위로
adj_close 이력이 소급 조정되면(#122 재적재 등) 과거 날짜의 저장 rs_rating 은 옛 adj 기준 값으로 굳는다(빈티지 드리프트).
방법 1(2026-11-04 결정): 컬럼 추가 없이 daily_prices/weekly_prices 의 adj_close 를 종목별로 읽어 기존
compute_ibd_strength_factor → assign_rs_rating_percentiles 로 날짜별 순위를 즉석 계산하고, 저장값과 다른 셀만 쓴다.

유니버스 = 그 날짜에 지표 행이 있는 종목(지표 테이블의 DISTINCT ticker 전체를 읽고, 날짜별 N 은 그 날짜 행 보유 종목 수).
"현재 활성 종목"을 쓰면 저장 순위(마지막 전체 산출 시점의 활성 종목) 와 N 이 달라 전 종목 순위가 ±1 흔들린다(리뷰 R1-1).
행 필터 없음: 거래정지 행도 adj_close 는 carry 값이라 Phase A 와 동일하게 모든 행을 시계열에 둔다(shift 위치 동일).
"""
from __future__ import annotations

import pandas as pd
from psycopg import Connection

from kr_pipeline.indicators.compute.rs_rating import assign_rs_rating_percentiles, compute_ibd_strength_factor
from kr_pipeline.indicators.modes import Target

SF_Q: dict[Target, tuple[int, int, int, int]] = {
    Target.DAILY: (63, 126, 189, 252),
    Target.WEEKLY: (13, 26, 39, 52),
}

_TABLES: dict[Target, tuple[str, str, str]] = {
    # (가격 테이블, 지표 테이블, 날짜 컬럼)
    Target.DAILY: ("daily_prices", "daily_indicators", "date"),
    Target.WEEKLY: ("weekly_prices", "weekly_indicators", "week_end_date"),
}


def tables(target: Target) -> tuple[str, str, str]:
    return _TABLES[target]


def universe_tickers(conn: Connection, target: Target) -> list[str]:
    """지표 테이블에 행이 하나라도 있는 종목 전체(상폐 포함). 활성 여부를 보지 않는다."""
    _, ind, _ = tables(target)
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT ticker FROM {ind} ORDER BY ticker")
        return [r[0] for r in cur.fetchall()]


def _series(conn: Connection, target: Target, ticker: str, end) -> pd.Series:
    prices, _, dcol = tables(target)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {dcol}, adj_close FROM {prices} WHERE ticker = %s AND {dcol} <= %s ORDER BY {dcol}",
            (ticker, end),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.Series(dtype=float, name=ticker)
    idx = [r[0] for r in rows]
    vals = [float(r[1]) if r[1] is not None else float("nan") for r in rows]
    return pd.Series(vals, index=pd.Index(idx), name=ticker, dtype=float)


def strength_table(conn: Connection, target: Target, *, tickers: list[str], end) -> pd.DataFrame:
    """날짜(index, 오름차순) × 종목(columns) 강도 점수. 종목별 SELECT(스트리밍) → SF → concat(axis=1).

    종목이 그 날짜에 행이 없으면 NaN(= Phase B 캐시에 그 날짜가 없는 것과 같음 → N 에서 제외).
    """
    q = SF_Q[target]
    cols: list[pd.Series] = []
    for t in tickers:
        s = _series(conn, target, t, end)
        if s.empty:
            continue
        cols.append(compute_ibd_strength_factor(s, *q).rename(t))
    if not cols:
        return pd.DataFrame(dtype=float)
    return pd.concat(cols, axis=1).sort_index()


def rank_table(sf: pd.DataFrame, dates: list) -> pd.DataFrame:
    """날짜별 assign_rs_rating_percentiles(이미 round→int 정수화; Phase B 의 int(rating) 은 무연산) → Int64(NaN → <NA>)."""
    out = {}
    for d in dates:
        if d not in sf.index:
            continue
        out[d] = assign_rs_rating_percentiles(sf.loc[d])
    if not out:
        return pd.DataFrame(dtype="Int64")
    df = pd.DataFrame(out).T
    df.index.name = None
    return df.astype("float").round().astype("Int64")


# ---------------------------------------------------------------- 영향 구간

from dataclasses import dataclass  # noqa: E402
from datetime import date  # noqa: E402

ROWS_AFTER: dict[Target, int] = {Target.DAILY: 252, Target.WEEKLY: 52}


@dataclass(frozen=True)
class Window:
    """사건 종목의 행 기준 [gap 행, gap 행 + rows_after − 1] (양끝 포함).

    강도 점수는 t 와 t−q4 행(일봉 252·주봉 52)까지 보므로, 재적재가 gap 이전 행만 ×coef 했을 때 비율이 바뀌는 날짜는
    정확히 이 구간이다(그 앞은 네 시점이 같은 배수, 그 뒤는 네 시점이 모두 새 값). 행이 모자라면 마지막 행까지.
    """
    ticker: str
    start: date
    end: date


def event_windows(conn: Connection, target: Target, events: list[tuple[str, date]]) -> list[Window]:
    prices, _, dcol = tables(target)
    n = ROWS_AFTER[target]
    out: list[Window] = []
    with conn.cursor() as cur:
        for ticker, gap in events:
            cur.execute(
                f"SELECT {dcol} FROM {prices} WHERE ticker = %s AND {dcol} >= %s ORDER BY {dcol} LIMIT %s",
                (ticker, gap, n),
            )
            rows = [r[0] for r in cur.fetchall()]
            if rows:
                out.append(Window(ticker, rows[0], rows[-1]))
    return out


def affected_dates(conn: Connection, target: Target, windows: list[Window]) -> list[date]:
    """윈도별 날짜를 실제 지표 날짜로 펼쳐 합집합·정렬."""
    _, ind, dcol = tables(target)
    acc: set[date] = set()
    with conn.cursor() as cur:
        for w in windows:
            cur.execute(f"SELECT DISTINCT {dcol} FROM {ind} WHERE {dcol} BETWEEN %s AND %s", (w.start, w.end))
            acc.update(r[0] for r in cur.fetchall())
    return sorted(acc)


def all_dates(conn: Connection, target: Target) -> list[date]:
    """전 기간 모드(--full): 지표 테이블의 모든 날짜."""
    _, ind, dcol = tables(target)
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {dcol} FROM {ind} ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


def merged_ranges(dates: list[date], trading_dates: list[date]) -> list[tuple[date, date]]:
    """거래일 목록상 연속(인덱스 차 1)인 날짜를 한 구간으로 병합(보고용)."""
    pos = {d: i for i, d in enumerate(trading_dates)}
    out: list[tuple[date, date]] = []
    for d in sorted(set(dates)):
        if out and d in pos and out[-1][1] in pos and pos[d] == pos[out[-1][1]] + 1:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


# ---------------------------------------------------------------- 비교·패리티·적용·복원

from datetime import timedelta  # noqa: E402

from kr_pipeline.common.thresholds import C8_RS_RATING_MIN  # noqa: E402  (보고용 읽기 전용 — 판정 공식은 store 가 단일 소유)
from kr_pipeline.indicators.store import (  # noqa: E402
    update_daily_indicators_minervini_pass,
    update_daily_indicators_rs_rating,
    update_weekly_indicators_minervini_pass,
    update_weekly_indicators_rs_rating,
)

_RS_UPDATE = {Target.DAILY: update_daily_indicators_rs_rating, Target.WEEKLY: update_weekly_indicators_rs_rating}
_PASS_UPDATE = {Target.DAILY: update_daily_indicators_minervini_pass, Target.WEEKLY: update_weekly_indicators_minervini_pass}
_CHUNK = 60  # 날짜 단위 SELECT 묶음(메모리)


def _stored_chunks(conn: Connection, target: Target, dates: list[date]):
    """날짜 묶음별 {(ticker, date): (rs_rating, c8, pass)} 를 순서대로 yield(메모리 — --full 은 5.4M 행)."""
    _, ind, dcol = tables(target)
    with conn.cursor() as cur:
        for i in range(0, len(dates), _CHUNK):
            cur.execute(
                f"SELECT ticker, {dcol}, rs_rating, minervini_c8, minervini_pass FROM {ind} WHERE {dcol} = ANY(%s)",
                (dates[i:i + _CHUNK],),
            )
            yield {(t, d): (rs, c8, ps) for t, d, rs, c8, ps in cur.fetchall()}


def _stored(conn: Connection, target: Target, dates: list[date]) -> dict[tuple[str, date], tuple]:
    out: dict[tuple[str, date], tuple] = {}
    for chunk in _stored_chunks(conn, target, dates):
        out.update(chunk)
    return out


def _stored_keys(conn: Connection, target: Target, keys: list[tuple[str, date]]) -> dict[tuple[str, date], tuple]:
    """지정 셀만 읽기(적용 후 pass 변화 집계용)."""
    _, ind, dcol = tables(target)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT x.ticker, x.{dcol}, x.rs_rating, x.minervini_c8, x.minervini_pass FROM {ind} x
                 JOIN unnest(%s::varchar[], %s::date[]) AS c(t, d) ON x.ticker = c.t AND x.{dcol} = c.d""",
            ([t for t, _ in keys], [d for _, d in keys]),
        )
        return {(t, d): (rs, c8, ps) for t, d, rs, c8, ps in cur.fetchall()}


def _new(v) -> int | None:
    return None if pd.isna(v) else int(v)


def diff_cells(conn: Connection, target: Target, ranks: pd.DataFrame) -> list[dict]:
    """저장값과 다른 셀만 — {ticker, date, old, new, old_c8, old_pass}. 저장 행이 없거나 재계산 표에 없는 종목은 건너뜀."""
    if ranks.empty:
        return []
    dates = list(ranks.index)
    cols = set(ranks.columns)
    cells: list[dict] = []
    for stored in _stored_chunks(conn, target, dates):
        for (t, d), (rs, c8, ps) in stored.items():
            if t not in cols:
                continue
            new = _new(ranks.at[d, t])
            if new != rs:
                cells.append({"ticker": t, "date": d, "old": rs, "new": new, "old_c8": c8, "old_pass": ps})
    cells.sort(key=lambda c: (c["date"], c["ticker"]))
    return cells


def parity_window(conn: Connection, target: Target, sf: pd.DataFrame, *, tickers: list[str], days: int = 30) -> dict:
    """최근 `days` 캘린더일 창(야간 증분 창과 동형)의 지표 날짜에서 즉석 계산 순위 vs 저장 순위.

    mismatch 가 0 이 아니면 (a) 재적재 후 Phase B 가 아직 그 날짜를 다시 돌지 않았거나 (b) 계산 경로가 어긋난 것.
    n_by_date(N_stored, N_recomputed)·last_phase_b_at 으로 둘을 구분한다.
    """
    _, ind, dcol = tables(target)
    with conn.cursor() as cur:
        cur.execute(f"SELECT max({dcol}) FROM {ind}")
        latest = cur.fetchone()[0]
        if latest is None:   # 빈 지표 테이블(테스트 DB 초기 상태)
            return {"latest": None, "dates": 0, "mismatch": 0, "sample": [], "n_by_date": {}, "last_phase_b_at": None}
        cur.execute(f"SELECT DISTINCT {dcol} FROM {ind} WHERE {dcol} > %s ORDER BY 1", (latest - timedelta(days=days),))
        dates = [r[0] for r in cur.fetchall()]
        cur.execute(
            "SELECT max(finished_at) FROM pipeline_runs WHERE pipeline='indicators' AND mode LIKE %s AND status='success'",
            (f"{'daily' if target == Target.DAILY else 'weekly'}-%",),
        )
        last_b = cur.fetchone()[0]
    ranks = rank_table(sf, dates)
    cells = diff_cells(conn, target, ranks)
    stored = _stored(conn, target, dates)
    n_by_date = {}
    for d in dates:
        n_stored = sum(1 for (t, dd), (rs, _, _) in stored.items() if dd == d and rs is not None and t in tickers)
        n_recomp = int(ranks.loc[d].notna().sum()) if d in ranks.index else 0
        n_by_date[d.isoformat()] = [n_stored, n_recomp]
    return {
        "latest": latest.isoformat() if latest else None, "dates": len(dates), "mismatch": len(cells),
        "sample": [{**c, "date": c["date"].isoformat()} for c in cells[:10]],
        "n_by_date": n_by_date, "last_phase_b_at": last_b.isoformat() if last_b else None,
    }


def plan(conn: Connection, target: Target, dates: list[date], *, sf: pd.DataFrame, target_tickers: set[str] = frozenset()) -> dict:
    """읽기 전용 보고 + 적용 입력(cells)."""
    ranks = rank_table(sf, dates)
    cells = diff_cells(conn, target, ranks)
    hist = {"1": 0, "2": 0, ">=3": 0, "null_flip": 0}
    c8_flip = 0
    for c in cells:
        if c["old"] is None or c["new"] is None:
            hist["null_flip"] += 1
        else:
            k = abs(c["old"] - c["new"])
            hist["1" if k == 1 else "2" if k == 2 else ">=3"] += 1
        if (c["new"] is not None and c["new"] >= C8_RS_RATING_MIN) != bool(c["old_c8"]):
            c8_flip += 1
    by_t = sum(1 for c in cells if c["ticker"] in target_tickers)
    return {
        "dates": len(dates), "cells": cells, "n_cells": len(cells), "by_target_ticker": by_t, "by_other": len(cells) - by_t,
        "delta_hist": hist, "c8_flip": c8_flip,
        "date_min": dates[0].isoformat() if dates else None, "date_max": dates[-1].isoformat() if dates else None,
    }


def _keys(cells: list[dict]) -> list[tuple[str, date]]:
    return [(c["ticker"], c["date"]) for c in cells]


def apply(conn: Connection, target: Target, cells: list[dict]) -> dict:
    """한 트랜잭션: rs_rating ← new → 같은 셀만 Phase C 재유도 → commit. 예외 시 rollback 후 재raise."""
    if not cells:
        return {"cells": 0, "pass_rows": 0, "pass_changed": 0}
    keys = _keys(cells)
    d_min, d_max = min(d for _, d in keys), max(d for _, d in keys)
    try:
        _RS_UPDATE[target](conn, [(c["ticker"], c["date"], c["new"]) for c in cells])
        pass_rows = _PASS_UPDATE[target](conn, d_min, d_max, cells=keys)
        after = _stored_keys(conn, target, keys)
        pass_changed = sum(1 for c in cells if after[(c["ticker"], c["date"])][2] != c["old_pass"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"cells": len(cells), "pass_rows": pass_rows, "pass_changed": pass_changed}


def restore(conn: Connection, target: Target, cells: list[dict]) -> dict:
    """한 트랜잭션: rs_rating ← old, c8/pass ← old_c8/old_pass (정확 복원, 재유도 아님)."""
    if not cells:
        return {"cells": 0}
    _, ind, dcol = tables(target)
    try:
        _RS_UPDATE[target](conn, [(c["ticker"], c["date"], c["old"]) for c in cells])
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {ind} x
                   SET minervini_c8 = c.c8, minervini_pass = c.ps, updated_at = NOW()
                  FROM unnest(%s::varchar[], %s::date[], %s::boolean[], %s::boolean[]) AS c(t, d, c8, ps)
                 WHERE x.ticker = c.t AND x.{dcol} = c.d
                """,
                ([c["ticker"] for c in cells], [c["date"] for c in cells],
                 [c["old_c8"] for c in cells], [c["old_pass"] for c in cells]),
            )
            n = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"cells": n}


# ---------------------------------------------------------------- 러너 입력

def events_from_frozen() -> list[tuple[str, date]]:
    """#122 재적재 동결 대상(18사건/17종목) → (ticker, gap_date) 정렬 목록."""
    from kr_pipeline.ohlcv.adj_reload_events import FROZEN_TARGETS
    return sorted((t, date.fromisoformat(d)) for t, d, _ in FROZEN_TARGETS)


def stale_mirror_rows(conn: Connection, tickers: list[str]) -> dict[str, int]:
    """종목별 일봉 미러(rs_line_not_declining_7m)가 최신 주봉 값과 다른 행 수(보고용)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.ticker, count(*) FILTER (WHERE d.rs_line_not_declining_7m IS DISTINCT FROM (
                       SELECT w.rs_line_not_declining_7m FROM weekly_indicators w
                        WHERE w.ticker = d.ticker AND w.week_end_date <= d.date ORDER BY w.week_end_date DESC LIMIT 1))
              FROM daily_indicators d WHERE d.ticker = ANY(%s) GROUP BY d.ticker ORDER BY 1
            """,
            (tickers,),
        )
        return {t: int(n) for t, n in cur.fetchall()}
