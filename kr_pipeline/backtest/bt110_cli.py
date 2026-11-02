"""(#242) 루프·워치독용 CLI — backfill_control 을 JSON 한 줄로 읽고(status), 커밋 핀을 기록·대조(pin)한다.

  uv run python -m kr_pipeline.backtest.bt110_cli status          → {"enabled":…, "tripwire":[…], "progress":{…}, …}
  uv run python -m kr_pipeline.backtest.bt110_cli status --kv     → enabled=1 complete=0 target=19734 done=0 tripwire=0 models=1
  uv run python -m kr_pipeline.backtest.bt110_cli pin --head SHA  → {"pin":"pinned"|"ok"|"mismatch:<sha>"}
쉘 루프는 python -c 대신 이 모듈을 호출해 SQL 을 쉘에 두지 않는다(스냅샷·기준선 로직 단일화).
"""
from __future__ import annotations

import argparse
import sys

from kr_pipeline.backtest import bt110
from kr_pipeline.db.connection import connect


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("--kv", action="store_true", help="쉘 파싱용 key=value 한 줄")
    p = sub.add_parser("pin")
    p.add_argument("--head", required=True)
    a = ap.parse_args(argv)
    with connect() as conn:
        if a.cmd == "status":
            d = bt110.status(conn)
            if a.kv:
                pr = d.get("progress") or {}
                print(" ".join([
                    f"enabled={int(bool(d['enabled']))}", f"complete={int(bool(pr.get('complete')))}",
                    f"target={pr.get('target', 0)}", f"done={pr.get('done', 0)}",
                    f"tripwire={len(d.get('tripwire') or [])}", f"models={len(pr.get('models_in_slice') or {})}",
                    f"pinned={d.get('pinned_commit') or '-'}",
                ]))
            else:
                print(bt110.dumps(d))
        elif a.cmd == "pin":
            print(bt110.dumps({"pin": bt110.check_or_pin_commit(conn, a.head)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
