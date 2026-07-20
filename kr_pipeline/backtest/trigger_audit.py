"""하락·조정기 진입 33건 LLM 트리거 확인 감사 — 사전등록 2026-07-02 §1.

시뮬 트레이드(결정론)를 재현해 down-phase 진입을 추출하고, 각 진입일에 대해
production 트리거 확인(5b)을 과거 시점으로 재생한다. prior_analysis 는
backtest_classification 의 해당 watch 행을 주입(look-ahead 차단, prereg §1).

격리: production trigger_evaluation_log 에 쓰지 않는다 — 결과는 JSON 파일.
멱등: 파일에 있는 (ticker, entry_date) skip. 사용량 한도 시 재실행 = resume.

  python -m kr_pipeline.backtest.trigger_audit            # 실행(resume)
  python -m kr_pipeline.backtest.trigger_audit --dry-run  # mock, 파일 미기록
  python -m kr_pipeline.backtest.trigger_audit --dump-payload  # 1건 페이로드 덤프만
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path

from psycopg import Connection

from kr_pipeline.backtest import phases as ph
from kr_pipeline.backtest.backfill import BT_TABLE
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.profitability_run import DOWN_PHASES, _market_of
from kr_pipeline.backtest.trigger_sim import (
    load_watchlist, load_daily_series, classify_rows, simulate,
)
from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError

log = logging.getLogger("kr_pipeline.backtest.trigger_audit")

AUDIT_PATH = Path("data/backtest/trigger_audit_20260702.json")
START, END = date(2021, 1, 1), date(2024, 12, 31)          # 분류 윈도(주간)
PX_START, PX_END = date(2020, 7, 1), date(2025, 6, 30)      # profitability_cli 동일


def collect_down_trades(conn: Connection, tickers: list[str] | None = None,
                        max_chase_pct: float | None = None) -> list[dict]:
    """profitability_run 과 동일 경로로 트레이드 재현(결정론) → down-phase 필터.

    run_analysis 는 pivot_sat 을 버리므로 simulate 를 직접 호출해 보존한다.
    max_chase_pct 지정 시 보정 후(5% 추격 룰) 트레이드 기준 — 표본 B prereg P2 의
    의도적 차이(A 감사는 1차 비보정 기준이었음).
    """
    tickers = list(tickers) if tickers is not None else list(FROZEN_SAMPLE)
    pmaps: dict[str, list] = {}
    out: list[dict] = []
    for ticker in tickers:
        market = _market_of(conn, ticker)
        code = ph.INDEX_OF.get(market, "1001")
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
        wr = load_watchlist(conn, ticker, START, END, table=BT_TABLE)
        bars = load_daily_series(conn, ticker, PX_START, PX_END)
        cls = classify_rows(wr)
        prod_trades, _ = simulate(
            ticker, cls["production"], bars, mode="production",
            **({"max_chase_pct": max_chase_pct} if max_chase_pct is not None else {}))
        for t in prod_trades:
            phase = ph.phase_at(pmaps[code], t.entry_date)
            if phase in DOWN_PHASES:
                out.append({
                    "ticker": t.ticker, "market": market,
                    "entry_date": t.entry_date, "phase": phase,
                    "pivot_sat": t.pivot_sat, "pivot_price": t.pivot_price,
                    "watch_reason": t.watch_reason,
                })
    return out


def prior_row_for(conn: Connection, symbol: str, sat: date) -> dict:
    """그 트레이드를 만든 backtest_classification watch 행 → build_for_5b 주입 형태.

    classified_at 주입값 = analyzed_for_date(토요일) — 백필 실행시각(2026)은 무의미
    (prereg §1). days_since_classification 이 진입일 - 분류토요일이 되게 한다.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT classification, pattern, pivot_price, pivot_basis,
                   base_high, base_low, base_depth_pct, risk_flags, reasoning,
                   watch_reason
              FROM {BT_TABLE}
             WHERE symbol = %s AND analyzed_for_date = %s
            """,
            (symbol, sat),
        )
        r = cur.fetchone()
    if r is None:
        raise ValueError(f"backtest watch row not found: {symbol} {sat}")
    return {
        "classified_at": datetime.combine(sat, dt_time.min),
        "classification": r[0], "pattern": r[1],
        "pivot_price": float(r[2]) if r[2] is not None else None,
        "pivot_basis": r[3],
        "base_high": float(r[4]) if r[4] is not None else None,
        "base_low": float(r[5]) if r[5] is not None else None,
        "base_depth_pct": float(r[6]) if r[6] is not None else None,
        "risk_flags": r[7], "reasoning": r[8], "watch_reason": r[9],
    }


def _load_done(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"prereg": "2026-07-02-backtest-refinement-prereg.md §1", "results": []}


def _key(rec: dict) -> tuple:
    return (rec["ticker"], str(rec["entry_date"]))


def run_audit(conn: Connection, *, dry_run: bool = False,
              path: Path = AUDIT_PATH, tickers: list[str] | None = None,
              max_chase_pct: float | None = None) -> dict:
    trades = collect_down_trades(conn, tickers=tickers, max_chase_pct=max_chase_pct)
    doc = _load_done(path)
    done = {_key(r) for r in doc["results"]}
    agg = {"total": len(trades), "skipped_existing": 0, "processed": 0,
           "failures": 0, "aborted_usage_limit": False}

    for t in trades:
        if _key({"ticker": t["ticker"], "entry_date": t["entry_date"]}) in done:
            agg["skipped_existing"] += 1
            continue
        prior = prior_row_for(conn, t["ticker"], t["pivot_sat"])
        payload = build_for_5b(
            conn, t["ticker"], trigger_type="breakout_from_watch",
            as_of=t["entry_date"], prior_row=prior,
        )
        llm_io: dict = {}
        try:
            result = call_claude(
                prompt_file="evaluate_pivot_trigger_v1.md",
                attachments=[], payload_inline=payload, dry_run=dry_run,
                meta_out=llm_io,
            )
        except UsageLimitError:
            log.warning("usage limit — clean abort, %d processed", agg["processed"])
            agg["aborted_usage_limit"] = True
            break
        except Exception as e:  # 단건 실패 기록 후 계속 (33건 소규모)
            log.warning("audit call failed %s %s: %s", t["ticker"], t["entry_date"], e)
            agg["failures"] += 1
            continue
        if dry_run:
            agg["processed"] += 1
            continue
        doc["results"].append({
            "ticker": t["ticker"], "entry_date": str(t["entry_date"]),
            "phase": t["phase"], "pivot_sat": str(t["pivot_sat"]),
            "watch_reason": t["watch_reason"],
            "decision": result.get("decision"),
            "confidence": result.get("confidence"),
            "reasoning": result.get("reasoning"),
            "abort_reason": result.get("abort_reason"),
            "llm_model": llm_io.get("model"),
            "input_tokens": llm_io.get("input_tokens"),
            "output_tokens": llm_io.get("output_tokens"),
        })
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        agg["processed"] += 1
        log.info("audit %s %s → %s (%d/%d)", t["ticker"], t["entry_date"],
                 result.get("decision"), len(doc["results"]), len(trades))
    return agg


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from kr_pipeline.db.connection import connect
    dry_run = "--dry-run" in sys.argv
    kind = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--sample=")), "a")
    tickers = None
    path = AUDIT_PATH
    max_chase = None
    if kind == "b":
        from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
        tickers = list(FROZEN_SAMPLE_B)
        path = Path("data/backtest/trigger_audit_sample_b_20260721.json")
        max_chase = 5.0        # prereg P2: 보정 후(5% 추격) 트레이드 기준
    elif kind != "a":
        raise SystemExit(f"unknown --sample: {kind!r} (a|b)")
    with connect() as conn:
        if "--dump-payload" in sys.argv:
            trades = collect_down_trades(conn)
            t = trades[0]
            prior = prior_row_for(conn, t["ticker"], t["pivot_sat"])
            payload = build_for_5b(conn, t["ticker"],
                                   trigger_type="breakout_from_watch",
                                   as_of=t["entry_date"], prior_row=prior)
            print(json.dumps({"n_down_trades": len(trades), "sample_trade": {
                "ticker": t["ticker"], "entry_date": str(t["entry_date"]),
                "phase": t["phase"]}, "payload": payload},
                ensure_ascii=False, indent=2, default=str))
            return 0
        agg = run_audit(conn, dry_run=dry_run, path=path,
                        tickers=tickers, max_chase_pct=max_chase)
        print(json.dumps(agg, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
