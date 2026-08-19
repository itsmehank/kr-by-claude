"""#114 경로B Phase 2 — DART 구조화 상세 백필 (KRX 0, DART 전용).

대상 = 상폐 전체(stocks.delisted_at NOT NULL) + 생존 검증 범위(scope 1,443).
종목×엔드포인트 4종, 기간 2015-06-15~2026-08-14. 페이싱 0.3s, 종목 단위
체크포인트, 연속 오류 10회 중단. DART 쿼터(일 2만) 내: ~7.6천 호출.

  uv run python scripts/issue114_dart_details_backfill.py [--limit N]
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import psycopg  # noqa: E402

from kr_pipeline.corporate_actions.details import ENDPOINTS, fetch_details, upsert_details  # noqa: E402
from kr_pipeline.ohlcv.delisted_backfill import load_checkpoint, save_checkpoint  # noqa: E402

DB = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")
SCOPE = "data/verification/issue114_survivor_scope.json"
CP = Path("data/verification/issue114_dart_checkpoint.json")
BGN, END = "20150615", "20260814"
PACE = 0.3
ABORT_ERRORS = 10


def main() -> int:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    api_key = os.environ.get("DART_API_KEY", "")
    if not api_key:
        print("DART_API_KEY 없음")
        return 1

    scope = json.load(open(SCOPE))
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NOT NULL")
        delisted = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT stock_code, corp_code FROM dart_corp_codes")
        corp_of = dict(cur.fetchall())

    targets = sorted(set(delisted) | set(scope["event_tickers"])
                     | set(scope["noevent_sample"]))
    cp = load_checkpoint(CP)
    done = set(cp["done"])
    todo = [t for t in targets if t not in done]
    unmapped = [t for t in todo if t not in corp_of]
    print(f"targets={len(targets)} todo={len(todo)} unmapped={len(unmapped)}")

    errors = 0
    processed = 0
    for t in todo:
        if limit is not None and processed >= limit:
            print("limit 도달 — 정상 종료")
            break
        if t not in corp_of:
            cp["failed"][f"unmapped:{t}"] = 1
            cp["done"].append(t)
            save_checkpoint(CP, cp)
            continue
        try:
            with psycopg.connect(DB) as conn:
                total = 0
                for ep in ENDPOINTS:
                    time.sleep(PACE)
                    items = fetch_details(api_key, corp_of[t], ep, BGN, END)
                    total += upsert_details(conn, t, ep, items)
            cp["done"].append(t)
            errors = 0
            if total:
                print(f"[{t}] +{total}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            cp["failed"][t] = cp["failed"].get(t, 0) + 1
            print(f"ERROR {t} — {type(e).__name__}: {e} (연속 {errors})")
            if errors >= ABORT_ERRORS:
                save_checkpoint(CP, cp)
                print("연속 오류 중단")
                return 1
        finally:
            save_checkpoint(CP, cp)
        processed += 1

    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT endpoint, COUNT(*) FROM corp_action_details GROUP BY 1")
        print("적재 현황:", dict(cur.fetchall()))
    print(f"종료: done={len(cp['done'])}/{len(targets)} "
          f"unmapped={len([k for k in cp['failed'] if k.startswith('unmapped')])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
