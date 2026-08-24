"""#118 8차 ④ — C 버킷 'rs_gate 단독' 131건 원인 분포 (저장본 1회 분류).

분류 축: 평가 시점(분해와 동일 규칙)의 rs_gate 값 기준 —
- warmup: NULL 이고 해당일이 종목 시계열 시작 후 30주(210역일) 이내
- gap: NULL 이고 워밍업 밖(미러 결손·지수 결손 등)
- declining_false: FALSE (게이트 정상 작동 — 가용성 실패 아님, 정직 보고)
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date, timedelta

import pandas as pd
import psycopg

from kr_pipeline.backtest.p1_recall import pass_window

DB = "postgresql://localhost/kr_pipeline"
EP_CSV = "data/verification/issue115_p1_episodes_20260821.csv"

SURV_SQL = (
    "SELECT d.date, minervini_c1, minervini_c2, minervini_c3, minervini_c4, "
    "minervini_c5, minervini_c6, minervini_c7, (b.rs_rating >= 70), "
    "rs_line_not_declining_7m FROM daily_indicators d "
    "JOIN bt_rs_daily b USING (ticker, date) "
    "WHERE ticker=%s AND date = ANY(%s) ORDER BY date")
DEL_SQL = (
    "SELECT g.date, c1, c2, c3, c4, c5, c6, c7, c8, rs_gate "
    "FROM bt_delisted_indicators g WHERE g.ticker=%s AND g.date = ANY(%s) "
    "ORDER BY g.date")


def main() -> int:
    eps = pd.read_csv(EP_CSV, dtype={"ticker": str})
    eps["anchor"] = pd.to_datetime(eps.anchor).dt.date
    census = Counter()
    rows_out = []
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT date FROM index_daily WHERE index_code='1001' "
                    "ORDER BY date")
        trading = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT ticker FROM delisted_adj_quality "
                    "WHERE (flags->>'stkdp_unresolved')::bool")
        carve = {r[0] for r in cur.fetchall()}
        first_of = {}
        for tbl, cond in (("daily_prices", ""),
                          ("delisted_adj_prices", "")):
            cur.execute(f"SELECT ticker, MIN(date) FROM {tbl} GROUP BY ticker")
            for t, d in cur.fetchall():
                first_of.setdefault(t, d)
        for r in eps.itertuples():
            dl = bool(r.is_delisted)
            if dl and r.ticker in carve:
                continue
            w = pass_window(trading, r.anchor)
            cur.execute(DEL_SQL if dl else SURV_SQL, (r.ticker, w))
            rows = cur.fetchall()
            if not rows:
                continue
            if any(all(bool(x) for x in row[1:10]) for row in rows):
                continue                     # 포착 — 분해 대상 아님
            best = max(rows, key=lambda row: (
                sum(1 for x in row[1:9] if x is True), row[0]))
            fails = [k for k in range(1, 9) if best[k] is not True]
            if fails:
                continue                     # rs_gate 단독이 아님
            rg = best[9]
            if rg is True:
                continue                     # (이론상 무 — 포착으로 걸러짐)
            d0 = first_of.get(r.ticker)
            if rg is False:
                cls = "declining_false"
            elif d0 and (best[0] - d0).days <= 210:
                cls = "warmup"
            else:
                cls = "gap"
            census[cls] += 1
            rows_out.append({"ticker": r.ticker, "anchor": r.anchor.isoformat(),
                             "eval_date": best[0].isoformat(), "class": cls})
    out = {"generated": str(date.today()), "n": len(rows_out),
           "census": dict(census), "rows": rows_out}
    path = f"data/verification/issue118_rsgate131_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"n": out["n"], "census": out["census"]}, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
