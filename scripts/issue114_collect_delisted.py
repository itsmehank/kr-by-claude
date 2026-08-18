"""#114 수집 러너 — 부재 종목 시세·주식수 + 생존 종목 주식수 (설계 v2 §1~§3).

실행 창(주말 또는 평일 20:30~06:00)·일일 예산 2,000·페이싱 2s·종목 체크포인트·
연속 오류 5회 중단. 재실행 = 이어받기(멱등). 빈 응답 = 오류(세션 만료가 빈 DF 로
나타나는 pykrx 특성 — 리뷰 C-1). 3회 실패 종목은 스킵·목록화(폴백 대상, I-5).

  uv run python scripts/issue114_collect_delisted.py [--now --limit N]
  (--now 는 창 무시 — 소량 테스트용, --limit 필수)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
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
NAMES = "data/verification/issue114_names.json"   # {ticker: 회사명} — 외부 조달
SCOPE = "data/verification/issue114_survivor_scope.json"  # 전문가 5차 ① 사전등록
CP = Path("data/verification/issue114_checkpoint.json")
DB = os.environ.get("DATABASE_URL", "postgresql://localhost/kr_pipeline")
FROM, TO = "20150615", "20260814"   # 하한 = 가격제한폭 체제 경계(전문가 4차)
MAX_TICKER_FAILURES = 3             # 초과 시 스킵·폴백 목록화(리뷰 I-5)
CALLS_PER_DELISTED = 2              # ohlcv + 주식수 (종목명은 외부 파일 — KRX 호출 없음)


def _call(cp: dict, fn, *args):
    time.sleep(PACE_SEC)
    add_calls(cp, date.today().isoformat(), 1)
    return fn(*args)


def main() -> int:
    force_now = "--now" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if force_now and limit is None:
        print("--now 는 --limit 와 함께만 허용(소량 테스트용)")  # 리뷰 M-4
        return 1

    missing = json.loads(Path(MISSING).read_text())["missing"]
    # 종목명: 외부 조달 파일(웹 수집) — 없으면 자리표시자로 넣고 도착 후
    # scripts/issue114_apply_names.py 로 일괄 갱신(신규 삽입 행만).
    names: dict[str, str] = {}
    if Path(NAMES).exists():
        names = json.loads(Path(NAMES).read_text())
    cp = load_checkpoint(CP)
    # 생존 종목 범위 = 사전등록 scope 파일(전문가 5차 ①: 이벤트 전수 + 무이벤트
    # 표본 150, 시드 고정·사후 교체 금지). 전수 조회로의 폴백은 두지 않는다.
    scope = json.loads(Path(SCOPE).read_text())
    survivors = sorted(set(scope["event_tickers"]) | set(scope["noevent_sample"]))

    # still_listed 스킵 근거(리뷰 I-4): delisted 경로로 넣으면 delisted_at 이
    # 채워진 행이 생기고, 이후 라이브 universe upsert 가 NULL 로 되돌리는 순간
    # 라이브 수집에 편입 — 무영향 원칙 위반. §5 커버리지 분모에서도 제외.
    skipped_still = sum(1 for m in missing if m["still_listed"])
    tasks = ([("delisted", m["ticker"], m["market"]) for m in missing
              if not m["still_listed"]]
             + [("shares", t, None) for t in survivors])
    done = set(cp["done"])
    todo = [t for t in tasks if f"{t[0]}:{t[1]}" not in done]
    print(f"tasks total={len(tasks)} todo={len(todo)} "
          f"skipped_still_listed={skipped_still} "
          f"calls_today={calls_today(cp, date.today().isoformat())}")

    errors = 0
    processed = 0
    for kind, ticker, market in todo:
        key = f"{kind}:{ticker}"
        if limit is not None and processed >= limit:
            print("limit 도달 — 정상 종료")
            break
        if not force_now and not in_window(datetime.now()):
            print("실행 창 밖 — 정상 종료(이어받기 가능)")
            break
        if calls_today(cp, date.today().isoformat()) + CALLS_PER_DELISTED \
                > DAILY_CALL_CAP:                      # 리뷰 M-1: 여유 포함 비교
            print("일일 예산 도달 — 정상 종료(내일 이어받기)")
            break
        if cp["failed"].get(key, 0) >= MAX_TICKER_FAILURES:
            continue                                    # 영구 실패 — 폴백 대상
        try:
            with psycopg.connect(DB) as conn:
                if kind == "delisted":
                    df = _call(cp, krx.get_market_ohlcv, FROM, TO, ticker,
                               "d", False)
                    if len(df) == 0:
                        raise ValueError("empty ohlcv")   # 리뷰 C-1
                    name = names.get(ticker) or f"상폐{ticker}"
                    caps = _call(cp, krx.get_market_cap_by_date, FROM, TO, ticker)
                    if len(caps) == 0:
                        raise ValueError("empty cap")     # 리뷰 C-1
                    last = df.index[-1].date()
                    delisted_at = last + timedelta(days=1)  # 설계 §3-2(리뷰 I-3)
                    upsert_delisted_stock(conn, ticker, name, market,
                                          delisted_at, True)
                    n_p = insert_delisted_prices(conn, price_rows(ticker, df))
                    n_s = insert_share_counts(conn, share_rows(ticker, caps))
                    print(f"[delisted] {ticker} {name}: prices+{n_p} "
                          f"shares+{n_s} last={last}")
                else:
                    caps = _call(cp, krx.get_market_cap_by_date, FROM, TO, ticker)
                    if len(caps) == 0:
                        raise ValueError("empty cap")     # 리뷰 C-1
                    n_s = insert_share_counts(conn, share_rows(ticker, caps))
                    print(f"[shares] {ticker}: +{n_s}")
            cp["done"].append(key)
            cp["failed"].pop(key, None)
            errors = 0
        except Exception as e:  # noqa: BLE001 — 수집 루프 연속 오류 카운트용
            errors += 1
            cp["failed"][key] = cp["failed"].get(key, 0) + 1
            print(f"ERROR {key} — {type(e).__name__}: {e} "
                  f"(연속 {errors}, 이 종목 누적 {cp['failed'][key]})")
            if errors >= ABORT_CONSECUTIVE_ERRORS:
                save_checkpoint(CP, cp)
                print("연속 오류 중단 조건 발동 — 즉시 종료")
                return 1
        finally:
            save_checkpoint(CP, cp)
        processed += 1

    perm_failed = sorted(k for k, n in cp["failed"].items()
                         if n >= MAX_TICKER_FAILURES)
    print(f"세션 종료: done={len(cp['done'])}/{len(tasks)} "
          f"calls_today={calls_today(cp, date.today().isoformat())} "
          f"perm_failed={len(perm_failed)}")
    if perm_failed:
        print("폴백 대상(날짜 기준 조회로 보충):", ", ".join(perm_failed[:20]),
              "..." if len(perm_failed) > 20 else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
