"""#114 v4 — 주주배정 유상증자 원문 파싱 백필 (8차 ③: 파싱 소스 교체 한정).

대상: corp_action_details 의 piicDecsn 중 method LIKE '%주주%' AND record_date
IS NULL. 원문(document API)에서 신주배정기준일 추출 → record_date UPDATE (v4 가
채우는 유일한 변경). 교차 검증 게이트(8차 ①): 원문 보통주 신주수 vs 구조화
nstk_ostk_cnt 일치율 + 파싱 실패 클래스 보고.

  uv run python scripts/issue114_v4_doc_backfill.py [--limit N]
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date

from dotenv import load_dotenv

load_dotenv()

import psycopg  # noqa: E402

from kr_pipeline.corporate_actions.details import (  # noqa: E402
    fetch_document_text, parse_new_share_count, parse_num,
    parse_rights_record_date,
)

DB = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")
PACE = 0.3


def main() -> int:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    api_key = os.environ["DART_API_KEY"]

    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, rcept_no, payload->>'nstk_ostk_cnt' "
            "FROM corp_action_details WHERE endpoint='piicDecsn' "
            "AND method LIKE '%주주%' AND record_date IS NULL ORDER BY rcept_no")
        targets = cur.fetchall()
    if limit is not None:
        targets = targets[:limit]

    stats = {"total": len(targets), "date_ok": 0, "date_fail": 0,
             "xcheck_ok": 0, "xcheck_mismatch": 0, "xcheck_unparsed": 0,
             "fetch_error": 0}
    fail_samples = []
    for ticker, rcept, struct_cnt in targets:
        time.sleep(PACE)
        try:
            text = fetch_document_text(api_key, rcept)
        except Exception as e:  # noqa: BLE001
            stats["fetch_error"] += 1
            fail_samples.append({"rcept": rcept, "class": "fetch",
                                 "err": str(e)[:60]})
            continue
        rd = parse_rights_record_date(text)
        if rd is None:
            stats["date_fail"] += 1
            fail_samples.append({"rcept": rcept, "class": "no_record_date"})
        else:
            stats["date_ok"] += 1
            with psycopg.connect(DB) as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE corp_action_details SET record_date = %s "
                    "WHERE rcept_no = %s AND endpoint='piicDecsn' "
                    "AND record_date IS NULL", (rd, rcept))
        doc_cnt = parse_new_share_count(text)
        s_cnt = parse_num(struct_cnt)
        if doc_cnt is None or s_cnt is None:
            stats["xcheck_unparsed"] += 1
        elif abs(doc_cnt - s_cnt) < 0.5:
            stats["xcheck_ok"] += 1
        else:
            stats["xcheck_mismatch"] += 1
            fail_samples.append({"rcept": rcept, "class": "xcheck",
                                 "doc": doc_cnt, "struct": s_cnt})

    out = {"generated": str(date.today()), "stats": stats,
           "fail_samples": fail_samples[:40]}
    path = f"data/verification/issue114_v4_parse_gate_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
