"""#118 사이클 1 — 상폐 435종목 게이트 지표 산출 (설계 v1 §1~2, 로컬 DB 전용).

현행 순수 함수 재사용(복제 금지): sma·w52_high_low·compute_minervini_c1_to_c7·
aggregate_to_weekly·compute_rs_line(_not_declining). adj_high/low = raw ×
(adj_close/raw_close) 동일 계수 유도(production 동형). c8 = bt_rs_daily ≥ 70.
"""
from __future__ import annotations

import json
import sys
from datetime import date

import pandas as pd
import psycopg

from kr_pipeline.common.thresholds import (
    C8_RS_RATING_MIN, RS_LINE_DECLINE_GATE_WEEKS,
)
from kr_pipeline.indicators.compute.high_low import w52_high_low
from kr_pipeline.indicators.compute.minervini import compute_minervini_c1_to_c7
from kr_pipeline.indicators.compute.rs_line import (
    compute_rs_line, compute_rs_line_not_declining,
)
from kr_pipeline.indicators.compute.sma import sma
from kr_pipeline.weekly.transform import aggregate_to_weekly

DB = "postgresql://localhost/kr_pipeline"


def _b(v):
    return None if pd.isna(v) else bool(v)


def main() -> int:
    out = {"generated": str(date.today()), "tickers": 0, "rows": 0,
           "carve_no_c8": [], "rs_nan_only": 0}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT date, close FROM index_daily WHERE index_code='1001' "
                    "ORDER BY date")
        idx_daily = pd.DataFrame(cur.fetchall(), columns=["date", "close"])
        idx_daily["close"] = idx_daily["close"].astype(float)
        c = idx_daily["close"]
        idxw = aggregate_to_weekly(pd.DataFrame({
            "date": idx_daily["date"], "open": c, "high": c, "low": c,
            "close": c, "adj_close": c, "adj_high": c, "adj_low": c,
            "adj_open": c, "adj_volume": 0, "volume": 0, "value": 0,
        }))
        idxw_close = idxw.set_index("week_end_date")["adj_close"]

        cur.execute("SELECT DISTINCT ticker FROM delisted_adj_prices ORDER BY 1")
        tickers = [r[0] for r in cur.fetchall()]
        cur.execute("DELETE FROM bt_delisted_indicators")
        for t in tickers:
            cur.execute(
                "SELECT p.date, p.adj_close, r.high, r.low, r.close "
                "FROM delisted_adj_prices p JOIN delisted_daily_prices r "
                "ON r.ticker = p.ticker AND r.date = p.date "
                "WHERE p.ticker = %s AND r.close > 0 ORDER BY p.date", (t,))
            rows = cur.fetchall()
            if not rows:
                continue
            df = pd.DataFrame(rows, columns=["date", "adj_close", "high",
                                             "low", "close"])
            for c in ("adj_close", "high", "low", "close"):
                df[c] = df[c].astype(float)
            factor = df["adj_close"] / df["close"]          # 동일 계수 유도
            adj_high = df["high"].where(df["high"] > 0, df["close"]) * factor
            adj_low = df["low"].where(df["low"] > 0, df["close"]) * factor
            ac = df["adj_close"]
            mn = compute_minervini_c1_to_c7(pd.DataFrame({
                "adj_close": ac,
                "sma_50": sma(ac, 50), "sma_150": sma(ac, 150),
                "sma_200": sma(ac, 200),
                **dict(zip(["w52_high", "w52_low"],
                           w52_high_low(adj_high, adj_low, window=252,
                                        min_periods=240))),
            }))
            wk = aggregate_to_weekly(pd.DataFrame({
                "date": df["date"], "open": df["close"], "high": df["high"],
                "low": df["low"], "close": df["close"], "adj_close": ac,
                "adj_high": adj_high, "adj_low": adj_low, "adj_open": ac,
                "adj_volume": 0, "volume": 0, "value": 0,
            }))
            widx = idxw_close.reindex(wk["week_end_date"]).reset_index(drop=True)
            rs_w = compute_rs_line(wk["adj_close"], widx)
            gate_w = compute_rs_line_not_declining(
                rs_w, window=RS_LINE_DECLINE_GATE_WEEKS)
            wmap = pd.DataFrame({
                "week_end_date": pd.to_datetime(wk["week_end_date"]),
                "rs_gate": gate_w}).sort_values("week_end_date")
            daily = pd.DataFrame({"date": pd.to_datetime(df["date"])})
            merged = pd.merge_asof(daily, wmap, left_on="date",
                                   right_on="week_end_date", direction="backward")
            cur.execute("SELECT date, rs_rating FROM bt_rs_daily "
                        "WHERE ticker = %s", (t,))
            c8_of = {d: (r is not None and r >= C8_RS_RATING_MIN)
                     for d, r in cur.fetchall()}
            if not c8_of:
                out["carve_no_c8"].append(t)
            with cur.copy(
                    "COPY bt_delisted_indicators (ticker, date, c1, c2, c3, c4, "
                    "c5, c6, c7, rs_gate, c8, gate_pass) FROM STDIN") as cp:
                for i, d in enumerate(df["date"]):
                    cs = [_b(mn[f"minervini_c{k}"].iloc[i]) for k in range(1, 8)]
                    rg = _b(merged["rs_gate"].iloc[i])
                    c8 = c8_of.get(d)
                    gate = (all(x is True for x in cs) and rg is True
                            and c8 is True)
                    cp.write_row((t, d, *cs, rg, c8, gate))
                    out["rows"] += 1
            conn.commit()
            out["tickers"] += 1
    path = f"data/verification/issue118_delisted_gate_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({**out, "carve_no_c8": len(out["carve_no_c8"])},
                     ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
