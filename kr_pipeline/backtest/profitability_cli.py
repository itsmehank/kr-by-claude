"""수익성·강건성 백테스트 CLI. 읽기전용 분석 + 전용 테이블 적재.

  python -m kr_pipeline.backtest.profitability_cli sample    # 100종목 동결 출력
  python -m kr_pipeline.backtest.profitability_cli backfill   # 멱등 백필(resume 가능)
  python -m kr_pipeline.backtest.profitability_cli analyze    # 국면별 집계 + §7 판정
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.db.connection import connect
from kr_pipeline.backtest.sample import build_frame, draw_sample, sample_composition, DEFAULT_SEED
from kr_pipeline.backtest.backfill import run_backtest_backfill
from kr_pipeline.backtest.profitability_run import run_analysis
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE

START, END = date(2021, 1, 1), date(2024, 12, 31)          # 분류 윈도(주간)
PX_START, PX_END = date(2020, 7, 1), date(2025, 6, 30)      # 가격(선행 SMA + forward 청산)


def _sample(conn) -> list[str]:
    # 사전등록 동결 100종목 고정(라이브 build_frame 재계산 금지 — 지표 드리프트로
    # 표본이 흔들렸던 §2 위반 복구). cf. frozen_sample.py
    return list(FROZEN_SAMPLE)


def cmd_sample(conn) -> int:
    sample = _sample(conn)                      # 동결 100
    comp = sample_composition(conn, sample)
    frame = build_frame(conn, START, END)       # 참고용 라이브 frame 크기만 표시
    print(json.dumps({"seed": DEFAULT_SEED, "frame_size_live": len(frame),
                      "frozen": True, "sample": sample, "composition": comp},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_backfill(conn, dry_run: bool) -> int:
    sample = _sample(conn)
    r = run_backtest_backfill(conn, start=START, end=END, tickers=sample, dry_run=dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


def cmd_analyze(conn) -> int:
    sample = _sample(conn)
    out = run_analysis(conn, sample, PX_START, PX_END, watch_start=START, watch_end=END)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sample"
    dry_run = "--dry-run" in sys.argv
    with connect() as conn:
        if cmd == "sample":
            return cmd_sample(conn)
        if cmd == "backfill":
            return cmd_backfill(conn, dry_run)
        if cmd == "analyze":
            return cmd_analyze(conn)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
