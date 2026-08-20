"""#114 P0 — 레거시 상폐 대조 검증 (로컬 DB 전용).

참조를 보유한 유일한 상폐 표본 = 과거부터 daily_prices 에 남아 있는 레거시 상폐
종목(adj_close 존재). 동일 v5 체인으로 재구성해 참조 대비 오차 분포를 보고 —
참조 부재 435종목 생산 품질의 간접 앵커(검증 범위 분포와 비교).
"""
from __future__ import annotations

import json
import sys
from datetime import date

import psycopg

from kr_pipeline.ohlcv.adj_reconstruct import error_stats
from kr_pipeline.ohlcv.delisted_adj import produce_delisted_adj

DB = "postgresql://localhost/kr_pipeline"


def main() -> int:
    out = {"generated": str(date.today()), "tickers": []}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT s.ticker FROM stocks s "
            "JOIN daily_prices p ON p.ticker = s.ticker "
            "WHERE s.delisted_at IS NOT NULL ORDER BY 1")
        legacy = [r[0] for r in cur.fetchall()]
        for t in legacy:
            cur.execute("SELECT date, close, adj_close FROM daily_prices "
                        "WHERE ticker=%s AND close>0 AND adj_close>0 "
                        "ORDER BY date", (t,))
            rows = cur.fetchall()
            closes = [(d, float(c)) for d, c, _ in rows]
            ref = {d: float(a) for d, _, a in rows}
            cur.execute("SELECT date, shares FROM share_counts WHERE ticker=%s "
                        "ORDER BY date", (t,))
            shares = {d: int(s) for d, s in cur.fetchall()}
            cur.execute("SELECT endpoint, record_date, ratio::float, method, "
                        "rcept_no FROM corp_action_details WHERE ticker=%s", (t,))
            details = [{"endpoint": e, "record_date": rd, "ratio": rt,
                        "method": m, "rcept_no": rc}
                       for e, rd, rt, m, rc in cur.fetchall()]
            if not closes or not shares:
                out["tickers"].append({"ticker": t, "skip": "no closes/shares"})
                continue
            adj, ev, provenance, flags = produce_delisted_adj(closes, shares, details)
            st = error_stats(adj, ref)
            out["tickers"].append({"ticker": t, "n_events": len(ev),
                                   "provenance": provenance, "flags": flags,
                                   **st})
    ok = [x for x in out["tickers"] if "p99" in x]
    out["summary"] = {
        "n_legacy": len(out["tickers"]), "n_compared": len(ok),
        "p99_le_1pct": sum(1 for x in ok if x["p99"] <= 0.01),
        "p99_values": sorted(round(x["p99"], 5) for x in ok),
    }
    path = f"data/verification/issue114_delisted_adj_verify_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out["summary"], ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
