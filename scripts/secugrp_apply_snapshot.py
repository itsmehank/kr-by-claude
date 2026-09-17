"""SECUGRP 저장본 → 운영 반영 (KRX 재접촉 0). 기본 dry-run — 변경 예정 전량 출력 후 rollback.

--execute: 커밋. --retro: 소급 표기(excluded_reason 6+1+1행 + 094800 모니터링 종료 행) 포함.
--insert-tickers: 신규 편입 종목(명시 — 일반 규칙 후보와 대조해 명시 목록이 후보 밖이면 중단).

단계: ① 활성 stocks security_group 갱신(저장본에 있는 종목만, UNRESOLVED 로 덮어쓰지 않음)
      ② 신규 편입 행 INSERT(name·market 저장본, sector NULL) ③ 초기 배제 집합 스냅샷(전환 후 상태)
      ④ [--retro] excluded_reason 표기 + 094800 시스템 종료 행 ⑤ 보고 수치 JSON.

plan: docs/superpowers/plans/2026-09-15-secugrp-universe-filter.md Task 6.
"""
import argparse
import json
import sys
from datetime import date, datetime, timezone

import pandas as pd
import psycopg

from kr_pipeline.common.security_group import (
    ROW_KEPT_EXCLUDED_SECURITY_GROUPS, UNRESOLVED, excluded_reason_text,
)
from kr_pipeline.universe.guards import write_exclusion_snapshot
from kr_pipeline.universe.transform import split_universe

RETRO_SYMBOLS = ("094800", "415640")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot_json")
    ap.add_argument("--db", default="postgresql://localhost/kr_pipeline")
    ap.add_argument("--snapshot-date", default="2026-09-15")
    ap.add_argument("--insert-tickers", default="088980,138040,369370")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--retro", action="store_true")
    ap.add_argument("--report", default="data/verification/secugrp_apply_report.json")
    a = ap.parse_args()
    snap_date = date.fromisoformat(a.snapshot_date)
    krx = json.load(open(a.snapshot_json))
    want_insert = set(filter(None, a.insert_tickers.split(",")))
    rep: dict = {"dry_run": not a.execute, "snapshot_date": a.snapshot_date}

    with psycopg.connect(a.db) as cn, cn.cursor() as cur:
        cur.execute("SELECT ticker, name, market, security_group FROM stocks WHERE delisted_at IS NULL")
        active = {t: (n, m, g) for t, n, m, g in cur.fetchall()}
        rep["universe_before"] = len(active)

        # ① 갱신 — 저장본에 있는 활성 종목만. 저장본 부재 종목은 기존 값 유지(fail-open).
        upd = [(krx[t]["secugrp"], t) for t in active if t in krx and active[t][2] != krx[t]["secugrp"]]
        cur.executemany("UPDATE stocks SET security_group = %s, updated_at = NOW() WHERE ticker = %s", upd)
        rep["security_group_updated"] = len(upd)
        rep["unresolved_after_update"] = sorted(t for t in active if t not in krx)

        # ② 신규 편입 — 일반 규칙 후보(저장본 ∖ stocks, 적재 전 배제 통과)와 명시 목록 대조
        cand_df = pd.DataFrame([{"ticker": t, "name": v["name"], "market": v["market"], "security_group": v["secugrp"]}
                                for t, v in krx.items() if t not in active])
        kept, _ = split_universe(cand_df)
        generic = set(kept["ticker"])
        rep["generic_new_candidates"] = sorted(generic)
        rep["generic_minus_explicit(별건 — 미반영)"] = sorted(generic - want_insert)
        if not want_insert <= generic:
            print("명시 편입 종목이 일반 규칙 후보에 없음:", sorted(want_insert - generic))
            cn.rollback()
            return 2
        ins = [(t, krx[t]["name"], krx[t]["market"], krx[t]["secugrp"]) for t in sorted(want_insert)]
        cur.executemany("""INSERT INTO stocks (ticker, name, market, sector, security_group, updated_at)
                           VALUES (%s, %s, %s, NULL, %s, NOW()) ON CONFLICT (ticker) DO NOTHING""", ins)
        rep["inserted"] = ins

        # ③ 초기 스냅샷 = 전환 후 배제 집합(저장본 전체에 split_universe 적용)
        all_df = pd.DataFrame([{"ticker": t, "name": v["name"], "market": v["market"], "security_group": v["secugrp"]}
                               for t, v in krx.items()])
        _, excluded = split_universe(all_df)
        rep["exclusion_snapshot_rows"] = write_exclusion_snapshot(cn, snap_date, excluded)
        rep["exclusion_by_axis"] = excluded["axis"].value_counts().to_dict()

        # ④ 소급 — 행 삭제 없음. 표기만.
        if a.retro:
            marks = {}
            for sym in RETRO_SYMBOLS:
                reason = excluded_reason_text(krx[sym]["secugrp"])
                for tbl in ("weekly_classification", "trigger_evaluation_log", "entry_params"):
                    cur.execute(f"UPDATE {tbl} SET excluded_reason = %s WHERE symbol = %s AND excluded_reason IS NULL",
                                (reason, sym))
                    marks[f"{sym}.{tbl}"] = cur.rowcount
            rep["retro_marked_rows"] = marks
            # 094800 은 최신 분류가 entry → get_active_monitoring 이 계속 반환해 트리거 평가가 이어짐.
            # 기존 구조 기제(시스템 강등 행)로 모니터링을 종료한다 — 사유는 증권구분(사실), 추세 기준 아님.
            # [Q-6 명시 가정] 전문가 열거 목록 밖의 '추가 행'. 삭제·변조 아님. 회신에서 확인 요청.
            from kr_pipeline.llm_runner.store import insert_disqualification
            cur.execute("""SELECT classification FROM weekly_classification WHERE symbol = '094800'
                           ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC LIMIT 1""")
            latest = cur.fetchone()
            if latest and latest[0] in ("entry", "watch"):
                now = datetime.now(timezone.utc)
                insert_disqualification(cn, symbol="094800", classified_at=now, market="KOSPI",
                                        reason=excluded_reason_text("투자회사"), analyzed_for_date=snap_date)
                cur.execute("UPDATE weekly_classification SET excluded_reason = %s WHERE symbol='094800' AND classified_at = %s",
                            (excluded_reason_text("투자회사"), now))
                rep["monitoring_closed_094800"] = now.isoformat()
            else:
                rep["monitoring_closed_094800"] = f"skip(latest={latest[0] if latest else None})"

        # ⑤ 보고
        cur.execute("SELECT ticker, security_group FROM stocks WHERE delisted_at IS NULL")
        after = dict(cur.fetchall())
        rep["universe_after"] = len(after)
        rep["row_kept_excluded"] = sorted(t for t, g in after.items() if g in ROW_KEPT_EXCLUDED_SECURITY_GROUPS)
        rep["unresolved"] = sorted(t for t, g in after.items() if g == UNRESOLVED)
        rep["qualifying_pool_expert_def(활성-게이트제외3)"] = len(after) - len(rep["row_kept_excluded"])
        rep["qualifying_pool_strict(UNRESOLVED 도 제외)"] = len(after) - len(rep["row_kept_excluded"]) - len(rep["unresolved"])
        cur.execute("SELECT security_group, count(*) FROM stocks WHERE delisted_at IS NULL GROUP BY 1 ORDER BY 2 DESC")
        rep["active_group_dist"] = dict(cur.fetchall())

        if a.execute:
            cn.commit()
        else:
            cn.rollback()
    json.dump(rep, open(a.report, "w"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
