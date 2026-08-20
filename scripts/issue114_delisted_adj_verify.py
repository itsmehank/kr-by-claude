"""#114 12차 ③ — 레거시 상폐 대조 검증 (사전등록 프로토콜, 로컬 DB 전용).

참조를 보유한 유일한 상폐 표본(레거시 = daily_prices 에 adj 가 남아 있는 상폐
종목)을 v5-d 체인으로 재구성해 대조. 프로토콜(수집 전 봉인 — plan 12차 ③):
① 오차 분포(ticker-day 분위수) ② 이벤트 매칭(±3일·크기 log1.15)
③ 정리매매 구간(마지막 14일) 별도 보고 — 참조가 폭락을 보존하면 v5-d(갭 보존)
오차가 0 에 수렴해야 함 = 12차 ① (a) 결정의 직접 검증.
시대 한정: 현대 서식 앵커 — 2015~19 구형 서식 구간은 본 대조로 미검증.
"""
from __future__ import annotations

import json
import sys
from datetime import date

import psycopg

from kr_pipeline.ohlcv.adj_reconstruct import (
    db_factor_jumps, error_stats, match_events,
)
from kr_pipeline.ohlcv.delisted_adj import LIQ_WINDOW_DAYS, produce_delisted_adj

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
            r = produce_delisted_adj(closes, shares, details)
            st = error_stats(r.adj, ref)
            m = match_events(db_factor_jumps(closes, ref),
                             [(d, rt) for d, rt, _ in r.events], size_tol=1.15)
            # ③ 정리매매 구간(마지막 14일) 별도 — (a) 직접 검증
            last = max(r.adj)
            liq = sorted(d for d in r.adj
                         if (last - d).days <= LIQ_WINDOW_DAYS and d in ref)
            liq_err = None
            if liq:
                scale = ref[last] / r.adj[last]
                liq_err = round(max(abs(r.adj[d] * scale / ref[d] - 1)
                                    for d in liq), 6)
            out["tickers"].append({"ticker": t, "n_events": len(r.events),
                                   "provenance": r.provenance, "flags": r.flags,
                                   "n_suppressed": len(r.suppressed),
                                   "match": m, "liq_window_max_err": liq_err,
                                   **st})
    ok = [x for x in out["tickers"] if "p99" in x]
    out["summary"] = {
        "n_legacy": len(out["tickers"]), "n_compared": len(ok),
        "p99_le_1pct": sum(1 for x in ok if x["p99"] <= 0.01),
        "p99_values": sorted(round(x["p99"], 5) for x in ok),
        "missed_big_total": sum(x["match"]["missed_big"] for x in ok),
        "liq_window_max_err": max((x["liq_window_max_err"] for x in ok
                                   if x["liq_window_max_err"] is not None),
                                  default=None),
    }
    path = f"data/verification/issue114_delisted_adj_verify_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out["summary"], ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
