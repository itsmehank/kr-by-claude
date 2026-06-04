"""CLI: python -m kr_pipeline.pipeline --chain=daily|weekly [--limit-tickers N]"""
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
    args = p.parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    with connect(cfg.database_url) as conn:
        if args.chain == "daily":
            result = chains.run_daily_chain(conn, limit_tickers=args.limit_tickers)
        else:
            result = chains.run_weekly_chain(conn, limit_tickers=args.limit_tickers)
    log.info("DONE chain=%s: %s", args.chain, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
