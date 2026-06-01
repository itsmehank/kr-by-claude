"""Phase 2 (i) build-first 재측정 하니스 (spec §10 / plan Task 11).

⚠ 일회성 *진단* 스크립트 — 프로덕션 경로 아님. DB 미기록, cron/파이프라인 미연결.
   프로덕션 분류는 kr_pipeline/llm_runner/ (weekend.py 등) 경로. 본 스크립트는 (i) 안정화
   효과를 동일입력 N회로 측정한 검증 도구이며, 게이트 통과 후 재실행 의도 없음(아카이브).


실행:
    uv run python scripts/remeasure_phase2i.py --n 10            # 전체 패널
    uv run python scripts/remeasure_phase2i.py --smoke 005850    # 1회 smoke (파이프라인 확인)

입력 고정: build_analysis_zip(conn, symbol) 는 DB 의 *현재* 데이터로 ZIP bytes 생성.
순수 경로 검증이려면 검증 시점 데이터를 고정(데이터 적재 정지 또는 고정 거래일 DB)하고 실행.

판정(spec §10):
  - feature 안정(9~10/10 band-containment) + verdict 안정 → 청정 통과
  - feature 안정 + verdict 흔들 → 트리/precedence 구멍 (Task 7 수정)
  - feature 흔들(밴드 straddle) → 측정 문제 #2 (졸업/(ii))
합격: 5종목 전 가지 기대대로 안정 + gate3_neg(005850) cup_with_handle ≥9/10 + watch + handle_quality ≥9/10.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

from kr_pipeline.common import thresholds

# 가지별 패널 — Step 2 에서 실제 티커로 채움 (FINDINGS 에 선정 근거 기록).
PANEL = {
    # gate3_neg(005850) 완료(watch 10/10, FINDINGS §2) — 재실행 방지로 ticker=None.
    "climax_neg": {"ticker": None, "expect_cls": "ignore", "note": "001820 완료(FINDINGS §5): ignore 10/10, climax_run 10/10 — (A) over-forcing 반증 통과"},
    "gate1_neg":  {"ticker": None, "expect_pattern": "none", "note": "004440 완료(FINDINGS §6): none/ignore 10/10"},
    "positive_nc":   {"ticker": "036570", "expect_cls": "watch", "note": "NC 선행+66%·depth19%·base→신고가 해소(early-stage 후보); 합격=watch≥9/10(불리장이라 entry 불가), late_stage 미해당 확인"},
    "positive_sy":   {"ticker": "002810", "expect_cls": "watch", "note": "삼영무역 선행+63%·depth21%·base→회복; positive hedge"},
    "positive":   {"ticker": None, "expect_cls": "entry|watch", "note": "241770 메카로 inconclusive(late_stage confound, FINDINGS §6) — 재선정으로 대체"},
    "gate2_neg":  {"ticker": None, "expect_pattern": "none",  "note": "명백한 V — 데이터 제약(스크린 유니버스 희소); climax런 V6/10→ignore 가 V-배제 증거"},
    "gate0_neg":  {"ticker": None, "expect_pattern": "none",  "note": "선행<30% — 데이터 제약(minervini-pass 277중 0건; Gate0 구성상 충족)"},
    "gate3_neg":  {"ticker": None, "expect_cls": "watch",     "note": "005850 완료(FINDINGS §2)"},
}

FEATURE_KEYS = ["prior_uptrend_pct", "cup_depth_pct", "handle_depth_pct", "handle_volume_ratio"]
TOL = thresholds.MEASUREMENT_TOLERANCE_PCT  # band-containment 판정용 (calibration-target)


def _build_zip_once(conn, ticker: str) -> str:
    """ZIP 1회 빌드 → temp 파일 경로. N개 호출이 *같은 바이트* 공유(입력 바이트-동일 보장)."""
    from api.services.zip_builder import build_analysis_zip
    zip_bytes = build_analysis_zip(conn, ticker)
    f = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    f.write(zip_bytes)
    f.close()
    return f.name


def _one_call(zip_path: str) -> dict:
    """단일 claude 분석 호출 (실패 시 _ERROR 마커 반환 — 배치 전체 중단 방지)."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude
    try:
        return call_claude(prompt_file="analyze_chart_v3.md", attachments=[zip_path], dry_run=False)
    except Exception as e:
        return {"classification": "_ERROR_", "pattern": None, "measurements": None,
                "risk_flags": [], "_error": str(e)[:200]}


