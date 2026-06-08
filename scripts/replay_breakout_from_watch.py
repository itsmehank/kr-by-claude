"""breakout_from_watch 관문 2-A 재측정 하니스 (analyze_chart_v3 watch_reason 안정성).

⚠ 일회성 *검증* 스크립트 — 프로덕션 경로 아님. DB 미기록, 실제 claude 호출.
`scripts/remeasure_phase2i.py` 패턴 재사용 + 신규 `watch_reason` 분포 집계.

실행:
    uv run python scripts/replay_breakout_from_watch.py --smoke 005850     # 1회 smoke
    uv run python scripts/replay_breakout_from_watch.py --n 10             # 패널 N=10

판정(관문 2-A):
  - 005850 → watch ≥9/10 (전이 없음)
  - 001820 → ignore ≥9/10 + climax_run flag ≥9/10
  - 066620(handle 미형성 cup) → watch + watch_reason=base_forming ≥9/10
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

# 가지별 패널 — 관문 2-A 필수 케이스.
PANEL = {
    "watch_keep_005850":  {"ticker": "005850", "expect_cls": "watch",
                           "note": "gate3 cup 경계 — watch 유지 회귀(분류 안정)"},
    "climax_ignore_001820": {"ticker": "001820", "expect_cls": "ignore",
                             "note": "climax → ignore 유지 + climax_run flag"},
    "handle_notformed_066620": {"ticker": "066620", "expect_cls": "watch",
                                "expect_watch_reason": "base_forming",
                                "note": "cup 완성·handle 미형성 → base_forming(actionable 아님)"},
    "handle_notformed_002810": {"ticker": "002810", "expect_cls": "watch",
                                "expect_watch_reason": "base_forming",
                                "note": "삼영무역 cup·handle 미형성 — 보강 케이스"},
}


def _build_zip_once(conn, ticker: str) -> str:
    from api.services.zip_builder import build_analysis_zip
    zip_bytes = build_analysis_zip(conn, ticker)
    f = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    f.write(zip_bytes)
    f.close()
    return f.name


PROMPT_FILE = "analyze_chart_v3.md"  # --prompt 로 덮어씀 (base vs 내 버전 비교용)


def _one_call(zip_path: str) -> dict:
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude
    try:
        return call_claude(prompt_file=PROMPT_FILE, attachments=[zip_path], dry_run=False)
    except Exception as e:  # noqa: BLE001
        return {"_ERROR": str(e)}


def diagnose(runs: list[dict], expect: dict) -> dict:
    ok = [r for r in runs if "_ERROR" not in r]
    return {
        "n": len(runs),
        "errors": sum(1 for r in runs if "_ERROR" in r),
        "classes": dict(Counter(r.get("classification") for r in ok)),
        "watch_reason": dict(Counter(r.get("watch_reason") for r in ok)),
        "patterns": dict(Counter(r.get("pattern") for r in ok)),
        "handle_status": dict(Counter(
            (r.get("measurements") or {}).get("handle_status") for r in ok
            if isinstance(r.get("measurements"), dict)
        )),
        "climax_run_flag": sum(1 for r in ok if "climax_run" in (r.get("risk_flags") or [])),
        "expect": expect,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--smoke", metavar="TICKER")
    ap.add_argument("--only", metavar="KEY", help="PANEL 의 특정 key 만 실행")
    ap.add_argument("--prompt", metavar="FILE", help="prompts/ 하위 분류 프롬프트 파일명 (base 비교용)")
    args = ap.parse_args()
    if args.prompt:
        global PROMPT_FILE
        PROMPT_FILE = args.prompt

    conn = psycopg.connect(os.environ["DATABASE_URL"])
    try:
        if args.smoke:
            zip_path = _build_zip_once(conn, args.smoke)
            try:
                result = _one_call(zip_path)
            finally:
                Path(zip_path).unlink(missing_ok=True)
            print(json.dumps({
                "smoke": args.smoke,
                "classification": result.get("classification"),
                "watch_reason": result.get("watch_reason"),
                "pattern": result.get("pattern"),
                "handle_status": (result.get("measurements") or {}).get("handle_status"),
                "risk_flags": result.get("risk_flags"),
                "_error": result.get("_ERROR"),
            }, ensure_ascii=False, indent=2))
            return

        active = [(k, cfg) for k, cfg in PANEL.items()
                  if cfg.get("ticker") and (not args.only or k == args.only)]
        zips = {k: _build_zip_once(conn, cfg["ticker"]) for k, cfg in active}
        tasks = [k for k, _ in active for _ in range(args.n)]
        print(f"[parallel] {len(active)}종목 × N={args.n} = {len(tasks)}호출, workers={args.workers}", flush=True)
        try:
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                paired = list(ex.map(lambda k: (k, _one_call(zips[k])), tasks))
        finally:
            for p in zips.values():
                Path(p).unlink(missing_ok=True)
        by_key: dict[str, list] = {}
        for k, r in paired:
            by_key.setdefault(k, []).append(r)
        cfg_by_key = dict(active)
        report = {k: diagnose(by_key[k], cfg_by_key[k]) for k in by_key}
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
