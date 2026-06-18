"""CLI 엔트리."""
import argparse
import json
import logging
import sys
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.llm_runner import (
    weekend, daily_delta, evaluate_pivot, entry_params, performance, backfill, disqualify,
)
from kr_pipeline.llm_runner import modes
from kr_pipeline.llm_runner.load import resolve_as_of
from kr_pipeline.common.trading_calendar import assert_data_fresh


# pipeline_runs.pipeline 컬럼 값. pipeline_specs.py 의 pipeline_db_name 과 일치해야 함.
PIPELINE_DB_NAME_BY_MODE = {
    "weekend": "llm_weekend",
    "daily-delta": "llm_daily_delta",
    "evaluate": "llm_evaluate",
    "entry": "llm_entry",
    "performance": "llm_performance",
    "full-daily": "llm_daily_delta",
    "backfill": "llm_backfill",
    "disqualify": "llm_disqualify",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        required=True,
        choices=["weekend", "daily-delta", "evaluate", "entry", "performance", "full-daily", "backfill", "disqualify"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ticker", type=str, help="단일 종목 디버깅 (weekend mode 만 지원)")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD")
    parser.add_argument("--start", type=str, help="YYYY-MM-DD (backfill 범위 시작)")
    parser.add_argument("--end", type=str, help="YYYY-MM-DD (backfill 범위 종료)")
    parser.add_argument("--tickers", type=str, help="쉼표 구분 종목 코드 (backfill 전용, 생략 시 전 종목)")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--concurrency", type=int, help="병렬 워커 수 (backfill 전용). 생략 시 BACKFILL_CONCURRENCY env 또는 4")
    args = parser.parse_args()

    # --ticker 는 현재 weekend mode 만 함수 시그니처가 지원. 다른 mode 에서 ticker
    # 지정 시 조용히 무시되고 전체 batch 가 실행되어 실 LLM 비용 폭증 위험.
    # 명시적 에러로 차단.
    _TICKER_SUPPORTED_MODES = {"weekend"}
    if args.ticker and args.mode not in _TICKER_SUPPORTED_MODES:
        parser.error(
            f"--ticker is only supported with --mode={'/'.join(sorted(_TICKER_SUPPORTED_MODES))} "
            f"(got --mode={args.mode}). 다른 mode 에선 ticker 가 무시되고 전체 batch 가 실행되어 비용 위험."
        )

    # --start/--end/--tickers 는 backfill 전용. 다른 모드와 쓰면 조용히 무시되어
    # 의도와 다른 동작을 할 수 있으므로 명시적 에러로 차단.
    if args.mode != "backfill" and (args.start or args.end or args.tickers or args.concurrency):
        parser.error("--start/--end/--tickers/--concurrency is only supported with --mode=backfill.")
    if args.mode == "backfill" and (not args.start or not args.end):
        parser.error("--start and --end are required with --mode=backfill (기간 없는 백필은 무의미).")

    logging.basicConfig(
        level=logging.INFO,
        format='{"ts": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": %(message)r}',
    )

    cfg = Config.load()

    with connect(cfg.database_url) as conn:
        # as_of 결정: --date 명시되면 그것, 아니면 daily_indicators 의 최신 날짜.
        # date.today() 사용 시 cron 실행 시각이 새벽이면 그 날 indicators 가 아직
        # 없어서 evaluate_pivot 의 active 가 0 으로 빠지는 문제를 방지.
        explicit = _date.fromisoformat(args.date) if args.date else None
        as_of = resolve_as_of(conn, explicit)
        pipeline_db_name = PIPELINE_DB_NAME_BY_MODE.get(args.mode, args.mode)
        params = {
            "mode": args.mode,
            "dry_run": args.dry_run,
            "as_of": as_of.isoformat(),
            "limit": args.limit,
            "ticker": getattr(args, "ticker", None),
            "start": getattr(args, "start", None),
            "end": getattr(args, "end", None),
            "tickers": getattr(args, "tickers", None),
        }
        with run_tracking(conn, pipeline=pipeline_db_name, mode=args.mode, params=params) as state:
            # ② 신선도 가드: 자동 as_of(명시 --date 아님) & backfill 아닐 때만.
            #    as_of < ELTD 면 StaleDataError, pykrx 실패면 TradingCalendarUnavailable(fail-closed).
            if explicit is None and args.mode != "backfill":
                assert_data_fresh(as_of, datetime.now(ZoneInfo("Asia/Seoul")))
            if args.mode == "weekend":
                result = modes.run_weekend(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit, ticker=args.ticker, run_id=state["run_id"])
            elif args.mode == "daily-delta":
                result = daily_delta.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
            elif args.mode == "evaluate":
                result = evaluate_pivot.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit, force=args.force)
            elif args.mode == "entry":
                result = entry_params.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit, force=args.force)
            elif args.mode == "performance":
                result = performance.run(conn, as_of=as_of)
            elif args.mode == "full-daily":
                result = modes.run_full_daily(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit, force=args.force)
            elif args.mode == "backfill":
                _start = _date.fromisoformat(args.start)
                _end = _date.fromisoformat(args.end)
                _tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
                result = backfill.run(conn, start=_start, end=_end, tickers=_tickers,
                                      dry_run=args.dry_run, limit=args.limit,
                                      concurrency=args.concurrency)
            elif args.mode == "disqualify":
                result = disqualify.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
            else:
                result = {}

            # rows_affected / total_count 추정 — 가능한 값 추출
            if isinstance(result, dict):
                state["rows_affected"] = (
                    result.get("processed")
                    or result.get("rows_affected")
                    or result.get("count")
                )
                state["total_count"] = (
                    result.get("candidates")
                    or result.get("total")
                )
                state["details"] = result

    logging.getLogger("kr_pipeline.llm_runner").info(
        "DONE %s: %s", args.mode, json.dumps(result)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
