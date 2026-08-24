"""#118 12차 — 차단 트리거 프록시 이웃 격자 강건성 [descriptive].

봉인 완결 조건: 신고가 {40, 60(본), 90}일 × 거래량 {1.25, 1.5(본), 2.0}× 중
이웃 격자 4셀(40/90 × 1.25/2.0)의 순효과 부호가 본 측정(+1.821)과 동일하게
양(+)으로 유지되는지. 회피손실(이탈군)은 프록시와 무관해 공통 — 지연비용만
셀별 재산출. 그 외 정의 전부 4변수 러너와 동일(11차 봉인 자구).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd
import psycopg

from kr_pipeline.backtest.minervini_forward import (
    extract_transitions, forward_excess,
)
from kr_pipeline.common.thresholds import (
    TT_MARGIN_MARGINAL_PCT, TT_MARGINAL_DEMOTION_COUNT,
)

sys.path.insert(0, "scripts")
from issue118_marginal_4vars import margins_frame  # noqa: E402 — 동일 정의 재사용

DB = "postgresql://localhost/kr_pipeline"
WIN = (date(2017, 1, 1), date(2024, 12, 31))
RESOLVE_ROWS = 63
IDX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}
GRID = [(40, 1.25), (40, 2.0), (90, 1.25), (90, 2.0), (60, 1.5)]  # 마지막=본 재현


def main() -> int:
    delay_vals = defaultdict(list)          # (hi,vol) -> [delay_cost]
    avoided = []
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT index_code, date, close FROM index_daily")
        idx = defaultdict(dict)
        for code, d, cl in cur.fetchall():
            idx[code][d] = float(cl)
        cur.execute("SELECT ticker, market FROM stocks WHERE delisted_at IS NULL")
        mkt_of = dict(cur.fetchall())
        cur.execute("SELECT DISTINCT ticker FROM daily_indicators ORDER BY 1")
        tickers = [r[0] for r in cur.fetchall()]
        for t in tickers:
            cur.execute(
                "SELECT d.date, d.adj_close, d.sma_50, d.sma_150, d.sma_200, "
                "d.w52_high, d.w52_low, d.rs_rating, d.minervini_pass, "
                "d.minervini_c1, d.minervini_c2, d.minervini_c3, d.minervini_c4, "
                "d.minervini_c5, d.minervini_c6, d.minervini_c7, d.minervini_c8, "
                "p.volume FROM daily_indicators d "
                "JOIN daily_prices p USING (ticker, date) "
                "WHERE d.ticker=%s ORDER BY d.date", (t,))
            raw = cur.fetchall()
            if len(raw) < 30:
                continue
            df = pd.DataFrame(raw, columns=[
                "date", "adj_close", "sma_50", "sma_150", "sma_200", "w52_high",
                "w52_low", "rs_rating", "mp", "c1", "c2", "c3", "c4", "c5",
                "c6", "c7", "c8", "volume"])
            for col in ("adj_close", "sma_50", "sma_150", "sma_200", "w52_high",
                        "w52_low", "volume", "rs_rating"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            mg = margins_frame(df).astype(float)
            cmat = df[[f"c{k}" for k in range(1, 9)]].to_numpy()
            mmat = mg.to_numpy()
            passed = cmat == True                                   # noqa: E712
            marg = passed & (mmat < TT_MARGIN_MARGINAL_PCT)
            bad = passed & ~np.isfinite(mmat)
            mc = np.where(bad.any(axis=1), -1, marg.sum(axis=1))
            allpass = passed.all(axis=1)
            vol = df.volume
            avg50 = vol.rolling(50, min_periods=50).mean()
            brk = {}
            for hi_d, vmul in GRID:
                hi = df.adj_close.rolling(hi_d, min_periods=hi_d).max().shift(1)
                brk[(hi_d, vmul)] = ((df.adj_close > hi) &
                                     (vol >= vmul * avg50)).to_numpy()
            rows = [(r.date, float(r.adj_close), bool(r.mp) if r.mp is not None
                     else None, None) for r in df.itertuples()]
            iclose = idx[IDX_CODE.get(mkt_of.get(t) or "KOSPI", "1001")]
            for i in extract_transitions(rows):
                d0 = rows[i][0]
                if not (WIN[0] <= d0 <= WIN[1]) or mc[i] < 0:
                    continue
                if mc[i] < TT_MARGINAL_DEMOTION_COUNT:
                    continue
                j0 = None
                for j in range(i + 1, min(i + 1 + RESOLVE_ROWS, len(rows))):
                    if allpass[j] and 0 <= mc[j] < TT_MARGINAL_DEMOTION_COUNT:
                        j0 = j
                        break
                if j0 is None:
                    x20 = forward_excess(rows, i, 20, iclose)
                    if x20 is not None:
                        avoided.append(-x20)
                    continue
                for cell, b in brk.items():
                    blocked = [j for j in range(i + 1, j0 + 1) if b[j]]
                    dc = (forward_excess(rows, blocked[0] - 1, 20, iclose)
                          if blocked else 0.0)
                    if dc is not None:
                        delay_vals[cell].append(dc)

    avoid_mean = float(np.mean(avoided))
    out = {"generated": str(date.today()),
           "grade": "descriptive — 프록시 봉인 완결 조건(12차)",
           "avoided_loss_mean": round(avoid_mean, 3),
           "cells": {}, "all_cells_positive": True}
    for cell, vals in sorted(delay_vals.items()):
        dm = float(np.mean(vals))
        net = avoid_mean - dm
        out["cells"][f"hi{cell[0]}_vol{cell[1]}"] = {
            "n": len(vals), "delay_cost_mean": round(dm, 3),
            "net_effect": round(net, 3)}
        if net <= 0 and cell != (60, 1.5):
            out["all_cells_positive"] = False
    path = f"data/backtest/issue118_marginal_grid_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