def run_ticker(conn, ticker: str, n: int, workers: int) -> list[dict]:
    """ZIP 1회 빌드 후 n개 claude 호출을 ThreadPool 로 병렬 (호출은 IO-bound subprocess).

    호출 간 공유 상태 = 읽기전용 zip_path 뿐 → thread-safe. call_claude 는 호출마다
    독립 prompt 문자열 + 독립 subprocess. psycopg conn 은 빌드(메인 스레드)에서만 사용.
    """
    zip_path = _build_zip_once(conn, ticker)
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(lambda _: _one_call(zip_path), range(n)))
    finally:
        Path(zip_path).unlink(missing_ok=True)


def diagnose(runs: list[dict], expect: dict) -> dict:
    patterns = Counter(r.get("pattern") for r in runs)
    classes = Counter(r.get("classification") for r in runs)
    feat_stats = {}
    for k in FEATURE_KEYS:
        vals = [r.get("measurements", {}).get(k) for r in runs if isinstance(r.get("measurements"), dict)]
        vals = [v for v in vals if isinstance(v, (int, float))]
        if vals:
            feat_stats[k] = {
                "n": len(vals),
                "mean": round(statistics.mean(vals), 2),
                "stdev": round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0,
                "min": min(vals), "max": max(vals),
                "spread_pct": round(max(vals) - min(vals), 2),
            }
    hq = sum(1 for r in runs if "handle_quality" in (r.get("risk_flags") or []))
    # 핵심 risk_flag 재현율 (climax_run = 과열 인식 재현 여부 — climax_neg 핵심 진단축)
    flag_counts = dict(Counter(
        f for r in runs for f in (r.get("risk_flags") or [])
    ))

    def _m_counter(field):
        return dict(Counter(
            (r.get("measurements") or {}).get(field) for r in runs
            if isinstance(r.get("measurements"), dict)
        ))

    # 회차별 raw — (cup_depth_pct, cup_shape) 짝 진단(#1 지각 vs #3 경계)용.
    runs_raw = []
    for r in runs:
        m = r.get("measurements") or {}
        runs_raw.append({
            "cls": r.get("classification"),
            "pattern": r.get("pattern"),
            "cup_depth_pct": m.get("cup_depth_pct"),
            "cup_shape": m.get("cup_shape"),
            "rejected_gate": m.get("rejected_gate"),
            "handle_status": m.get("handle_status"),
        })

    return {
        "n": len(runs),
        "patterns": dict(patterns),
        "classes": dict(classes),
        "rejected_gate": _m_counter("rejected_gate"),   # 진단 핵심축 (어느 Gate none 탈락)
        "cup_shape": _m_counter("cup_shape"),
        "handle_status": _m_counter("handle_status"),
        "feature_stats": feat_stats,                     # depth band-containment 판정용
        "handle_quality_cited": hq,
        "risk_flag_counts": flag_counts,
        "measurements_null_runs": sum(1 for r in runs if not isinstance(r.get("measurements"), dict)),
        "runs_raw": runs_raw,                            # (depth,shape) 짝 진단용
        "expect": expect,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--workers", type=int, default=5, help="동시 claude 호출 수 (병렬)")
    ap.add_argument("--smoke", metavar="TICKER", help="1회 smoke 실행 (파이프라인 확인, 진단 생략)")
    args = ap.parse_args()

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
                "pattern": result.get("pattern"),
                "measurements": result.get("measurements"),
                "risk_flags": result.get("risk_flags"),
            }, ensure_ascii=False, indent=2))
            return

        # 티커-간 병렬: ZIP 은 종목당 1회 직렬 빌드(psycopg conn thread-unsafe), 모든
        # (티커×N) claude 호출을 단일 전역 ThreadPool 로 flatten → 동시 호출 ≤ --workers 보장.
        active = [(k, cfg) for k, cfg in PANEL.items() if cfg.get("ticker")]
        for k, cfg in active:
            print(f"[skip] {k}: 미선정" if not cfg.get("ticker") else f"[build] {k} ({cfg['ticker']})", flush=True)
        zips = {k: _build_zip_once(conn, cfg["ticker"]) for k, cfg in active}
        tasks = [k for k, cfg in active for _ in range(args.n)]
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
        for k in report:
            print(f"[done] {k}: classes={report[k]['classes']}", flush=True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
