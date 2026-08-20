"""#114 12차 ③ — 레거시 상폐 12종목 share_counts 1회 수집 (KRX 12요청, 재수집 없음).

대상 = stocks.delisted_at NOT NULL AND daily_prices 보유(참조 있는 유일 e2e 앵커).
기존 delisted_backfill 헬퍼(페이싱·적재) 재사용. 이미 share_counts 가 있는
종목은 스킵(1회 원칙 — 멱등이 아니라 '재수집 금지'가 규율).
시대 한정: 이 표본 = 현대 서식 앵커 — 2015~19 구형 서식 구간은 본 대조로 미검증.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date

from dotenv import load_dotenv

load_dotenv()

from pykrx import stock as krx  # noqa: E402
import psycopg  # noqa: E402

from kr_pipeline.ohlcv.delisted_backfill import (  # noqa: E402
    PACE_SEC, insert_share_counts, share_rows,
)

DB = "postgresql://localhost/kr_pipeline"
FROM, TO = "20150615", "20260820"


def main() -> int:
    out = {"generated": str(date.today()), "collected": [], "skipped": [],
           "failed": []}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT s.ticker FROM stocks s "
            "JOIN daily_prices p ON p.ticker = s.ticker "
            "WHERE s.delisted_at IS NOT NULL ORDER BY 1")
        legacy = [r[0] for r in cur.fetchall()]
        print("legacy delisted:", legacy)
        for t in legacy:
            cur.execute("SELECT COUNT(*) FROM share_counts WHERE ticker=%s", (t,))
            if cur.fetchone()[0] > 0:
                out["skipped"].append(t)     # 재수집 금지
                continue
            try:
                time.sleep(PACE_SEC)
                caps = krx.get_market_cap_by_date(FROM, TO, t)
                n = insert_share_counts(conn, share_rows(t, caps))
                conn.commit()
                out["collected"].append({"ticker": t, "rows": n})
                print(f"[shares] {t}: +{n}")
            except Exception as e:
                out["failed"].append({"ticker": t, "err": str(e)[:100]})
    path = f"data/verification/issue114_legacy_shares_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: (len(v) if isinstance(v, list) else v)
                      for k, v in out.items()}, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
