#!/usr/bin/env python
"""#175 과거 행 handle_low 소급 — spec 2026-11-06-issue175-handle-low-design.md §7.

대상: pattern = 'cup_with_handle' AND handle_low IS NULL 인 행. 신 검출기(compute_handle_quality, as_of = COALESCE(analyzed_for_date, KST−1))
로 산출해 `handle_low·handle_start·handle_end` **만** 채운다. triggered_rules·risk_flags·classification 은 건드리지 않는다(과거 트리거
기록 확정 — #253 §8·pivot-offset-removal §1 과 같은 원칙).

  --plan  [--table <t>|all]   읽기 전용. 채울 행 수 / 미평가 사유 분포 / handle_above_pivot 수 출력(쓰기 0).
  --apply --table <t>         테이블 하나 명시 필수('all' 거부). WHERE <PK> AND handle_low IS NULL 로 UPDATE. **사용자 승인 후에만 실행.**

KRX 0·DART 0·LLM 0. 사용 예:  uv run python scripts/issue175_handle_low_backfill.py --plan --table all
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date

import psycopg
from dotenv import load_dotenv

from kr_pipeline.llm_runner.compute.handle_low_backfill import ALL_TABLES, PK_COLUMNS, plan_rows, require_table_for_apply
from kr_pipeline.llm_runner.compute.handle_quality import compute_handle_quality_with_reason, kst_fallback_as_of


def has_handle_low_column(conn, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = 'handle_low'", (table,))
        return cur.fetchone() is not None


def detect_rows(conn, table: str):
    """(행 키, 검출 결과 | None, skip 사유) 생성. SELECT 만."""
    if True:
        with conn.cursor() as cur:
            # 운영 DB 에 schema.sql(handle_low 열)이 아직 적용되지 않았으면(--plan 선행 실행) 열 없이 전 cwh 행을 후보로 본다.
            has_col = has_handle_low_column(conn, table)
            null_filter = "AND handle_low IS NULL" if has_col else ""
            if not has_col:
                print(f"[{table}] handle_low 열 없음 — schema.sql 미적용 상태, 전 cwh 행을 후보로 집계(--apply 는 열 적용 후)", file=sys.stderr)
            cur.execute(f"""SELECT symbol, classified_at, analyzed_for_date, pattern, pivot_price, pivot_basis,
                                   base_high, base_low, base_depth_pct, base_start_date
                              FROM {table}
                             WHERE pattern = 'cup_with_handle' {null_filter}
                             ORDER BY classified_at""")
            rows = cur.fetchall()
        for (sym, cat, afd, pat, pv, pb, bh, bl, bd, bsd) in rows:
            cls = {"pattern": pat, "pivot_basis": pb, "base_start_date": bsd, "pivot_price": pv,
                   "base_depth_pct": bd, "base_high": bh, "base_low": bl}
            det, reason = compute_handle_quality_with_reason(conn, sym, cat, cls, as_of=afd or kst_fallback_as_of(cat))
            yield (sym, cat, afd), det, reason


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--table", default="all")
    args = ap.parse_args()
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    tables = list(ALL_TABLES) if args.table == "all" else [args.table]
    if args.apply:
        tables = [require_table_for_apply(args.table)]
    for t in tables:
        if t not in PK_COLUMNS:
            print(f"unknown table {t!r}", file=sys.stderr)
            return 2
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        if args.plan:
            conn.read_only = True
        if args.apply and not has_handle_low_column(conn, tables[0]):
            print(f"[{tables[0]}] handle_low 열 없음 — schema.sql 을 먼저 적용하세요(--apply 중단)", file=sys.stderr)
            return 2
        for t in tables:
            detected = list(detect_rows(conn, t))
            summary = plan_rows((det, reason) for _k, det, reason in detected)
            summary["table"] = t
            summary["candidates"] = len(detected)
            print(json.dumps(summary, ensure_ascii=False, indent=1))
            if args.apply:
                pk = PK_COLUMNS[t]
                where = " AND ".join(f"{c} = %s" for c in pk) + " AND handle_low IS NULL"
                n = 0
                with conn.cursor() as cur:
                    for (sym, cat, afd), det, _reason in detected:
                        if det is None:
                            continue
                        sl = det["structural_low"]
                        key = (sym, cat) if pk[1] == "classified_at" else (sym, afd)
                        cur.execute(f"UPDATE {t} SET handle_low = %s, handle_start = %s, handle_end = %s WHERE {where}",
                                    (sl["price"], date.fromisoformat(sl["start"]), date.fromisoformat(sl["end"]), *key))
                        n += cur.rowcount
                conn.commit()
                print(json.dumps({"table": t, "updated": n}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
