# kr_pipeline/corporate_actions/__main__.py
"""corporate_actions 파이프라인 진입점."""
import argparse
import logging
import sys

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.corporate_actions.modes import Mode, run


log = logging.getLogger("kr_pipeline.corporate_actions")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.corporate_actions")
    p.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    p.add_argument("--years", type=int, default=5, help="backfill 모드 기간 (년)")
    p.add_argument("--window-days", type=int, default=7, help="incremental 모드 윈도우 (일)")
    p.add_argument("--limit-tickers", type=int, default=None, help="테스트용 종목 수 제한")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)

    if not cfg.dart_api_key:
        log.error("DART_API_KEY 환경변수가 설정되지 않았습니다. .env 에 추가하세요.")
        return 1

    with connect(cfg.database_url) as conn:
        stats = run(
            conn, Mode(args.mode), cfg.dart_api_key,
            years=args.years, window_days=args.window_days, limit_tickers=args.limit_tickers,
        )
        log.info(
            f"DONE corporate_actions mode={args.mode} "
            f"rows_affected={stats.rows_affected} failures={len(stats.failures)} warnings={len(stats.warnings)}"
        )
        if stats.warnings:
            for w in stats.warnings:
                log.warning(f"sanity: {w}")
        if stats.failures:
            log.warning(f"Failed tickers: {[t for t, _ in stats.failures[:20]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
