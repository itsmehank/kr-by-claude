"""#114 P0 — 상폐 435종목 수정주가 생산 러너 (로컬 DB 전용, 외부 호출 0).

delisted_daily_prices(raw) + share_counts + corp_action_details → 동결 v5 체인
(produce_delisted_adj) → delisted_adj_prices/delisted_adj_quality 적재.
종목 단위 트랜잭션(DELETE→INSERT — 재실행 멱등). stkdp_unresolved 층화는
상폐 stkdp 백필 원장(doc_unavailable·parse_fail)에서 유래.
"""
from __future__ import annotations

import glob
import json
import math
import sys
from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from kr_pipeline.ohlcv.delisted_adj import CHAIN_VERSION, produce_delisted_adj

DB = "postgresql://localhost/kr_pipeline"


def load_stkdp_unresolved() -> set[str]:
    paths = sorted(glob.glob(
        "data/verification/issue114_stkdp_backfill_delisted_*.json"))
    if not paths:
        raise SystemExit("상폐 stkdp 백필 원장 없음 — 백필 선행 필요")
    stats = json.load(open(paths[-1]))
    return {r["ticker"] for r in stats.get("doc_unavailable", [])} | \
           {r["ticker"] for r in stats.get("parse_fail", [])}


def main() -> int:
    unresolved = load_stkdp_unresolved()
    out = {"generated": str(date.today()), "chain_version": CHAIN_VERSION,
           "tickers": 0, "produced": 0, "empty": [], "rows": 0,
           "flags_census": {}, "provenance_census": {},
           "suppressed_total": 0, "upward_suppressed": [],
           "extreme_factors": []}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM delisted_daily_prices ORDER BY 1")
        tickers = [r[0] for r in cur.fetchall()]
        out["tickers"] = len(tickers)
        for t in tickers:
            cur.execute("SELECT date, close FROM delisted_daily_prices "
                        "WHERE ticker=%s ORDER BY date", (t,))
            closes = [(d, float(c)) for d, c in cur.fetchall()]
            cur.execute("SELECT date, shares FROM share_counts WHERE ticker=%s "
                        "ORDER BY date", (t,))
            shares = {d: int(s) for d, s in cur.fetchall()}
            cur.execute("SELECT endpoint, record_date, ratio::float, method, "
                        "rcept_no FROM corp_action_details WHERE ticker=%s", (t,))
            details = [{"endpoint": e, "record_date": rd, "ratio": rt,
                        "method": m, "rcept_no": rc}
                       for e, rd, rt, m, rc in cur.fetchall()]
            r = produce_delisted_adj(closes, shares, details,
                                     stkdp_unresolved=(t in unresolved))
            adj = r.adj
            if not adj:
                out["empty"].append(t)
                continue
            cur.execute("DELETE FROM delisted_adj_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM delisted_adj_quality WHERE ticker=%s", (t,))
            with cur.copy("COPY delisted_adj_prices (ticker, date, adj_close, "
                          "liq_window) FROM STDIN") as cp:
                for d, a in sorted(adj.items()):
                    cp.write_row((t, d, round(a, 4), d in r.liq_window))
            cur.execute(
                "INSERT INTO delisted_adj_quality (ticker, chain_version, "
                "n_days, n_events, provenance, flags, suppressed) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (t, CHAIN_VERSION, len(adj), len(r.events), Jsonb(r.provenance),
                 Jsonb(r.flags),
                 Jsonb([{"date": d.isoformat(), "ratio": round(rt, 4)}
                        for d, rt, _ in r.suppressed])))
            conn.commit()
            out["produced"] += 1
            out["rows"] += len(adj)
            for k, v in r.flags.items():
                if v:
                    out["flags_census"][k] = out["flags_census"].get(k, 0) + 1
            for k, v in r.provenance.items():
                out["provenance_census"][k] = out["provenance_census"].get(k, 0) + v
            out["suppressed_total"] += len(r.suppressed)
            for d, rt, _ in r.suppressed:
                if rt > 1.35:
                    out["upward_suppressed"].append(
                        {"ticker": t, "date": d.isoformat(), "ratio": round(rt, 3)})
            factors = [adj[d] / c for d, c in closes if c > 0 and d in adj]
            fmax, fmin = max(factors), min(factors)
            if fmax > 1000 or fmin < 1e-3:
                out["extreme_factors"].append(
                    {"ticker": t, "max_factor": round(fmax, 4),
                     "min_factor": round(fmin, 6)})
    out["coverage"] = round(out["produced"] / out["tickers"], 4) if out["tickers"] else 0
    path = f"data/verification/issue114_delisted_adj_produce_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("empty", "extreme_factors",
                                   "upward_suppressed")},
                     ensure_ascii=False))
    print("empty:", len(out["empty"]), "extreme:", len(out["extreme_factors"]),
          "upward_suppressed:", len(out["upward_suppressed"]))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
