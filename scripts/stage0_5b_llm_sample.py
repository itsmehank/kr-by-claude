"""0단계 잔여 공백 — 5b LLM 소비층 소표본 실측 (#37 computed_gates 순종 검증).

층① 재생 산출물(data/verification/2026-07-17-stage0/5b_gate_replay.json)의 705개
트리거 컨텍스트에서 층화 표본 30건(breakout 전수 4 + bfw 8 + invalidation 8 +
promotion 10, 유형 내 균등 간격 — 무작위성 없이 결정론 추출)을 뽑아 실제 LLM 을
호출하고, 프롬프트 규약에서 **사전 도출한 판독 기준**으로 위반을 계수한다.

판독 기준 (evaluate_pivot_trigger_v1.md 에서 도출 — 실행 전 고정):
  H1  promotion / invalidation 트리거에서 decision == go_now → 위반 (§3.2·§3.3
      'go_now 발생 안 함' 명문).
  H2  breakout 에서 go_now 인데 §3.1 게이트 5개(price_above_pivot·volume_band
      =="pass"·close_upper_third·spread_wide_loose==false·no_dist_3d) 중 하나라도
      미충족(false 또는 null) → 위반.
  H3  breakout_from_watch 에서 go_now 인데 위 5개 + 회복 게이트 2개
      (market_recovery_ok·tt_recovery_ok) 미충족 → 위반 (§3.5).
  H4  decision ∉ {go_now, wait, abort} 또는 abort 인데 abort_reason 이 §3.4
      카탈로그 밖 → 위반.
  S1  (수동 판독) reasoning 이 computed_gates 값과 모순되는 재계산 수치를 주장
      → 리포트에 개별 기록.

결과는 JSON 저장만 — production 테이블에 저장하지 않는다 (관측 전용).
UsageLimitError 발생 시 그 지점까지 저장하고 클린 중단.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date, datetime, time as dt_time
from pathlib import Path

from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError

log = logging.getLogger("stage0.5b_llm_sample")

REPLAY_PATH = Path("data/verification/2026-07-17-stage0/5b_gate_replay.json")
OUT_PATH = Path("data/verification/2026-07-17-stage0/5b_llm_sample.json")

SAMPLE_PER_TYPE = {"breakout": 4, "breakout_from_watch": 8,
                   "invalidation": 8, "promotion": 10}

ABORT_REASONS = {
    "sma50_breach_distribution_volume", "sma50_breach_low_volume",
    "stop_loss_breach", "base_depth_exceeded", "distribution_pattern_clear",
    "volume_insufficient_intraday_weak", "spread_wide_loose",
    "consecutive_weak_days",
}

_GO_NOW_GATES_31 = ("price_above_pivot", "close_upper_third", "no_dist_3d")


def _select_sample(records: list[dict]) -> list[dict]:
    """유형별 균등 간격 추출 — 무작위성 없이 재현 가능."""
    out = []
    for ttype, n in SAMPLE_PER_TYPE.items():
        pool = [r for r in records if r["trigger"] == ttype]
        if not pool:
            continue
        step = max(1, len(pool) // n)
        out.extend(pool[::step][:n])
    return out


def _prior_row(conn, symbol: str, sat: date) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT classification, pattern, pivot_price, pivot_basis, base_high,
                   base_low, base_depth_pct, risk_flags, reasoning, watch_reason
              FROM backtest_classification
             WHERE symbol = %s AND analyzed_for_date = %s
            """,
            (symbol, sat),
        )
        r = cur.fetchone()
    if r is None:
        raise ValueError(f"backtest row not found: {symbol} {sat}")
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


def _violations(trigger: str, gates: dict, result: dict) -> list[str]:
    v: list[str] = []
    decision = result.get("decision")
    if decision not in ("go_now", "wait", "abort"):
        return [f"H4: decision={decision!r}"]
    if decision == "abort" and result.get("abort_reason") not in ABORT_REASONS:
        v.append(f"H4: abort_reason={result.get('abort_reason')!r}")
    if decision != "go_now":
        return v
    if trigger in ("promotion", "invalidation"):
        v.append(f"H1: go_now on {trigger}")
        return v
    # breakout / breakout_from_watch 공통 §3.1 게이트
    for k in _GO_NOW_GATES_31:
        if gates.get(k) is not True:
            v.append(f"H2: go_now 인데 {k}={gates.get(k)}")
    if gates.get("volume_band") != "pass":
        v.append(f"H2: go_now 인데 volume_band={gates.get('volume_band')}")
    if gates.get("spread_wide_loose") is not False:
        v.append(f"H2: go_now 인데 spread_wide_loose={gates.get('spread_wide_loose')}")
    if trigger == "breakout_from_watch":
        for k in ("market_recovery_ok", "tt_recovery_ok"):
            if gates.get(k) is not True:
                v.append(f"H3: go_now 인데 {k}={gates.get(k)}")
    return v


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    records = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))["records"]
    sample = _select_sample(records)
    log.info("sample: %d건 %s", len(sample),
             Counter(r["trigger"] for r in sample))

    results = []
    agg = {"calls": 0, "errors": 0, "violations": 0,
           "aborted_usage_limit": False,
           "decisions": Counter()}

    with connect() as conn:
        for i, rec in enumerate(sample):
            symbol, sat = rec["symbol"], date.fromisoformat(rec["sat"])
            as_of = date.fromisoformat(rec["as_of"])
            try:
                prior = _prior_row(conn, symbol, sat)
                payload = build_for_5b(conn, symbol, trigger_type=rec["trigger"],
                                       as_of=as_of, prior_row=prior)
                llm_io: dict = {}
                result = call_claude(
                    prompt_file="evaluate_pivot_trigger_v1.md",
                    attachments=[], payload_inline=payload, meta_out=llm_io,
                )
            except UsageLimitError:
                log.warning("usage limit — clean abort at %d/%d", i, len(sample))
                agg["aborted_usage_limit"] = True
                break
            except Exception as e:
                log.warning("call failed %s %s: %s", symbol, as_of, e)
                agg["errors"] += 1
                continue
            gates = payload.get("computed_gates") or {}
            vio = _violations(rec["trigger"], gates, result)
            agg["calls"] += 1
            agg["decisions"][f"{rec['trigger']}:{result.get('decision')}"] += 1
            if vio:
                agg["violations"] += 1
            results.append({
                "symbol": symbol, "sat": rec["sat"], "as_of": rec["as_of"],
                "trigger": rec["trigger"], "computed_gates": gates,
                "decision": result.get("decision"),
                "abort_reason": result.get("abort_reason"),
                "confidence": result.get("confidence"),
                "reasoning": result.get("reasoning"),
                "violations": vio,
                "llm_model": llm_io.get("model"),
            })
            OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            OUT_PATH.write_text(
                json.dumps({"agg": {**agg, "decisions": dict(agg["decisions"])},
                            "results": results},
                           ensure_ascii=False, indent=2),
                encoding="utf-8")
            log.info("[%d/%d] %s %s %s → %s %s", i + 1, len(sample), symbol,
                     as_of, rec["trigger"], result.get("decision"),
                     f"⚠{vio}" if vio else "")

    print(json.dumps({**agg, "decisions": dict(agg["decisions"])},
                     ensure_ascii=False, indent=2))
    print(f"saved → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
