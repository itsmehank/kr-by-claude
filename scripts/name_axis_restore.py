"""(#195) 이름축 오탐으로 부당 배제됐던 종목의 복귀 — stocks 행 생성 + 배제 집합 스냅샷 갱신(KRX 재접촉 0).

기본 dry-run(rollback). --execute 로 커밋. 시세 백필은 별도(scripts/secugrp_backfill_new_tickers.py, KRX 승인 게이트).
복귀 대상은 명시(--tickers) — 저장본 전체에 새 split_universe 를 적용한 "적재 대상 ∖ stocks" 와 대조해
명시 목록이 그 밖이면 중단(386380 같은 별건 후보는 출력만).
스냅샷 차분 사유(회신 10): 우선주 판별 코드 규칙 전환(성우·에코글로우·이오플로우 복귀) + ETF 축 제거(BNK금융지주 복귀).
"""
import argparse
import json
import sys
from datetime import date

import pandas as pd
import psycopg

from kr_pipeline.universe.guards import write_exclusion_snapshot
from kr_pipeline.universe.transform import split_universe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot_json", nargs="?", default="data/verification/krx_secugrp_full_20260911.json")
    ap.add_argument("--db", default="postgresql://localhost/kr_pipeline")
    ap.add_argument("--tickers", default="458650,159910,294090,138930")
    ap.add_argument("--snapshot-date", default=date.today().isoformat())
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--report", default="data/verification/name_axis_restore_report.json")
    a = ap.parse_args()
    krx = json.load(open(a.snapshot_json))
    want = [t for t in a.tickers.split(",") if t]
    snap_date = date.fromisoformat(a.snapshot_date)
    rep: dict = {"dry_run": not a.execute, "snapshot_date": a.snapshot_date}

    all_df = pd.DataFrame([{"ticker": t, "name": v["name"], "market": v["market"], "security_group": v["secugrp"]}
                           for t, v in krx.items()])
    kept, excluded = split_universe(all_df)

    with psycopg.connect(a.db) as cn, cn.cursor() as cur:
        cur.execute("SELECT ticker FROM stocks")
        have = {r[0] for r in cur.fetchall()}
        candidates = sorted(set(kept["ticker"]) - have)
        rep["generic_candidates(적재대상 ∖ stocks)"] = candidates
        rep["generic_minus_explicit(별건)"] = sorted(set(candidates) - set(want))
        if not set(want) <= set(candidates):
            print("명시 종목이 후보 밖:", sorted(set(want) - set(candidates)))
            cn.rollback()
            return 2
        rows = [(t, krx[t]["name"], krx[t]["market"], krx[t]["secugrp"]) for t in want]
        cur.executemany("""INSERT INTO stocks (ticker, name, market, sector, security_group, updated_at)
                           VALUES (%s, %s, %s, NULL, %s, NOW()) ON CONFLICT (ticker) DO NOTHING""", rows)
        rep["inserted"] = rows

        cur.execute("SELECT max(snapshot_date) FROM universe_exclusion_snapshot")
        prev = cur.fetchone()[0]
        cur.execute("SELECT ticker FROM universe_exclusion_snapshot WHERE snapshot_date = %s", (prev,))
        prev_set = {r[0] for r in cur.fetchall()}
        cur_set = set(excluded["ticker"])
        rep["snapshot_prev"] = {"date": str(prev), "rows": len(prev_set)}
        rep["snapshot_diff"] = {"removed(배제 해제)": sorted(prev_set - cur_set), "added": sorted(cur_set - prev_set),
                                "reason": "#195: 우선주 판별 코드 말미 규칙 전환(3) + ETF 축 제거(1) — 전문가 회신 10"}
        rep["snapshot_rows"] = write_exclusion_snapshot(cn, snap_date, excluded)
        rep["exclusion_by_axis"] = excluded["axis"].value_counts().to_dict()

        cur.execute("SELECT count(*) FROM stocks WHERE delisted_at IS NULL")
        rep["universe_after"] = cur.fetchone()[0]
        if a.execute:
            cn.commit()
        else:
            cn.rollback()
    json.dump(rep, open(a.report, "w"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
