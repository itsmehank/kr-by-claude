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
