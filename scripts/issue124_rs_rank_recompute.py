"""#124 — RS 순위(rs_rating)·c8/pass 를 저장 수정종가 기준 현재 빈티지로 표적 재계산 (운영 DB UPDATE — 명시 승인 후). 외부 접촉 0.

  uv run python scripts/issue124_rs_rank_recompute.py --plan  [--target daily|weekly|both] [--full]   # 읽기 전용
  uv run python scripts/issue124_rs_rank_recompute.py --apply [--target …] [--full]                  # 백업 → 적용 → 미러 → 재비교
  uv run python scripts/issue124_rs_rank_recompute.py --restore <backup.json>                        # 정확 복원 + 미러

대상 날짜: 기본 = #122 동결 18사건의 영향 구간(일봉 gap 행+251·주봉 gap 주+51) 합집합 / --full = 전 기간.
쓰기 = 대상 날짜의 전 종목 셀 중 값이 달라진 셀만(rs_rating, 같은 셀의 minervini_c8/pass) + 17종목 일봉 미러(전 기간).
전제: 최근 30일 창 패리티 0(일봉은 2026-11-04 저녁 체인 후, 주봉은 11-07 체인 후) — 실패 시 쓰기 없이 종료 2.
백업: data/verification/issue124_rs_rank_backup_<stamp>_<target>.json (변경 셀의 old rs·c8·pass). 결과: issue124_rs_rank_<stamp>_<target>.json.
종료 코드: 0 정상 / 1 오류 / 2 패리티 실패 또는 적용 후 재비교 ≠ 0.
운영 전제: evening-chain 창(20:25~) 밖, `pgrep -f kr_pipeline` 0, bt-110 웹 스위치 OFF(최초 on 이전에 완료). run_tracking 미사용.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()
# KRX 접촉 0 보장: 지표 모듈 import 가 pykrx 를 끌어오고, pykrx 는 KRX_ID/KRX_PW 가 있으면 import 시점에 로그인을 시도한다
# (#122 --plan 첫 실행에서 로그인 1회 실측). 본 작업은 KRX 가 필요 없으므로 kr_pipeline import 전에 비운다(conftest 동형).
os.environ["KRX_ID"] = ""
os.environ["KRX_PW"] = ""

import psycopg  # noqa: E402

from kr_pipeline.indicators import rs_rank_recompute as m  # noqa: E402
from kr_pipeline.indicators.modes import Target  # noqa: E402
from kr_pipeline.indicators.store import update_daily_rs_gate_from_weekly  # noqa: E402

DB = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")
OUT = "data/verification"
TARGETS = {"daily": [Target.DAILY], "weekly": [Target.WEEKLY], "both": [Target.DAILY, Target.WEEKLY]}


def _iso(c: dict) -> dict:
    return {**c, "date": c["date"].isoformat()}


def _compute(conn, target: Target, *, full: bool) -> dict:
    """읽기 전용: 유니버스·강도 표·패리티·대상 날짜·plan. parity 실패 시 plan 생략."""
    events = m.events_from_frozen()
    target_tickers = {t for t, _ in events}
    tickers = m.universe_tickers(conn, target)
    _, ind, dcol = m.tables(target)
    with conn.cursor() as cur:
        cur.execute(f"SELECT max({dcol}) FROM {ind}")
        latest = cur.fetchone()[0]
    sf = m.strength_table(conn, target, tickers=tickers, end=latest or date.today())
    parity = m.parity_window(conn, target, sf, tickers=tickers)
    out = {"target": target.value, "full": full, "universe": len(tickers), "latest": latest and latest.isoformat(),
           "events": [[t, d.isoformat()] for t, d in events], "parity": parity}
    if parity["mismatch"] or latest is None:
        return out
    trading = m.all_dates(conn, target)
    if full:
        windows, dates = [], trading
    else:
        windows = m.event_windows(conn, target, events)
        dates = m.affected_dates(conn, target, windows)
    p = m.plan(conn, target, dates, sf=sf, target_tickers=target_tickers)
    out.update({"windows": [[w.ticker, w.start.isoformat(), w.end.isoformat()] for w in windows],
                "ranges": [[a.isoformat(), b.isoformat()] for a, b in m.merged_ranges(dates, trading)],
                "trading_dates": len(trading), **p})
    if target == Target.DAILY:
        out["stale_mirror"] = m.stale_mirror_rows(conn, sorted(target_tickers))
    return out


def _print(o: dict) -> None:
    par = o["parity"]
    print(f"[{o['target']}] universe {o['universe']} latest {o['latest']} | parity(30d): dates {par['dates']} "
          f"mismatch {par['mismatch']} last_phase_b {par['last_phase_b_at']}")
    if par["mismatch"]:
        print("  parity 불일치 — 전제(재적재 후 Phase B 실행) 미충족 또는 계산 경로 불일치. 샘플:", par["sample"][:5])
        print("  N(stored, recomputed) by date:", par["n_by_date"])
        return
    if o["latest"] is None:
        print("  지표 테이블 비어 있음 — 대상 없음")
        return
    print(f"  mode {'FULL' if o['full'] else 'windows'}: windows {len(o['windows'])} dates {o['dates']}/{o['trading_dates']} "
          f"ranges {len(o['ranges'])} [{o['date_min']}..{o['date_max']}]")
    print(f"  cells {o['n_cells']} (target17 {o['by_target_ticker']} / other {o['by_other']}) "
          f"delta {o['delta_hist']} c8_flip {o['c8_flip']}")
    if "stale_mirror" in o:
        print(f"  stale mirror rows(17): {sum(o['stale_mirror'].values())} {o['stale_mirror']}")


def cmd_plan(targets, full: bool) -> int:
    rc = 0
    for tg in targets:
        with psycopg.connect(DB) as conn:
            conn.read_only = True
            o = _compute(conn, tg, full=full)
        _print(o)
        if o["parity"]["mismatch"]:
            rc = 2
    return rc


def _mirror(conn, tickers: list[str]) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT min(date), max(date) FROM daily_indicators WHERE ticker = ANY(%s)", (tickers,))
        lo, hi = cur.fetchone()
    if lo is None:
        return 0
    n = update_daily_rs_gate_from_weekly(conn, lo, hi, tickers=tickers)
    conn.commit()
    return n


def cmd_apply(targets, full: bool) -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rc = 0
    for tg in targets:
        with psycopg.connect(DB) as conn:
            conn.read_only = True
            o = _compute(conn, tg, full=full)
        _print(o)
        if o["parity"]["mismatch"]:
            print("  parity 실패 → 쓰기 없이 종료")
            return 2
        cells = o.pop("cells")
        bpath = f"{OUT}/issue124_rs_rank_backup_{stamp}_{tg.value}.json"
        with open(bpath, "w") as f:
            json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"), "issue": 124, **o,
                       "cells": [_iso(c) for c in cells]}, f, ensure_ascii=False)
        print(f"  backup: {bpath} ({len(cells)} cells)")
        result = {"issue": 124, "generated": date.today().isoformat(), "backup": bpath, **o}
        rpath = f"{OUT}/issue124_rs_rank_{stamp}_{tg.value}.json"
        try:
            with psycopg.connect(DB) as conn:
                result["apply"] = m.apply(conn, tg, cells)
                print(f"  apply: {result['apply']}")
                if tg == Target.DAILY:
                    tk = sorted({t for t, _ in m.events_from_frozen()})
                    result["mirror_rows"] = _mirror(conn, tk)
                    result["stale_mirror_after"] = m.stale_mirror_rows(conn, tk)
                    print(f"  mirror: {result['mirror_rows']} rows, stale after {sum(result['stale_mirror_after'].values())}")
            with psycopg.connect(DB) as conn:
                conn.read_only = True
                again = _compute(conn, tg, full=full)
            result["recheck_cells"] = again.get("n_cells")
            result["recheck_parity_mismatch"] = again["parity"]["mismatch"]
            print(f"  recheck: cells {result['recheck_cells']} parity mismatch {result['recheck_parity_mismatch']}")
            if result["recheck_cells"] != 0 or result["recheck_parity_mismatch"]:
                rc = 2
        except Exception as e:  # noqa: BLE001
            result["error"] = f"{type(e).__name__}: {e}"
            print("  ERROR", result["error"], "— --restore", bpath)
            rc = 1
        finally:
            with open(rpath, "w") as f:
                json.dump(result, f, ensure_ascii=False, indent=1)
            print("  saved:", rpath)
        if rc == 1:
            return rc
    return rc


def cmd_restore(bpath: str) -> int:
    b = json.load(open(bpath))
    tg = Target(b["target"])
    cells = [{**c, "date": date.fromisoformat(c["date"])} for c in b["cells"]]
    with psycopg.connect(DB) as conn:
        r = m.restore(conn, tg, cells)
        print(f"restore[{tg.value}]: {r} (backup {len(cells)} cells)")
        if tg == Target.DAILY:
            print("mirror rows:", _mirror(conn, sorted({t for t, _ in m.events_from_frozen()})))
    return 0


def main() -> int:
    a = sys.argv[1:]
    targets = TARGETS[a[a.index("--target") + 1]] if "--target" in a else TARGETS["both"]
    full = "--full" in a
    if "--plan" in a:
        return cmd_plan(targets, full)
    if "--apply" in a:
        return cmd_apply(targets, full)
    if "--restore" in a:
        return cmd_restore(a[a.index("--restore") + 1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
