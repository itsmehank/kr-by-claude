# kr_pipeline/market_context/__main__.py
"""market_context 파이프라인 진입점."""
import argparse
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.market_context.modes import Mode, run


log = logging.getLogger("kr_pipeline.market_context")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.market_context")
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--window-days", type=int, default=30, help="incremental 윈도우")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)

    with connect(cfg.database_url) as conn:
        stats = run(conn, Mode(args.mode), window_days=args.window_days)
        log.info(
            f"DONE market_context mode={args.mode} "
            f"rows_affected={stats.rows_affected} failures={len(stats.failures)} warnings={len(stats.warnings)}"
        )
        if stats.warnings:
            for w in stats.warnings:
                log.warning(f"sanity: {w}")
        if stats.failures:
            log.warning(f"Failed: {[t for t, _ in stats.failures[:20]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
