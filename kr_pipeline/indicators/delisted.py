"""(#181 B3) 상폐 지표 수치 — delisted_daily_indicators(daily_indicators 동일 37컬럼).

indicators/compute 순수 함수를 라이브 `modes._process_ticker_daily` 와 **같은 순서·같은 인자**로
호출한다(복제 금지 대상은 계산식이며, 오케스트레이션은 라이브 함수가 테이블에 결합돼 있어 여기
별도 기술). 차이(사실):
- 입력 = delisted_daily_prices_adj(B1). zero-bar 행도 adj_close(체인값, PR #183 Q-1 (B))를 보유하므로
  라이브 daily_prices 와 같은 시계열 의미론(정지일 carry 포함 SMA 창). adj_high/low/volume 은 NaN.
- rs_rating·c8 = bt_rs_daily(무편향 RS, #114) — 라이브 Phase B(생존 유니버스 백분위) 대신.
- rs_line_not_declining_7m = delisted_weekly_prices(B2) adj_close 로 주봉 RS 라인 계산 후 daily 에
  asof 미러(라이브 Phase D 와 동일 규약, 주봉 지표 테이블은 만들지 않음).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from psycopg import Connection

from kr_pipeline.common.security_group import UNRESOLVED, is_gated_out
from kr_pipeline.common.thresholds import (
    C8_RS_RATING_MIN, RS_LINE_DECLINE_GATE_WEEKS, RS_LINE_UPTREND_LONG_WEEKS,
    RS_LINE_UPTREND_SHORT_WEEKS,
)
from kr_pipeline.indicators.compute.high_low import pct_from_high_low, w52_high_low
from kr_pipeline.indicators.compute.minervini import compute_minervini_c1_to_c7
from kr_pipeline.indicators.compute.rs_line import (
    compute_rs_line, compute_rs_line_52w_high_and_date, compute_rs_line_at_52w_high,
    compute_rs_line_not_declining, compute_rs_line_uptrend_slope,
)
from kr_pipeline.indicators.compute.sma import sma
from kr_pipeline.indicators.compute.volume import (
    avg_volume, distribution_day, pocket_pivot, up_down_volume_ratio, volume_dry_up, volume_ratio,
)
from kr_pipeline.indicators.load import load_index_daily, load_weekly_index
from kr_pipeline.indicators.modes import KOSPI_INDEX_CODE, _as_bool, _as_float

COLUMNS = (
    "ticker", "date", "adj_close", "sma_10", "sma_21", "sma_50", "sma_150", "sma_200",
    "w52_high", "w52_low", "pct_from_52w_high", "pct_from_52w_low",
    "rs_line", "rs_line_52w_high", "rs_line_52w_high_date", "rs_line_at_52w_high",
    "rs_line_uptrend_6w", "rs_line_uptrend_13w", "rs_line_not_declining_7m", "rs_rating",
    "minervini_c1", "minervini_c2", "minervini_c3", "minervini_c4", "minervini_c5", "minervini_c6",
    "minervini_c7", "minervini_c8", "minervini_pass",
    "volume", "avg_volume_50d", "volume_ratio_50d", "pocket_pivot_flag", "volume_dry_up_flag",
    "up_down_volume_ratio_50d", "distribution_day_flag",
)


def load_delisted_daily_for_indicators(conn: Connection, ticker: str) -> pd.DataFrame:
    """(date, adj_close, adj_high, adj_low, adj_volume) — 라이브 load_daily_prices 와 동일 컬럼."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, adj_close, adj_high, adj_low, adj_volume "
            "FROM delisted_daily_prices_adj WHERE ticker = %s ORDER BY date", (ticker,))
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["date", "adj_close", "adj_high", "adj_low", "adj_volume"])
    if df.empty:
        return df
    for c in ("adj_close", "adj_high", "adj_low", "adj_volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def compute_delisted_rows(ticker: str, df_daily: pd.DataFrame, df_idx: pd.DataFrame,
                          rs_rating: dict[date, int | None], rs_gate_weekly: pd.Series | None,
                          *, security_group: str) -> list[dict]:
    """라이브 _process_ticker_daily 의 Phase A 산술 + Phase B/C/D 를 상폐 입력으로 재현(순수).

    (Q-5) 증권구분 게이트: is_gated_out(security_group, d) 참이면 minervini_pass=None — 라이브 daily/weekly
    UPDATE 와 동일 계약(SSOT kr_pipeline/common/security_group.py). 상폐 종목은 전 행이 기준일 이전이라 무영향.
    """
    df = df_daily.merge(df_idx.rename(columns={"close": "index_close"}), on="date", how="left")
    df = df.set_index("date").sort_index()
    adj_close = df["adj_close"]
    adj_volume = df["adj_volume"]
    avg_vol_50 = avg_volume(adj_volume, window=50, min_periods=40)
    vol_ratio_50 = volume_ratio(adj_volume, avg_vol_50)
    is_up = adj_close > adj_close.shift(1)
    is_down = adj_close < adj_close.shift(1)
    sma_10, sma_21 = sma(adj_close, 10), sma(adj_close, 21)
    sma_50, sma_150, sma_200 = sma(adj_close, 50), sma(adj_close, 150), sma(adj_close, 200)
    pp_flag = pocket_pivot(is_up, adj_volume, sma_50, adj_close)
    vdu_flag = volume_dry_up(adj_volume, avg_vol_50)
    ud_ratio_50 = up_down_volume_ratio(adj_volume, is_up, is_down, window=50)
    ret_pct = adj_close.pct_change(fill_method=None) * 100.0
    dist_flag = distribution_day(ret_pct, adj_volume, avg_vol_50)
    w52h, w52l = w52_high_low(df["adj_high"], df["adj_low"], window=252, min_periods=240)
    pct_h, pct_l = pct_from_high_low(adj_close, w52h, w52l)
    rs_line = compute_rs_line(adj_close, df["index_close"])
    rs_line_high, rs_line_high_date = compute_rs_line_52w_high_and_date(rs_line, window=252)
    rs_at_high = compute_rs_line_at_52w_high(rs_line, rs_line_high)
    rs_up_6w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_SHORT_WEEKS * 5)
    rs_up_13w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_LONG_WEEKS * 5)
    mn = compute_minervini_c1_to_c7(pd.DataFrame({
        "adj_close": adj_close, "sma_50": sma_50, "sma_150": sma_150, "sma_200": sma_200,
        "w52_high": w52h, "w52_low": w52l}, index=df.index))
    # Phase D 미러: 최신 week_end_date <= date 의 주봉 게이트
    gate_map = None
    if rs_gate_weekly is not None and not rs_gate_weekly.empty:
        gm = pd.DataFrame({"week_end_date": pd.to_datetime(rs_gate_weekly.index), "g": rs_gate_weekly.values}).sort_values("week_end_date")
        dd = pd.DataFrame({"date": pd.to_datetime(df.index)})
        merged = pd.merge_asof(dd, gm, left_on="date", right_on="week_end_date", direction="backward")
        gate_map = dict(zip(df.index, merged["g"]))
    rows = []
    for d in df.index:
        if pd.isna(adj_close.loc[d]):
            continue  # adj_close 없는 행(체인 미생산) — 라이브도 adj_close NOT NULL
        cs = [_as_bool(mn[f"minervini_c{k}"].loc[d]) for k in range(1, 8)]
        rr = rs_rating.get(d)
        c8 = None if rr is None else (rr >= C8_RS_RATING_MIN)
        gated = is_gated_out(security_group, d)
        rows.append({
            "ticker": ticker, "date": d, "adj_close": float(adj_close.loc[d]),
            "sma_10": _as_float(sma_10.loc[d]), "sma_21": _as_float(sma_21.loc[d]),
            "sma_50": _as_float(sma_50.loc[d]), "sma_150": _as_float(sma_150.loc[d]), "sma_200": _as_float(sma_200.loc[d]),
            "w52_high": _as_float(w52h.loc[d]), "w52_low": _as_float(w52l.loc[d]),
            "pct_from_52w_high": _as_float(pct_h.loc[d]), "pct_from_52w_low": _as_float(pct_l.loc[d]),
            "rs_line": _as_float(rs_line.loc[d]), "rs_line_52w_high": _as_float(rs_line_high.loc[d]),
            "rs_line_52w_high_date": rs_line_high_date.loc[d] if pd.notna(rs_line_high_date.loc[d]) else None,
            "rs_line_at_52w_high": _as_bool(rs_at_high.loc[d]),
            "rs_line_uptrend_6w": _as_bool(rs_up_6w.loc[d]), "rs_line_uptrend_13w": _as_bool(rs_up_13w.loc[d]),
            "rs_line_not_declining_7m": (_as_bool(gate_map[d]) if gate_map is not None else None),
            "rs_rating": rr,
            **{f"minervini_c{k}": cs[k - 1] for k in range(1, 8)},
            "minervini_c8": c8,
            "minervini_pass": None if gated else ((all(x is True for x in cs) and c8 is True) if c8 is not None else None),
            "volume": _as_float(adj_volume.loc[d]), "avg_volume_50d": _as_float(avg_vol_50.loc[d]),
            "volume_ratio_50d": _as_float(vol_ratio_50.loc[d]), "pocket_pivot_flag": _as_bool(pp_flag.loc[d]),
            "volume_dry_up_flag": _as_bool(vdu_flag.loc[d]), "up_down_volume_ratio_50d": _as_float(ud_ratio_50.loc[d]),
            "distribution_day_flag": _as_bool(dist_flag.loc[d]),
        })
    return rows


