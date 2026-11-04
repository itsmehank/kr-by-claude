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
