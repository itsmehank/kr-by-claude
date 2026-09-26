"""[KRX 접촉 — 사용자 승인 후에만 실행] #207 등락률(change_pct) 백필 — 기업행위 조정계수 자체 산출의 입력.

두 모드(각각 KRX 요청 수 = 인자 개수, dry-run 기본 = fetch 만 하고 적재 rollback):
  --dates 2026-09-14 2026-09-15 …   날짜별 전종목 스냅샷(fetch_market_snapshot, market=ALL 1요청/일)
  --tickers 006490,… --start 2026-08-01 --end 2026-09-25   종목별 raw 범위(_fetch_one adjusted=False 1요청/종목)
적재 = store.update_change_pct: change_pct 만 갱신(OHLCV·adj_* 불변). 주말은 달력으로 skip(접촉 0).
usage: KR_ALLOW_KRX=1 uv run python scripts/issue207_change_pct_backfill.py --dates 2026-09-14 … [--execute]
"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import date

import psycopg


def main() -> int:
    if os.environ.get("KR_ALLOW_KRX") != "1":   # pykrx import 자체가 KRX 로그인(접촉 1회)이라 게이트를 import 앞에 둔다
        print("KR_ALLOW_KRX=1 없이는 실행하지 않는다(운영 규칙 5 — KRX 실 접촉 승인 게이트)."); return 2
    from kr_pipeline.common.config import Config
    from kr_pipeline.ohlcv.fetch import _fetch_one, fetch_market_snapshot
    from kr_pipeline.ohlcv.store import update_change_pct
    from kr_pipeline.ohlcv.transform import to_change_pct_rows

    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*", default=[], help="YYYY-MM-DD … (전종목 스냅샷, 1요청/일)")
    ap.add_argument("--tickers", default="", help="쉼표 구분 (종목별 raw 범위, 1요청/종목)")
    ap.add_argument("--start", default=None); ap.add_argument("--end", default=None)
    ap.add_argument("--execute", action="store_true", help="없으면 fetch 만 하고 적재는 rollback")
    ap.add_argument("--report", default="data/verification/issue207_change_pct_backfill_report.json")
    a = ap.parse_args()
    dates = [date.fromisoformat(d) for d in a.dates]
    dates = [d for d in dates if d.weekday() < 5]
    tickers = [t for t in a.tickers.split(",") if t]
    if tickers and not (a.start and a.end):
        print("--tickers 에는 --start/--end 필요"); return 2
    planned = len(dates) + len(tickers)
    print(f"계획 KRX 요청 수 = {planned} (dates {len(dates)} + tickers {len(tickers)}), execute={a.execute}")

    report = {"execute": a.execute, "requests": 0, "dates": {}, "tickers": {}}
    rows: list[tuple] = []
    for d in dates:
        snap = fetch_market_snapshot(d); report["requests"] += 1
        r = to_change_pct_rows(snap)
        report["dates"][d.isoformat()] = {"status": snap.attrs.get("snapshot_status", "ok"), "rows": len(r)}
        rows += r; time.sleep(0.3)
    for t in tickers:
        df = _fetch_one(t, date.fromisoformat(a.start), date.fromisoformat(a.end), adjusted=False); report["requests"] += 1
        r = to_change_pct_rows(df, ticker=t)
        report["tickers"][t] = {"rows": len(r), "first": str(df["date"].min()) if not df.empty else None,
                                "last": str(df["date"].max()) if not df.empty else None}
        rows += r; time.sleep(0.3)

    cfg = Config.load()
    with psycopg.connect(cfg.database_url) as cn:
        n = update_change_pct(cn, rows)
        report["fetched_rows"] = len(rows); report["updated_rows"] = n
        if a.execute:
            cn.commit()
        else:
            cn.rollback()
    json.dump(report, open(a.report, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