def _weekly_rs_gate(conn: Connection, ticker: str) -> pd.Series | None:
    with conn.cursor() as cur:
        cur.execute("SELECT week_end_date, adj_close FROM delisted_weekly_prices WHERE ticker = %s ORDER BY 1", (ticker,))
        wk = cur.fetchall()
    if not wk:
        return None
    w = pd.DataFrame(wk, columns=["date", "adj_close"])
    w["adj_close"] = pd.to_numeric(w["adj_close"], errors="coerce")
    idx = load_weekly_index(conn, KOSPI_INDEX_CODE, w["date"].min(), w["date"].max())
    m = w.merge(idx.rename(columns={"close": "index_close"}), on="date", how="left").set_index("date").sort_index()
    rs = compute_rs_line(m["adj_close"], m["index_close"])
    return compute_rs_line_not_declining(rs, window=RS_LINE_DECLINE_GATE_WEEKS)


def build_delisted_indicators(conn: Connection, tickers: list[str] | None = None) -> dict:
    """종목 단위 DELETE→COPY(멱등). 반환 {tickers, rows, no_rs}."""
    stats = {"tickers": 0, "rows": 0, "no_rs": 0}
    with conn.cursor() as cur:
        if tickers is None:
            cur.execute("SELECT DISTINCT ticker FROM delisted_daily_prices ORDER BY 1")
            tickers = [r[0] for r in cur.fetchall()]
        for t in tickers:
            df = load_delisted_daily_for_indicators(conn, t)
            if df.empty:
                continue
            df_idx = load_index_daily(conn, KOSPI_INDEX_CODE, df["date"].min(), df["date"].max())
            cur.execute("SELECT date, rs_rating FROM bt_rs_daily WHERE ticker = %s", (t,))
            rs = {d: (int(r) if r is not None else None) for d, r in cur.fetchall()}
            if not rs:
                stats["no_rs"] += 1
            cur.execute("SELECT security_group FROM stocks WHERE ticker = %s", (t,))
            sg_row = cur.fetchone()
            rows = compute_delisted_rows(t, df, df_idx, rs, _weekly_rs_gate(conn, t),
                                         security_group=sg_row[0] if sg_row else UNRESOLVED)
            cur.execute("DELETE FROM delisted_daily_indicators WHERE ticker = %s", (t,))
            with cur.copy(f"COPY delisted_daily_indicators ({', '.join(COLUMNS)}) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row(tuple(r[c] for c in COLUMNS))
            stats["rows"] += len(rows)
            stats["tickers"] += 1
            conn.commit()
    return stats
