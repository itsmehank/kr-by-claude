import argparse
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.ohlcv.modes import Mode, run


log = logging.getLogger("kr_pipeline.ohlcv")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.ohlcv")
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--years", type=int, default=2, help="backfill 모드 기간")
    p.add_argument("--window-days", type=int, default=30, help="incremental 윈도우")
    p.add_argument("--limit-tickers", type=int, default=None, help="테스트용 종목 수 제한")
    p.add_argument("--max-workers", type=int, default=3)
    p.add_argument(
        "--exclude-today", action="store_true",
        help="INCREMENTAL 에서 오늘 제외(end=어제). 장중 수동 실행 시 오늘 미확정 부분봉 회피용. "
             "기본 미설정=오늘 포함(마감 후 cron 정상 동작).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)

    with connect(cfg.database_url) as conn:
        stats = run(
            conn,
            Mode(args.mode),
            years=args.years,
            window_days=args.window_days,
            limit_tickers=args.limit_tickers,
            max_workers=args.max_workers,
            exclude_today=args.exclude_today,
        )
        log.info(f"DONE rows_affected={stats.rows_affected} failures={len(stats.failures)}")
        if stats.failures:
            log.warning(f"Failed tickers: {[t for t, _ in stats.failures[:20]]}")
        if stats.warnings:
            for w in stats.warnings:
                log.warning(f"sanity: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
