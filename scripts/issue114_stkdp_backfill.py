"""#114 v5 — 주식배당결정 수시공시 백필 (11차 사전 확약 이행).

대상: 기본 = 표적 64종목(carve-out) + FP 비악화 측정용 무이벤트 표본 150종목.
`--delisted` = 상폐 전 종목(stocks.delisted_at NOT NULL) — P0 생산 선행 백필.
경로: list.json(pblntf_ty='I') → report_nm '주식배당결정' 필터 → 원문 파싱
(parse_stkdp) → corp_action_details(endpoint='stkdpDecsn') 멱등 적재.
DART 호출만(KRX 0), 기존 데이터 무수정(신규 행만).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from kr_pipeline.corporate_actions.dart_client import fetch_disclosures
from kr_pipeline.corporate_actions.details import fetch_document_text, parse_stkdp

DB = "postgresql://localhost/kr_pipeline"
SCOPE = "data/verification/issue114_survivor_scope.json"
PROBE = "data/verification/issue114_seam_probe_20260819.json"
BGN = date(2015, 1, 1)


def main() -> int:
    load_dotenv()
    key = os.environ["DART_API_KEY"]
    delisted = "--delisted" in sys.argv
    if delisted:
        with psycopg.connect(DB) as conn, conn.cursor() as cur:
            cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NOT NULL "
                        "ORDER BY ticker")
            targets = [r[0] for r in cur.fetchall()]
    else:
        scope = json.load(open(SCOPE))
        probe = json.load(open(PROBE))
        targets = sorted(set(probe["carveout_stockdiv"]["excluded_tickers"])
                         | set(scope["noevent_sample"]))
    print(f"targets: {len(targets)} ({'delisted' if delisted else 'verify-scope'})")
    stats = {"tickers": len(targets), "no_corp_code": 0, "disclosures": 0,
             "parsed": 0, "parse_fail": [], "doc_unavailable": [], "inserted": 0}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT stock_code, corp_code FROM dart_corp_codes")
        codes = dict(cur.fetchall())
        for i, t in enumerate(targets, 1):
            cc = codes.get(t)
            if not cc:
                stats["no_corp_code"] += 1
                continue
            items = fetch_disclosures(key, cc, BGN, date.today(), pblntf_ty="I")
            hits = [it for it in items if "주식배당결정" in it.get("report_nm", "")]
            stats["disclosures"] += len(hits)
            for it in hits:
                rc = it["rcept_no"]
                try:
                    text = fetch_document_text(key, rc)
                except Exception as e:      # 원문미제공(구형) — rights_no_doc 동형
                    stats["doc_unavailable"].append(
                        {"ticker": t, "rcept_no": rc, "err": str(e)[:80]})
                    time.sleep(0.15)
                    continue
                p = parse_stkdp(text)
                time.sleep(0.15)
                if not p:
                    stats["parse_fail"].append({"ticker": t, "rcept_no": rc,
                                                "report_nm": it["report_nm"]})
                    continue
                stats["parsed"] += 1
                cur.execute(
                    "INSERT INTO corp_action_details "
                    "(ticker, rcept_no, endpoint, record_date, ratio, method, payload) "
                    "VALUES (%s, %s, 'stkdpDecsn', %s, %s, '주식배당', %s) "
                    "ON CONFLICT DO NOTHING",
                    (t, rc, p["record_date"], p["ratio"],
                     Jsonb({**{k: (v.isoformat() if isinstance(v, date) else v)
                               for k, v in p.items()},
                            "report_nm": it["report_nm"]})))
                stats["inserted"] += cur.rowcount
            conn.commit()
            time.sleep(0.15)
            if i % 25 == 0:
                print(f"  {i}/{len(targets)} discl={stats['disclosures']} "
                      f"ins={stats['inserted']}")
    out = (f"data/verification/issue114_stkdp_backfill_"
           f"{'delisted_' if delisted else ''}{date.today():%Y%m%d}.json")
    with open(out, "w") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != "parse_fail"},
                     ensure_ascii=False),
          f"parse_fail={len(stats['parse_fail'])}")
    print("saved:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
