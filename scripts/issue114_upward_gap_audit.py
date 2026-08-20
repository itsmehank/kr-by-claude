"""#114 12차 조건 1 — 상방 억제 갭 표적 감사.

v5-d 가 보존한 상방 대형 갭(r>1.35) 전수 × 조정성 공시 대조 — 진짜 조정
(감자·병합·분할류)이 미부여로 남았는지 판별. 증거 우선순위:
1) 로컬: crDecsn detail 기준일 ±14일 / merger·spinoff 공시 ±90일 /
   주식수 이벤트 ±45일 크기 정합(log 1.4 — 왜 gap_share 가 안 됐는지 사유 기록)
2) DART list(±90/+30일, pblntf_ty='B') report_nm 감자·합병·분할·병합 검색
분류: cr_detail_match / share_late_match / dart_disclosure_found / no_evidence.
처분: 공시 실재 건은 quality flags 에 upward_gap_disclosed 표시(편입 후보 보고).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import date, timedelta

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from kr_pipeline.corporate_actions.dart_client import fetch_disclosures
from kr_pipeline.ohlcv.adj_reconstruct import share_events

DB = "postgresql://localhost/kr_pipeline"
KEYWORDS = ("감자", "합병", "분할", "병합")


def main() -> int:
    load_dotenv()
    key = os.environ["DART_API_KEY"]
    prod = json.load(open(sorted(__import__("glob").glob(
        "data/verification/issue114_delisted_adj_produce_*.json"))[-1]))
    gaps = prod["upward_suppressed"]
    print(f"upward suppressed gaps: {len(gaps)}")
    rows = []
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT stock_code, corp_code FROM dart_corp_codes")
        codes = dict(cur.fetchall())
        for g in gaps:
            t, d, r = g["ticker"], date.fromisoformat(g["date"]), g["ratio"]
            cur.execute("SELECT record_date, ratio::float FROM corp_action_details "
                        "WHERE ticker=%s AND endpoint='crDecsn' "
                        "AND record_date BETWEEN %s AND %s",
                        (t, d - timedelta(days=14), d + timedelta(days=14)))
            cr = cur.fetchall()
            cur.execute("SELECT event_type, event_date FROM corporate_actions "
                        "WHERE ticker=%s AND event_type IN ('merger','spinoff') "
                        "AND event_date BETWEEN %s AND %s",
                        (t, d - timedelta(days=90), d + timedelta(days=90)))
            ms = cur.fetchall()
            cur.execute("SELECT date, shares FROM share_counts WHERE ticker=%s "
                        "ORDER BY date", (t,))
            shares = {dd: int(s) for dd, s in cur.fetchall()}
            se = share_events(sorted(shares), shares)
            late = [(sd, sr) for sd, sr in se
                    if abs((sd - d).days) <= 45 and sr > 0
                    and abs(math.log(sr) - math.log(r)) < math.log(1.4)]
            dart_hits = []
            cc = codes.get(t)
            if cc:
                time.sleep(0.15)
                try:
                    items = fetch_disclosures(key, cc, d - timedelta(days=90),
                                              d + timedelta(days=30),
                                              pblntf_ty="B")
                    dart_hits = [it["report_nm"].strip() for it in items
                                 if any(k in it.get("report_nm", "")
                                        for k in KEYWORDS)]
                except Exception as e:
                    dart_hits = [f"ERROR:{str(e)[:60]}"]
            cls = ("cr_detail_match" if cr else
                   "share_late_match" if late else
                   "merger_spinoff_local" if ms else
                   "dart_disclosure_found" if dart_hits and not str(
                       dart_hits[0]).startswith("ERROR") else "no_evidence")
            rows.append({"ticker": t, "date": g["date"], "ratio": r,
                         "class": cls, "cr": [str(x[0]) for x in cr],
                         "share_late": [str(sd) for sd, _ in late],
                         "dart": dart_hits[:5]})
        # 공시 실재 건 → quality flags 표시
        disclosed = {x["ticker"] for x in rows if x["class"] != "no_evidence"}
        for t in disclosed:
            cur.execute(
                "UPDATE delisted_adj_quality SET flags = flags || %s "
                "WHERE ticker=%s",
                (Jsonb({"upward_gap_disclosed": True}), t))
        conn.commit()
    from collections import Counter
    summary = dict(Counter(x["class"] for x in rows))
    out = {"generated": str(date.today()), "n_gaps": len(rows),
           "by_class": summary, "tickers_flagged": sorted(disclosed),
           "rows": rows}
    path = f"data/verification/issue114_upward_gap_audit_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({"by_class": summary,
                      "tickers_flagged": len(disclosed)}, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
