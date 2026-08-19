"""#114 §4.5 — 재구성 오차 분포 리포트 (KRX 접촉 0, DB 로컬 전용).

검증 범위(사전등록 scope): 이벤트 보유 1,293 + 무이벤트 표본 150.
각 종목: share_counts 로 재구성 → daily_prices.adj_close(pykrx) 대비
상대오차 분포 + 참조 이벤트 매칭(±3일) + 무이벤트 표본 위양성 계수.
"""
from __future__ import annotations

import json
import sys
from datetime import date

import psycopg

from kr_pipeline.ohlcv.adj_reconstruct import (
    db_factor_jumps, error_stats, factor_curve, match_events, reconstruct,
    share_events, v2_events, v3_events,
)

DB = "postgresql://localhost/kr_pipeline"
SCOPE = "data/verification/issue114_survivor_scope.json"
V2 = "--v2" in sys.argv
V3 = "--v3" in sys.argv


def load_ticker(cur, ticker: str):
    cur.execute("SELECT date, close, adj_close FROM daily_prices "
                "WHERE ticker = %s AND close > 0 AND adj_close > 0 "
                "ORDER BY date", (ticker,))
    rows = cur.fetchall()
    closes = [(d, float(c)) for d, c, _ in rows]
    adj = {d: float(a) for d, _, a in rows}
    cur.execute("SELECT date, shares FROM share_counts WHERE ticker = %s "
                "ORDER BY date", (ticker,))
    shares = {d: int(s) for d, s in cur.fetchall()}
    cur.execute("SELECT DISTINCT event_date FROM corporate_actions "
                "WHERE ticker = %s AND event_type IN "
                "('bonus_issue','rights_offering','capital_reduction')", (ticker,))
    discl = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT endpoint, record_date, ratio::float, method "
                "FROM corp_action_details WHERE ticker = %s", (ticker,))
    details = [{"endpoint": e, "record_date": rd, "ratio": rt, "method": m}
               for e, rd, rt, m in cur.fetchall()]
    return closes, adj, shares, discl, details


def main() -> int:
    scope = json.load(open(SCOPE))
    groups = {"event": scope["event_tickers"], "noevent": scope["noevent_sample"]}
    out = {"issue": 114, "part": "§4.5 오차 분포 " + ("v3" if V3 else "v2" if V2 else "v1"), "generated": str(date.today()),
           "method": "share_events(|Δ|>0.5%) → factor_curve → 최신일 앵커 정규화",
           "groups": {}}

    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for gname, tickers in groups.items():
            per, worst = [], []
            fp_tickers = []
            agg_match = {"db_jumps": 0, "matched": 0, "missed_big": 0,
                         "missed_small": 0}
            for t in tickers:
                closes, adj, shares, discl, details = load_ticker(cur, t)
                if not closes or not shares:
                    continue
                if V3:
                    ev = v3_events(closes, shares, details)
                    dates = [d for d, _ in closes]
                    f = factor_curve(dates, ev)
                    recon = {d: c * f[d] for d, c in closes}
                elif V2:
                    ev = v2_events(closes, shares, discl)
                    dates = [d for d, _ in closes]
                    f = factor_curve(dates, ev)
                    recon = {d: c * f[d] for d, c in closes}
                else:
                    recon = reconstruct(closes, shares)
                    ev = share_events(sorted(shares), shares)
                st = error_stats(recon, adj)
                if st.get("n", 0) == 0:
                    continue
                if gname == "noevent" and ev:
                    fp_tickers.append({"ticker": t, "n_events": len(ev),
                                       "ratios": [round(r, 4) for _, r in ev][:5]})
                m = match_events(db_factor_jumps(closes, adj), ev)
                for k in agg_match:
                    agg_match[k] += m[k]
                per.append({"ticker": t, **st, **m})
                worst.append((st["p99"], t))
            worst.sort(reverse=True)
            n = len(per)
            pooled_p99 = sorted(p["p99"] for p in per)
            g = {"n_tickers": n, "match": agg_match,
                 "ticker_p99_median": round(pooled_p99[n // 2], 6) if n else None,
                 "ticker_p99_p90": round(pooled_p99[int(n * 0.9)], 6) if n else None,
                 "share_of_tickers_p99_le_1pct":
                     round(sum(1 for p in pooled_p99 if p <= 0.01) / n, 4) if n else None,
                 "worst10": [{"ticker": t, "p99": p} for p, t in worst[:10]]}
            if gname == "noevent":
                g["false_positive_tickers"] = fp_tickers
                g["fp_count"] = len(fp_tickers)
            out["groups"][gname] = g

    path = f"data/verification/issue114_adj_error_report_{"v3_" if V3 else "v2_" if V2 else ""}{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "worst10"
                          and kk != "false_positive_tickers"}
                      for k, v in out["groups"].items()}, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
