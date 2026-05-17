"""CLI 엔트리."""
import argparse
import json
import logging
import sys
from datetime import date as _date

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner import (
    weekend, daily_delta, evaluate_pivot, entry_params, performance,
)
from kr_pipeline.llm_runner import modes


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
    as_of = _date.fromisoformat(args.date) if args.date else _date.today()

    with connect(cfg.database_url) as conn:
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

    logging.getLogger("kr_pipeline.llm_runner").info(
        "DONE %s: %s", args.mode, json.dumps(result)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
