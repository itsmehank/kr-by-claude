#!/usr/bin/env python3
"""분류 분포 드리프트 모니터 — analyze_chart_v3 ZIP→인라인 전환(2026-06-15) 후 검토용.

**read-only.** 기존 weekly_classification 레코드만 SELECT 한다. 분석/적재 파이프라인
경로와 비결합 — cron 이나 러너가 import 하지 않는 독립 리포트. 새 모니터링
서브시스템이 아니라, 이미 쌓이는 분류 레코드를 사후 비교하는 스크립트일 뿐.

목적: 전송 방식만 바꾼 변경이 verdict 분포를 흔들지 않았는지 확인.
워치 포인트(3단계 결정):
  - ignore→watch 드리프트: 컷오버 이후 ignore 비율이 zip 기준선 밴드(mean-2σ) 아래로
    체계적으로 떨어지면(=워치리스트 비대화) 플래그.
  - entry 비율 이상: 회귀 패널에 entry 가 0건이라 entry 안정성 미검증 → production 에서
    entry 비율이 기준선 밴드를 벗어나면 플래그.

usage:
  DATABASE_URL=... python scripts/monitor_classification_drift.py [--cutover YYYY-MM-DD] [--source weekend]
컷오버 기본값 = 2026-06-15(인라인 병합일). 임계 초과 시 검토 후 zip 스위치백 고려
(docs/analyze_chart_inline_rollback.md).
"""
from __future__ import annotations

import argparse
import os
import statistics as st
from collections import defaultdict

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect

CLASSES = ("ignore", "watch", "entry")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutover", default="2026-06-15", help="인라인 전환일 (이 날짜 이상 = inline-era)")
    ap.add_argument("--source", default="weekend", help="weekly_classification.source 필터")
    args = ap.parse_args()

    with connect(Config.load().database_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT analyzed_for_date, classification, COUNT(*)
            FROM weekly_classification
            WHERE source = %s AND analyzed_for_date IS NOT NULL
              AND classification IN ('ignore','watch','entry')
            GROUP BY analyzed_for_date, classification
            ORDER BY analyzed_for_date
            """,
            (args.source,),
        )
        rows = cur.fetchall()

    # batch[date][class] = count
    batch: dict = defaultdict(lambda: {c: 0 for c in CLASSES})
    for d, cls, n in rows:
        batch[d][cls] = n

    def rates(counts):
        tot = sum(counts.values())
        return (tot, {c: (counts[c] / tot if tot else 0.0) for c in CLASSES})

    cutover = args.cutover
    base_ignore, base_entry = [], []
    print(f"{'batch':12} {'n':>4}  {'ignore%':>8} {'watch%':>7} {'entry%':>7}   era")
    print("-" * 56)
    post = []
    for d in sorted(batch):
        tot, r = rates(batch[d])
        era = "inline" if str(d) >= cutover else "zip"
        if era == "zip":
            base_ignore.append(r["ignore"]); base_entry.append(r["entry"])
        else:
            post.append((d, tot, r))
        print(f"{str(d):12} {tot:>4}  {r['ignore']*100:>7.1f} {r['watch']*100:>6.1f} {r['entry']*100:>6.1f}   {era}")

    print("\n=== 기준선(zip-era) 밴드 ===")
    if len(base_ignore) >= 2:
        mi, si = st.mean(base_ignore), st.pstdev(base_ignore)
        me = st.mean(base_entry)
        lo = mi - 2 * si
        print(f"  ignore% mean={mi*100:.1f} σ={si*100:.1f} → 하한(mean-2σ)={lo*100:.1f}%")
        print(f"  entry%  mean={me*100:.1f}")
        print("\n=== inline-era 점검 ===")
        if not post:
            print("  (컷오버 이후 배치 없음 — 전환 후 첫 주말 배치부터 채워짐)")
        for d, tot, r in post:
            flags = []
            if r["ignore"] < lo:
                flags.append(f"IGNORE 하락 {r['ignore']*100:.1f}%<{lo*100:.1f}% (워치리스트 비대화 의심)")
            if base_entry and (r["entry"] > me + 0.10 or (me == 0 and r["entry"] > 0.05)):
                flags.append(f"ENTRY 비율 이상 {r['entry']*100:.1f}% (기준선 {me*100:.1f}%)")
            print(f"  {d}: {'⚠ ' + ' / '.join(flags) if flags else 'OK (밴드 내)'}")
    else:
        print("  기준선 배치 < 2 — 밴드 산출 불가. zip-era 데이터 누적 후 재실행.")
    print("\n임계 초과 시: docs/analyze_chart_inline_rollback.md 참고 → 전송 ZIP 스위치백 검토.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
