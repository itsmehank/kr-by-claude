"""#114 수집 러너 — 부재 종목 시세·주식수 + 생존 종목 주식수 (설계 v2 §1~§3).

실행 창(주말 또는 평일 20:30~06:00)·일일 예산 2,000·페이싱 2s·종목 체크포인트·
연속 오류 5회 중단. 재실행 = 이어받기(멱등). --now 는 창 무시(소량 테스트용).

  uv run python scripts/issue114_collect_delisted.py [--now] [--limit N]
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from pykrx import stock as krx  # noqa: E402
import psycopg  # noqa: E402

from kr_pipeline.ohlcv.delisted_backfill import (  # noqa: E402
    ABORT_CONSECUTIVE_ERRORS, DAILY_CALL_CAP, PACE_SEC, add_calls, calls_today,
    in_window, insert_delisted_prices, insert_share_counts, load_checkpoint,
    price_rows, save_checkpoint, share_rows, upsert_delisted_stock,
)

MISSING = "data/verification/issue114_missing_tickers.json"
CP = Path("data/verification/issue114_checkpoint.json")
DB = "postgresql://localhost/kr_pipeline"
FROM, TO = "20150615", "20260814"   # 하한 = 가격제한폭 체제 경계(전문가 4차)


def _call(cp: dict, fn, *args):
    time.sleep(PACE_SEC)
    add_calls(cp, date.today().isoformat(), 1)
    return fn(*args)


def main() -> int:
    force_now = "--now" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    missing = json.loads(Path(MISSING).read_text())["missing"]
    cp = load_checkpoint(CP)
    with psycopg.connect(DB) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NULL "
                        "ORDER BY ticker")
            survivors = [r[0] for r in cur.fetchall()]

    tasks = ([("delisted", m["ticker"], m["market"]) for m in missing
              if not m["still_listed"]]
             + [("shares", t, None) for t in survivors])
    todo = [t for t in tasks if f"{t[0]}:{t[1]}" not in set(cp["done"])]
    print(f"tasks total={len(tasks)} todo={len(todo)} "
          f"calls_today={calls_today(cp, date.today().isoformat())}")

    errors = 0
    processed = 0
    for kind, ticker, market in todo:
        if limit is not None and processed >= limit:
            print("limit 도달 — 정상 종료")
            break
        if not force_now and not in_window(datetime.now()):
            print("실행 창 밖 — 정상 종료(이어받기 가능)")
            break
        if calls_today(cp, date.today().isoformat()) >= DAILY_CALL_CAP:
            print("일일 예산 도달 — 정상 종료(내일 이어받기)")
            break
        try:
            with psycopg.connect(DB) as conn:
                if kind == "delisted":
                    df = _call(cp, krx.get_market_ohlcv, FROM, TO, ticker, "d", False)
                    if len(df) == 0:
                        raise ValueError("empty ohlcv")
                    name = _call(cp, krx.get_market_ticker_name, ticker)
                    if not isinstance(name, str) or not name:
                        name = f"상폐{ticker}"
                    caps = _call(cp, krx.get_market_cap_by_date, FROM, TO, ticker)
                    last = df.index[-1].date()
                    upsert_delisted_stock(conn, ticker, name, market, last, True)
                    n_p = insert_delisted_prices(conn, price_rows(ticker, df))
                    n_s = insert_share_counts(conn, share_rows(ticker, caps))
                    print(f"[delisted] {ticker} {name}: prices+{n_p} shares+{n_s} "
                          f"last={last}")
                else:
                    caps = _call(cp, krx.get_market_cap_by_date, FROM, TO, ticker)
                    n_s = insert_share_counts(conn, share_rows(ticker, caps))
                    print(f"[shares] {ticker}: +{n_s}")
            cp["done"].append(f"{kind}:{ticker}")
            errors = 0
        except Exception as e:  # noqa: BLE001 — 수집 루프 연속 오류 카운트용
            errors += 1
            print(f"ERROR {kind}:{ticker} — {type(e).__name__}: {e}")
            if "패스워드" in str(e) or errors >= ABORT_CONSECUTIVE_ERRORS:
                save_checkpoint(CP, cp)
                print("중단 조건 발동 — 즉시 종료")
                return 1
        finally:
            save_checkpoint(CP, cp)
        processed += 1

    done_n = len(cp["done"])
    print(f"세션 종료: done={done_n}/{len(tasks)} "
          f"calls_today={calls_today(cp, date.today().isoformat())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
