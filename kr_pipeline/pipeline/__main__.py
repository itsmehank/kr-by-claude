"""CLI: python -m kr_pipeline.pipeline --chain=daily|weekly [--limit-tickers N] [--no-drift] [--no-sweep]"""
import argparse
import logging
import sys

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.pipeline import chains

log = logging.getLogger("kr_pipeline.pipeline")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--chain", required=True, choices=["daily", "weekly"])
    p.add_argument("--limit-tickers", type=int, default=None)
    p.add_argument("--no-drift", action="store_true", help="daily 체인 드리프트 감지 건너뛰기")
    p.add_argument("--no-sweep", action="store_true", help="weekly 체인 전체스윕 건너뛰기")
    args = p.parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    with connect(cfg.database_url) as conn:
        if args.chain == "daily":
            result = chains.run_daily_chain(conn, drift_check=not args.no_drift,
                                            limit_tickers=args.limit_tickers)
        else:
            result = chains.run_weekly_chain(conn, limit_tickers=args.limit_tickers,
                                             full_sweep=not args.no_sweep)
    log.info("DONE chain=%s: %s", args.chain, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
