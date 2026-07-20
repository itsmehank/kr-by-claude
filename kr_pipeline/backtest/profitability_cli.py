"""수익성·강건성 백테스트 CLI. 읽기전용 분석 + 전용 테이블 적재.

  python -m kr_pipeline.backtest.profitability_cli sample [--sample=a|b|c]
  python -m kr_pipeline.backtest.profitability_cli backfill [--sample=a|b|c] \
      [--start=YYYY-MM-DD] [--end=YYYY-MM-DD] [--dry-run]   # 멱등 백필(resume 가능)
  python -m kr_pipeline.backtest.profitability_cli analyze \
      [--sample=a|b|c] [--watch-start=…] [--watch-end=…] [--px-start=…] [--px-end=…]

--sample=b (표본 B, prereg 2026-07-21-sample-b-analysis): 기본 2021 윈도로 실행,
EXCLUDED_CELLS(#50 결함 셀) 자동 제외.
--sample=c (독립 검증 구간 2017-H2~2020, 이슈 #52): 동결 전에는 거부되며, 동결 후에도
기본 2021 윈도 오발사를 막기 위해 backfill 은 --start/--end, analyze 는 watch/px
윈도 4개를 전부 명시해야 한다.
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
    # 표본이 흔들렸던 §2 위반 복구). cf. frozen_sample.py / frozen_sample_b.py /
    # frozen_sample_c.py
    if kind == "a":
        return list(FROZEN_SAMPLE)
    if kind == "b":
        return list(FROZEN_SAMPLE_B)
    if kind == "c":
        import kr_pipeline.backtest.frozen_sample_c as fc
        if not fc.FROZEN_SAMPLE_C:
            raise SystemExit(
                "표본 C 미동결(pending_draw) — 사전등록 "
                "(2026-07-21-independent-window-backtest-prereg.md) 승인 후 "
                "scripts/draw_sample_c.py --draw 1회 실행으로 동결하라")
        return list(fc.FROZEN_SAMPLE_C)
    raise SystemExit(f"unknown --sample: {kind!r} (a|b|c)")


def cmd_sample(conn, kind: str) -> int:
    sample = _sample(conn, kind)
    comp = sample_composition(conn, sample)
    frame = build_frame(conn, START, END)       # 참고용 라이브 frame 크기만 표시
    if kind == "b":
        seed = FROZEN_SEED_B
    elif kind == "c":
        from kr_pipeline.backtest.frozen_sample_c import FROZEN_SEED_C
        seed = FROZEN_SEED_C
    else:
        seed = DEFAULT_SEED
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


def cmd_analyze(conn, kind: str = "a",
                watch_start: date = START, watch_end: date = END,
                px_start: date = PX_START, px_end: date = PX_END) -> int:
    """기본(인자 없음) = 표본 A · 2021~2024 윈도 — 현행 동작 불변 (이슈 #52).

    kind="b": EXCLUDED_CELLS(#50 결함 셀) 를 분류점 집계에서 제외 (prereg §1)."""
    sample = _sample(conn, kind)
    exclude = frozenset()
    if kind == "b":
        from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_CELLS
        exclude = frozenset((s, date.fromisoformat(d)) for s, d in EXCLUDED_CELLS)
    out = run_analysis(conn, sample, px_start, px_end,
                       watch_start=watch_start, watch_end=watch_end, exclude=exclude)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _flag(name: str, default: str) -> str:
    prefix = f"--{name}="
    for a in sys.argv[2:]:
        if a.startswith(prefix):
            return a.split("=", 1)[1]
    return default


def _flag_present(name: str) -> bool:
    return any(a.startswith(f"--{name}=") for a in sys.argv[2:])


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sample"
    dry_run = "--dry-run" in sys.argv
    kind = _flag("sample", "a")
    start = date.fromisoformat(_flag("start", str(START)))
    end = date.fromisoformat(_flag("end", str(END)))
    # 표본 C 기간 명시 강제 — 기본 2021 윈도로 독립 구간 아닌 기간을 돌리는 오발사 방지
    # (이슈 #52 prereg 실행 계획의 리터럴 커맨드와 짝)
    if cmd == "backfill" and kind == "c" and not (
            _flag_present("start") and _flag_present("end")):
        raise SystemExit(
            "--sample=c backfill 은 --start/--end 명시 필수 — 기본 2021 윈도 오발사 방지 "
            "(독립 구간: --start=2017-07-01 --end=2020-12-31)")
    if cmd == "analyze" and kind == "c" and not all(
            _flag_present(n) for n in ("watch-start", "watch-end",
                                       "px-start", "px-end")):
        raise SystemExit(
            "--sample=c analyze 는 --watch-start/--watch-end/--px-start/--px-end "
            "전부 명시 필수 — 기본 2021 윈도 오발사 방지")
    watch_start = date.fromisoformat(_flag("watch-start", str(START)))
    watch_end = date.fromisoformat(_flag("watch-end", str(END)))
    px_start = date.fromisoformat(_flag("px-start", str(PX_START)))
    px_end = date.fromisoformat(_flag("px-end", str(PX_END)))
    with connect() as conn:
        if cmd == "sample":
            return cmd_sample(conn, kind)
        if cmd == "backfill":
            return cmd_backfill(conn, dry_run, kind, start, end)
        if cmd == "analyze":
            return cmd_analyze(conn, kind, watch_start, watch_end, px_start, px_end)
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
