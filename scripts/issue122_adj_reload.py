"""#122 — 확정 누락 18건/17종목 참조 adj 소급 재적재 (운영 DB UPDATE — 명시 승인 후 실행). 외부 접촉 0.

  uv run python scripts/issue122_adj_reload.py --plan                       # 읽기 전용: 대상·상태·행 수
  uv run python scripts/issue122_adj_reload.py --apply [--tickers A,B]      # 백업 파일 기록 → 종목별 트랜잭션 적용 → 지표 재계산
  uv run python scripts/issue122_adj_reload.py --restore <backup.json>      # 백업으로 복원(적용된 건만) + 지표 재계산

입력: data/verification/issue122_adj_missing_audit_20261103.json (missing_confirmed 행, 모듈 동결본과 집합 동일해야 함).
백업: data/verification/issue122_adj_reload_backup_<stamp>.json — 첫 UPDATE 전에 전 대상 스냅샷(plan 상태 포함)을 먼저 쓴다.
결과: data/verification/issue122_adj_reload_<stamp>.json — 재계산 실패가 있어도 항상 기록.
종료 코드: 0 정상 / 1 적용·재계산 오류 / 2 오류 없이 skip(recorded 제외)이 있음.
운영 전제(리뷰 R1 메모 ⑧): evening-chain 창(20:25~) 밖, `pgrep -f kr_pipeline` 0, bt-110 웹 스위치 OFF.
결정(사용자 11-03): 조정일 = gap_date / 지표 재계산은 17종목 Phase A 만(전 종목 과거 RS·pass 불변) / 저장 판정 불변.
재계산 실패 시 복구 = `drift.reload_ticker`(멱등) 재실행.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()
# KRX 접촉 0 보장: 지표·주봉 모듈 import 가 pykrx 를 끌어오고, pykrx 는 KRX_ID/KRX_PW 가 있으면 import 시점에
# KRX 로그인을 시도한다(2026-11-03 --plan 실행에서 로그인 1회 실측). 본 작업은 KRX 가 필요 없으므로 비운다(conftest 동형).
os.environ["KRX_ID"] = ""
os.environ["KRX_PW"] = ""

import psycopg  # noqa: E402

from kr_pipeline.ohlcv.adj_reload_events import (  # noqa: E402
    Target, apply_target, backup_rows, load_targets, plan_target, recompute_ticker, restore_rows,
)

DB = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")
AUDIT = "data/verification/issue122_adj_missing_audit_20261103.json"
OK_SKIPS = (None, "recorded")


def _targets(only: set[str] | None) -> list[Target]:
    ts = load_targets(json.load(open(AUDIT)))
    if only is not None:
        unknown = only - {t.ticker for t in ts}
        if unknown:
            print(f"경고: 대상에 없는 종목 {sorted(unknown)}")
        ts = [t for t in ts if t.ticker in only]
    return ts


def _print_plan(p: dict) -> None:
    rg = p["raw_gap_x_coef"]
    print(f"{p['ticker']} {p['date']} {p['kind']:5s} coef {p['coef']:<8g} rows_before {p['rows_before']:5d} "
          f"factor_ratio {p['factor_ratio'] and round(p['factor_ratio'], 4)} "
          f"raw_gap×coef {rg and round(rg, 3)}{' ⚠' if rg and abs(rg - 1) > 0.15 else ''} -> {p['state']}")


def cmd_plan(only) -> int:
    with psycopg.connect(DB) as conn:
        conn.read_only = True
        plans = [plan_target(conn, t) for t in _targets(only)]
    for p in plans:
        _print_plan(p)
    from collections import Counter
    print("states:", dict(Counter(p["state"] for p in plans)), "rows_before 합:", sum(p["rows_before"] for p in plans))
    return 0


def cmd_apply(only) -> int:
    ts = _targets(only)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bpath = f"data/verification/issue122_adj_reload_backup_{stamp}.json"
    rpath = f"data/verification/issue122_adj_reload_{stamp}.json"
    with psycopg.connect(DB) as conn:
        conn.read_only = True
        backup = {"generated_at": datetime.now().isoformat(timespec="seconds"), "targets": [
            {"ticker": t.ticker, "date": t.date.isoformat(), "coef": t.coef, "kind": t.kind,
             "ex_date": t.ex_date.isoformat(), "rcept_no": t.rcept_no, "plan": plan_target(conn, t),
             "rows": backup_rows(conn, t)} for t in ts]}
    with open(bpath, "w") as f:
        json.dump(backup, f, ensure_ascii=False)
    print(f"backup: {bpath} ({sum(len(b['rows']) for b in backup['targets'])} rows)")

    results, touched, recomputed, rc_errors = [], [], {}, {}
    try:
        for t in ts:
            with psycopg.connect(DB) as conn:
                try:
                    out = apply_target(conn, t)
                    conn.commit()
                except Exception as e:  # noqa: BLE001
                    conn.rollback()
                    out = {"ticker": t.ticker, "date": t.date.isoformat(), "error": f"{type(e).__name__}: {e}"}
            results.append(out)
            print(f"{t.ticker} {t.date} coef {t.coef:g}: "
                  + (out.get("error") or f"skipped={out['skipped']} applied_rows={out['applied_rows']} "
                                         f"continuity {out['continuity_after'] and round(out['continuity_after'], 3)}"))
            if out.get("applied_rows"):
                touched.append(t.ticker)
        for tk in sorted(set(touched)):
            try:
                with psycopg.connect(DB) as conn:
                    recomputed[tk] = recompute_ticker(conn, tk)
                    conn.commit()
                print(f"recompute {tk}: {recomputed[tk]}")
            except Exception as e:  # noqa: BLE001
                rc_errors[tk] = f"{type(e).__name__}: {e}"
                print(f"recompute {tk} ERROR {rc_errors[tk]} — drift.reload_ticker 재실행으로 복구")
    finally:
        out = {"issue": 122, "generated": date.today().isoformat(), "backup": bpath, "results": results,
               "recomputed": recomputed, "recompute_errors": rc_errors}
        with open(rpath, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("saved:", rpath)
    skips = [(r["ticker"], r["date"], r["skipped"]) for r in results if r.get("skipped") not in OK_SKIPS]
    if skips:
        print("skip(검토 필요):", skips)
    if any("error" in r for r in results) or rc_errors:
        return 1
    return 2 if skips else 0


def cmd_restore(bpath: str) -> int:
    backup = json.load(open(bpath))
    bt = datetime.fromisoformat(backup["generated_at"])
    touched = []
    for b in backup["targets"]:
        t = Target(b["ticker"], date.fromisoformat(b["date"]), b["coef"], b["kind"],
                   date.fromisoformat(b["ex_date"]), b.get("rcept_no"))
        if b.get("plan", {}).get("state") != "missing":
            print(f"restore {t.ticker} {t.date}: 백업 시점 상태 {b.get('plan', {}).get('state')} — 건너뜀")
            continue
        with psycopg.connect(DB) as conn:
            r = restore_rows(conn, t, b["rows"], backup_time=bt)
            conn.commit()
        print(f"restore {t.ticker} {t.date}: {r}")
        if r["restored_rows"]:
            touched.append(t.ticker)
    for tk in sorted(set(touched)):
        with psycopg.connect(DB) as conn:
            print(f"recompute {tk}: {recompute_ticker(conn, tk)}")
            conn.commit()
    return 0


def main() -> int:
    only = None
    if "--tickers" in sys.argv:
        only = set(sys.argv[sys.argv.index("--tickers") + 1].split(","))
    if "--plan" in sys.argv:
        return cmd_plan(only)
    if "--apply" in sys.argv:
        return cmd_apply(only)
    if "--restore" in sys.argv:
        return cmd_restore(sys.argv[sys.argv.index("--restore") + 1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
