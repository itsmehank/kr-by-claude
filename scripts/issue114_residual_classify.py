"""#114 잔여 건 전수 분류 (6차 ③·5차 ② 이행) — 대형 175 + FP 30. 읽기전용 진단.

동결 v4.1 파이프라인은 무수정(재검증 발동 없음) — 본 스크립트는 진단 전용으로
이벤트를 재현·태깅한다.

대형 클래스: merger_spinoff(복합—층화) / rights_no_doc(2015~19 원문 미제공—층화
확정) / ratio_mismatch(날짜 일치·크기 불일치 — 근사 한계) / no_signal(주변 증거
전무 — 데이터 결함 후보) / other.
FP 클래스(출처): gap_fallback(재개 급변을 조정으로 오인) / detail_fric / detail_piic
/ share_matched — 5차 ② 심판(DART) 대상 표기.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date

import psycopg

from kr_pipeline.ohlcv.adj_reconstruct import (
    db_factor_jumps, share_events, v3_events,
)

DB = "postgresql://localhost/kr_pipeline"
SCOPE = "data/verification/issue114_survivor_scope.json"
SIZE_TOL = 1.15


def load(cur, t):
    cur.execute("SELECT date, close, adj_close FROM daily_prices WHERE ticker=%s "
                "AND close>0 AND adj_close>0 ORDER BY date", (t,))
    rows = cur.fetchall()
    closes = [(d, float(c)) for d, c, _ in rows]
    adj = {d: float(a) for d, _, a in rows}
    cur.execute("SELECT date, shares FROM share_counts WHERE ticker=%s ORDER BY date", (t,))
    shares = {d: int(s) for d, s in cur.fetchall()}
    cur.execute("SELECT endpoint, record_date, ratio::float, method, rcept_no "
                "FROM corp_action_details WHERE ticker=%s", (t,))
    details = [{"endpoint": e, "record_date": rd, "ratio": rt, "method": m,
                "rcept_no": rc} for e, rd, rt, m, rc in cur.fetchall()]
    cur.execute("SELECT event_type, event_date FROM corporate_actions WHERE ticker=%s", (t,))
    actions = cur.fetchall()
    return closes, adj, shares, details, actions


def classify_missed(t, d, r, closes, shares, details, actions, events):
    near_ev = [(ed, er) for ed, er in events if abs((ed - d).days) <= 3]
    if near_ev:
        return "ratio_mismatch"
    if any(et in ("merger", "spinoff") and abs((ad - d).days) <= 90
           for et, ad in actions):
        return "merger_spinoff"
    if any(x["endpoint"] == "piicDecsn" and (x["method"] or "").find("주주") >= 0
           and x["record_date"] is None and x["rcept_no"][:4] <= "2019"
           for x in details):
        return "rights_no_doc"
    se = share_events(sorted(shares), shares)
    has_signal = (any(abs((sd - d).days) <= 45 for sd, _ in se)
                  or any(x["record_date"] and abs((x["record_date"] - d).days) <= 90
                         for x in details)
                  or any(abs((ad - d).days) <= 60 for _, ad in actions))
    return "other" if has_signal else "no_signal"


def fp_provenance(ed, er, closes, shares, details):
    close_of = dict(closes)
    dates = [x for x, _ in closes]
    i = dates.index(ed) if ed in close_of else -1
    if i > 0:
        g = close_of[ed] / close_of[dates[i - 1]]
        if abs(math.log(g)) > math.log(1.35):
            se = share_events(sorted(shares), shares)
            if any(abs((sd - ed).days) <= 45
                   and abs(math.log(sr) - math.log(g)) < math.log(1.4)
                   for sd, sr in se if sr > 0):
                return "share_matched_gap"
            return "gap_fallback"
    for x in details:
        if x["record_date"] is None:
            continue
        if abs((x["record_date"] - ed).days) <= 5:
            return f"detail_{'fric' if x['endpoint'] != 'piicDecsn' else 'piic'}"
    return "unknown"


def main() -> int:
    scope = json.load(open(SCOPE))
    missed_rows, fp_rows = [], []
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for t in scope["event_tickers"]:
            closes, adj, shares, details, actions = load(cur, t)
            if not closes:
                continue
            events = v3_events(closes, shares, details)
            for d, r in db_factor_jumps(closes, adj):
                if abs(r - 1) <= 0.30:
                    continue
                hit = any(abs((d - ed).days) <= 3 and er > 0 and r > 0
                          and abs(math.log(er) - math.log(r)) <= math.log(SIZE_TOL)
                          for ed, er in events)
                if not hit:
                    missed_rows.append(
                        {"ticker": t, "date": d.isoformat(), "ratio": round(r, 3),
                         "class": classify_missed(t, d, r, closes, shares,
                                                  details, actions, events)})
        for t in scope["noevent_sample"]:
            closes, adj, shares, details, actions = load(cur, t)
            if not closes:
                continue
            events = v3_events(closes, shares, details)
            for ed, er in events:
                fp_rows.append({"ticker": t, "date": ed.isoformat(),
                                "ratio": round(er, 3),
                                "provenance": fp_provenance(ed, er, closes,
                                                            shares, details)})

    from collections import Counter
    out = {"generated": str(date.today()),
           "missed_big": {"n": len(missed_rows),
                          "by_class": dict(Counter(x["class"] for x in missed_rows)),
                          "rows": missed_rows},
           "fp": {"n_tickers": len({x['ticker'] for x in fp_rows}),
                  "n_events": len(fp_rows),
                  "by_provenance": dict(Counter(x["provenance"] for x in fp_rows)),
                  "rows": fp_rows}}
    path = f"data/verification/issue114_residual_classify_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"missed_by_class": out["missed_big"]["by_class"],
                      "fp_by_provenance": out["fp"]["by_provenance"],
                      "missed_n": len(missed_rows), "fp_events": len(fp_rows)},
                     ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
