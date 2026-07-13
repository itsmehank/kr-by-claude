"""수익성·강건성 백테스트 CLI. 읽기전용 분석 + 전용 테이블 적재.

  python -m kr_pipeline.backtest.profitability_cli sample [--sample=a|b]
  python -m kr_pipeline.backtest.profitability_cli backfill [--sample=a|b] \
      [--start=YYYY-MM-DD] [--end=YYYY-MM-DD] [--dry-run]   # 멱등 백필(resume 가능)
  python -m kr_pipeline.backtest.profitability_cli analyze   # 국면별 집계 + §7 판정(표본 A)
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.db.connection import connect
from kr_pipeline.backtest.sample import build_frame, sample_composition, DEFAULT_SEED
from kr_pipeline.backtest.backfill import run_backtest_backfill
from kr_pipeline.backtest.profitability_run import run_analysis
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B, FROZEN_SEED_B

START, END = date(2021, 1, 1), date(2024, 12, 31)          # 분류 윈도(주간)
PX_START, PX_END = date(2020, 7, 1), date(2025, 6, 30)      # 가격(선행 SMA + forward 청산)

MAX_SAMPLE = 100   # 백필 허용 표본 상한 — 동결 표본 외 어떤 목록도 거부


def _sample(conn, kind: str = "a") -> list[str]:
    # 사전등록 동결 표본 고정(라이브 build_frame 재계산 금지 — 지표 드리프트로
    # 표본이 흔들렸던 §2 위반 복구). cf. frozen_sample.py / frozen_sample_b.py
    if kind == "a":
        return list(FROZEN_SAMPLE)
    if kind == "b":
        return list(FROZEN_SAMPLE_B)
    raise SystemExit(f"unknown --sample: {kind!r} (a|b)")


def cmd_sample(conn, kind: str) -> int:
    sample = _sample(conn, kind)
    comp = sample_composition(conn, sample)
    frame = build_frame(conn, START, END)       # 참고용 라이브 frame 크기만 표시
    seed = FROZEN_SEED_B if kind == "b" else DEFAULT_SEED
    print(json.dumps({"kind": kind, "seed": seed, "frame_size_live": len(frame),
                      "frozen": True, "sample": sample, "composition": comp},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_backfill(conn, dry_run: bool, kind: str, start: date, end: date) -> int:
    sample = _sample(conn, kind)
    if len(set(sample)) > MAX_SAMPLE:
        raise SystemExit(
            f"sample guard: {len(set(sample))} tickers > {MAX_SAMPLE} — "
            "동결 표본만 허용(라이브 재추첨 의심)")
    r = run_backtest_backfill(conn, start=start, end=end, tickers=sample, dry_run=dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0


def cmd_analyze(conn) -> int:
    sample = _sample(conn)
    out = run_analysis(conn, sample, PX_START, PX_END, watch_start=START, watch_end=END)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _flag(name: str, default: str) -> str:
    prefix = f"--{name}="
    for a in sys.argv[2:]:
        if a.startswith(prefix):
            return a.split("=", 1)[1]
    return default


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sample"
    dry_run = "--dry-run" in sys.argv
    kind = _flag("sample", "a")
    start = date.fromisoformat(_flag("start", str(START)))
    end = date.fromisoformat(_flag("end", str(END)))
    if cmd == "analyze" and kind != "a":
        raise SystemExit(
            "analyze 는 표본 A 전용 — --sample=b 는 아직 미지원(백필 완료 후 별도 분석)")
    with connect() as conn:
        if cmd == "sample":
            return cmd_sample(conn, kind)
        if cmd == "backfill":
            return cmd_backfill(conn, dry_run, kind, start, end)
        if cmd == "analyze":
            return cmd_analyze(conn)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
