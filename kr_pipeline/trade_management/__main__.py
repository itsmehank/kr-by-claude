# kr_pipeline/trade_management/__main__.py
"""(#47) 포지션 관리 진입점 — 수동 기록 CLI + 일일 손절 평가 러너.

사용 예:
  python -m kr_pipeline.trade_management --mode=daily-eval [--as-of 2026-07-22]
  python -m kr_pipeline.trade_management --add 005930 --price 71000 [--date ...] [--qty 10]
  python -m kr_pipeline.trade_management --close-id 3 [--reason "target hit"]
  python -m kr_pipeline.trade_management --list
"""
import argparse
import json
import logging
import sys
from datetime import date

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.trade_management.runner import run_daily_eval
from kr_pipeline.trade_management.store import (
    close_position, get_open_positions, open_position,
)

log = logging.getLogger("kr_pipeline.trade_management")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.trade_management")
    p.add_argument("--mode", choices=["daily-eval"], help="러너 모드")
    p.add_argument("--as-of", type=date.fromisoformat, default=None)
    p.add_argument("--add", metavar="SYMBOL", help="포지션 수동 개설")
    p.add_argument("--price", type=float, help="--add 평균매입가")
    p.add_argument("--date", dest="entry_date", type=date.fromisoformat,
                   default=None, help="--add 매수일 (기본 오늘)")
    p.add_argument("--qty", type=int, default=None)
    p.add_argument("--note", default=None)
    p.add_argument("--close-id", type=int, help="포지션 종료 (id)")
    p.add_argument("--reason", default=None, help="--close-id 사유")
    p.add_argument("--list", action="store_true", help="open 포지션 목록")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)

    with connect(cfg.database_url) as conn:
        if args.mode == "daily-eval":
            with run_tracking(conn, pipeline="trade_management", mode="daily-eval",
                              params={"as_of": str(args.as_of) if args.as_of else None}) as state:
                r = run_daily_eval(conn, as_of=args.as_of)
                state["rows_affected"] = r["evaluated"]
                if r["skipped"]:
                    state["warnings"].append(
                        f"skipped {len(r['skipped'])}: "
                        + ", ".join(f"{s['symbol']}({s['reason']})" for s in r["skipped"])
                    )
                log.info("daily-eval %s: evaluated=%d triggered=%d skipped=%d",
                         r["as_of"], r["evaluated"], r["triggered"], len(r["skipped"]))
        elif args.add:
            if not args.price:
                log.error("--add 는 --price 필수")
                return 1
            pid = open_position(
                conn, symbol=args.add, entry_date=args.entry_date or date.today(),
                entry_price=args.price, quantity=args.qty, note=args.note,
            )
            log.info("opened position id=%d %s @ %s", pid, args.add, args.price)
        elif args.close_id:
            try:
                close_position(conn, position_id=args.close_id, reason=args.reason)
            except ValueError as e:
                log.error("%s", e)
                return 1
            log.info("closed position id=%d", args.close_id)
        elif args.list:
            print(json.dumps(get_open_positions(conn), default=str,
                             ensure_ascii=False, indent=2))
        else:
            log.error("동작 지정 필요: --mode=daily-eval | --add | --close-id | --list")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
