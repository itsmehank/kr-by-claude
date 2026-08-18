"""#114 — 외부 조달 종목명 일괄 적용 (KRX 호출 0).

data/verification/issue114_names.json ({ticker: 회사명})을 읽어, 수집기가
자리표시자('상폐<ticker>')로 넣은 **신규 삽입 행만** UPDATE 한다.
기존(수집 전부터 있던) stocks 행은 조건상 절대 건드리지 않는다.

  uv run python scripts/issue114_apply_names.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg

NAMES = Path("data/verification/issue114_names.json")
DB = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")


def main() -> int:
    if not NAMES.exists():
        print(f"이름 파일 없음: {NAMES}")
        return 1
    names = json.loads(NAMES.read_text())
    updated = 0
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for ticker, name in sorted(names.items()):
            if not name:
                continue
            cur.execute(
                "UPDATE stocks SET name = %s WHERE ticker = %s "
                "AND delisted_at IS NOT NULL AND name = %s",
                (str(name).strip(), ticker, f"상폐{ticker}"),
            )
            updated += cur.rowcount
    print(f"이름 적용: {updated}건 (자리표시자 행만)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
