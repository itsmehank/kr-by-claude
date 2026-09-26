"""[KRX 접촉 — 사용자 승인 후에만 실행] SECUGRP 필터로 신규 편입된 종목의 전기간 일봉 백필.

종목별 pykrx get_market_ohlcv raw(KRX) 1회 = KRX 요청 = 종목 수. **Naver 접촉 0**(#207 A안).
수정 OHLCV 는 그 종목의 전 기간 change_pct(KRX 등락률)로 조정일을 검출해 adjust.derive_adj(raw × F) 로 산출하고
조정일은 adj_factor_events 에 기록한다. weekly_prices·지표는 다음 정규 실행이 채운다.

usage: KR_ALLOW_KRX=1 uv run python scripts/secugrp_backfill_new_tickers.py 088980,138040,369370 [--execute]
plan: docs/superpowers/plans/2026-09-15-secugrp-universe-filter.md Task 6 Step 7.
"""
import argparse
import json
import os
import sys
import time
from datetime import date, timedelta

import psycopg

from kr_pipeline.common.config import Config
from kr_pipeline.ohlcv.fetch import _fetch_one
from kr_pipeline.ohlcv.modes import _get_db_min_date
from kr_pipeline.ohlcv.store import upsert_daily_prices
from kr_pipeline.ohlcv import adjust
from kr_pipeline.ohlcv.transform import to_price_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers")
    ap.add_argument("--execute", action="store_true", help="없으면 fetch 만 하고 적재는 rollback")
    ap.add_argument("--report", default="data/verification/secugrp_backfill_report.json")
    a = ap.parse_args()
    if os.environ.get("KR_ALLOW_KRX") != "1":
        print("KR_ALLOW_KRX=1 없이는 실행하지 않는다(운영 규칙 5 — KRX 실 접촉 승인 게이트).")
        return 2
    cfg = Config.load()
    tickers = [t for t in a.tickers.split(",") if t]
    rep: dict = {"execute": a.execute, "tickers": {}}
    end = date.today() - timedelta(days=1)
    with psycopg.connect(cfg.database_url) as cn:
        start = _get_db_min_date(cn)
        rep["range"] = [start.isoformat(), end.isoformat()]
        for t in tickers:
            raw = _fetch_one(t, start, end, adjusted=False)      # KRX (change_pct 포함)
            time.sleep(1.0)
            info = {"raw_rows": len(raw)}
            if raw.empty:
                info["skipped"] = "empty raw — 적재 보류(#95 규약)"
                rep["tickers"][t] = info
                continue
            raw = raw.sort_values("date").reset_index(drop=True)
            events = adjust.events_in_frame(raw, prev_close=None, min_date=None)   # 신규 종목: Naver 이력 없음 → 전 기간 자체 산출
            merged = adjust.derive_adj(raw, events)
            rows = to_price_rows(t, merged)
            info["rows"] = len(rows)
            info["events"] = [(str(d), round(c, 6)) for d, c in events]
            info["first"], info["last"] = str(merged["date"].min()), str(merged["date"].max())
            info["upserted"] = upsert_daily_prices(cn, rows)
            info["events_recorded"] = adjust.record_events(cn, t, events)
            rep["tickers"][t] = info
        if a.execute:
            cn.commit()
        else:
            cn.rollback()
    json.dump(rep, open(a.report, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
