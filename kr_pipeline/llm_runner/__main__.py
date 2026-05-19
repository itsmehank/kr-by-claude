"""CLI 엔트리."""
import argparse
import json
import logging
import sys
from datetime import date as _date

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.llm_runner import (
    weekend, daily_delta, evaluate_pivot, entry_params, performance,
)
from kr_pipeline.llm_runner import modes


# pipeline_runs.pipeline 컬럼 값. pipeline_specs.py 의 pipeline_db_name 과 일치해야 함.
PIPELINE_DB_NAME_BY_MODE = {
    "weekend": "llm_weekend",
    "daily-delta": "llm_daily_delta",
    "evaluate": "llm_evaluate",
    "entry": "llm_entry",
    "performance": "llm_performance",
    "full-daily": "llm_daily_delta",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        required=True,
        choices=["weekend", "daily-delta", "evaluate", "entry", "performance", "full-daily"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ticker", type=str)
    parser.add_argument("--date", type=str, help="YYYY-MM-DD")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='{"ts": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": %(message)r}',
    )

    cfg = Config.load()

    with connect(cfg.database_url) as conn:
        # as_of 결정: --date 명시되면 그것, 아니면 daily_indicators 의 최신 날짜.
        # date.today() 사용 시 cron 실행 시각이 새벽이면 그 날 indicators 가 아직
        # 없어서 evaluate_pivot 의 active 가 0 으로 빠지는 문제를 방지.
        if args.date:
            as_of = _date.fromisoformat(args.date)
        else:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(date) FROM daily_indicators")
                row = cur.fetchone()
            as_of = row[0] if row and row[0] else _date.today()
        pipeline_db_name = PIPELINE_DB_NAME_BY_MODE.get(args.mode, args.mode)
        params = {
            "mode": args.mode,
            "dry_run": args.dry_run,
            "as_of": as_of.isoformat(),
            "limit": args.limit,
            "ticker": getattr(args, "ticker", None),
        }
        with run_tracking(conn, pipeline=pipeline_db_name, mode=args.mode, params=params) as state:
            if args.mode == "weekend":
                result = modes.run_weekend(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
            elif args.mode == "daily-delta":
                result = daily_delta.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
            elif args.mode == "evaluate":
                result = evaluate_pivot.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
            elif args.mode == "entry":
                result = entry_params.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
            elif args.mode == "performance":
                result = performance.run(conn, as_of=as_of)
            elif args.mode == "full-daily":
                result = modes.run_full_daily(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
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
