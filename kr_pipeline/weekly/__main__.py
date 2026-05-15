"""weekly 파이프라인 진입점."""
import argparse
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.weekly.modes import Mode, run


log = logging.getLogger("kr_pipeline.weekly")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.weekly")
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--window-weeks", type=int, default=4, help="incremental 윈도우 (주)")
    p.add_argument("--limit-tickers", type=int, default=None, help="테스트용 종목 수 제한")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)

    with connect(cfg.database_url) as conn:
        stats = run(
            conn,
            Mode(args.mode),
            window_weeks=args.window_weeks,
            limit_tickers=args.limit_tickers,
        )
        log.info(
            f"DONE weekly rows_affected={stats.rows_affected} "
            f"failures={len(stats.failures)} warnings={len(stats.warnings)}"
        )
        if stats.warnings:
            for w in stats.warnings:
                log.warning(f"sanity: {w}")
        if stats.failures:
            log.warning(f"Failed tickers: {[t for t, _ in stats.failures[:20]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
