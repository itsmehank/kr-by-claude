# kr_pipeline/indicators/__main__.py
"""indicators 파이프라인 진입점."""
import argparse
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.indicators.modes import Mode, Target, run_daily, run_weekly


log = logging.getLogger("kr_pipeline.indicators")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.indicators")
    p.add_argument("--target", required=True, choices=[t.value for t in Target])
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--window-days", type=int, default=30, help="일봉 incremental 윈도우")
    p.add_argument("--window-weeks", type=int, default=4, help="주봉 incremental 윈도우")
    p.add_argument("--limit-tickers", type=int, default=None, help="테스트용 종목 수 제한")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)

    target = Target(args.target)
    mode = Mode(args.mode)

    with connect(cfg.database_url) as conn:
        if target == Target.DAILY:
            stats = run_daily(conn, mode, window=args.window_days, limit_tickers=args.limit_tickers)
        else:
            stats = run_weekly(conn, mode, window=args.window_weeks, limit_tickers=args.limit_tickers)

        log.info(
            f"DONE indicators target={target.value} mode={mode.value} "
            f"rows_affected={stats.rows_affected} failures={len(stats.failures)} warnings={len(stats.warnings)}"
        )
        if stats.warnings:
            for w in stats.warnings:
                log.warning(f"sanity: {w}")
        if stats.failures:
            log.warning(f"Failed tickers: {[t for t, _ in stats.failures[:20]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
