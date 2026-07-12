"""breakout_from_watch 관문 2-B — evaluate_pivot_trigger §3.5 LLM 판정 e2e (3사유).

build_for_5b(확장본) 형태의 inline payload(trigger_type='breakout_from_watch')를 직접 구성해
evaluate_pivot_trigger_v1.md 를 실제 claude 로 N회 호출, decision 분포 측정. DB 미사용.

게이트→breakout_from_watch 결정론 부분은 통합테스트(green)로 보장. 본 스크립트는 §3.5 의
사유별 LLM go_now/wait 판정만 검증:
  - valid_base_awaiting_breakout: 표준검증 충족→go_now / 미충족→wait
  - unfavorable_market: 시장 confirmed_uptrend 회복→go_now / 미회복→wait
  - marginal_tt: 8조건 clean→go_now / marginal 잔존→wait

실행: uv run python scripts/replay_bfw_e2e.py --n 10
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv()

PIVOT = 80000.0


def _ohlcv_20d(*, close, high, low, vol):
    bars = [{
        "date": f"2026-05-{i+1:02d}", "open": 75000, "high": 76500,
        "low": 74000, "close": 75500, "volume": 1_000_000,
        "distribution_day_flag": False,  # (#31) 규약상 필수 입력 — 미포함 시 판정 불가 교락
    } for i in range(19)]
    bars.append({"date": "2026-05-20", "open": 80800, "high": high,
                 "low": low, "close": close, "volume": vol,
                 "distribution_day_flag": False})
    return bars


def _conditions(*, margin):
    """8조건 전부 passed=True, margin_pct=margin (clean=큼 / marginal=작음<3)."""
    return {
        f"c{i}": {"passed": True, "description": f"condition {i}",
                  "values": ({"rs_rating": 88} if i == 8 else {}),
                  "margin_pct": margin}
        for i in range(1, 9)
    }


def _market_ctx(status):
    return {"current_status": status,
            "distribution_day_count_last_25_sessions": 1 if status == "confirmed_uptrend" else 6,
            "last_follow_through_day": "2026-05-02" if status == "confirmed_uptrend" else None,
            "days_since_follow_through": 13 if status == "confirmed_uptrend" else None,
            "pct_stocks_above_200d_ma": 62.0 if status == "confirmed_uptrend" else 28.0}


def _payload(*, watch_reason, close, vol, high, low, market_status, cond_margin):
    return {
        "symbol": "BFW_E2E", "name": "테스트", "market": "KOSPI",
        "evaluation_date": "2026-05-20",
        "trigger_type": "breakout_from_watch",
        "market_context": _market_ctx(market_status),
        "conditions_met": {f"c{i}": True for i in range(1, 9)},
        "conditions_detail": _conditions(margin=cond_margin),
        "rs_rating": 88,
        "prior_analysis": {
            "classified_at": "2026-05-08T03:00:00+00:00",
            "days_since_classification": 12, "classification": "watch",
            "pattern": "flat_base", "pivot_price": PIVOT, "pivot_basis": "range_high",
            "base_high": PIVOT, "base_low": 72000.0, "base_depth_pct": 10.0,
            "risk_flags": [], "reasoning": "flat base 완성, pivot 80000",
            "watch_reason": watch_reason,
        },
        "recent_daily_ohlcv_20d": _ohlcv_20d(close=close, high=high, low=low, vol=vol),
        "current_metrics": {"close": close, "volume": vol, "avg_volume_50d": 1_000_000,
                            "volume_ratio": round(vol / 1_000_000, 2),
                            "sma_50": 76000.0, "sma_21": 78000.0},
        "recent_evaluation_history": [],
    }


# 강한 돌파 바 (표준검증 충족): close +3.1%, vol 1.6×, 종가 상단 1/3
STRONG = dict(close=82500, vol=1_600_000, high=83000, low=80500)
WEAK = dict(close=80300, vol=1_150_000, high=81200, low=79600)  # vol 1.15× + 중간권

CASES = {
    "valid_base_strong":   {"expect": "go_now",
        "payload": _payload(watch_reason="valid_base_awaiting_breakout", **STRONG,
                            market_status="confirmed_uptrend", cond_margin=8.0)},
    "valid_base_weak":     {"expect": "wait",
        "payload": _payload(watch_reason="valid_base_awaiting_breakout", **WEAK,
                            market_status="confirmed_uptrend", cond_margin=8.0)},
    "unfav_recovered":     {"expect": "go_now",
        "payload": _payload(watch_reason="unfavorable_market", **STRONG,
                            market_status="confirmed_uptrend", cond_margin=8.0)},
    "unfav_still_down":    {"expect": "wait",
        "payload": _payload(watch_reason="unfavorable_market", **STRONG,
                            market_status="downtrend", cond_margin=8.0)},
    "marginal_clean":      {"expect": "go_now",
        "payload": _payload(watch_reason="marginal_tt", **STRONG,
                            market_status="confirmed_uptrend", cond_margin=8.0)},
    "marginal_remains":    {"expect": "wait",
        "payload": _payload(watch_reason="marginal_tt", **STRONG,
                            market_status="confirmed_uptrend", cond_margin=1.2)},
}


def _one_call(payload: dict) -> dict:
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude
    try:
        return call_claude(prompt_file="evaluate_pivot_trigger_v1.md",
                           attachments=[], payload_inline=payload, dry_run=False)
    except Exception as e:  # noqa: BLE001
        return {"_ERROR": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    tasks = [k for k in CASES for _ in range(args.n)]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        paired = list(ex.map(lambda k: (k, _one_call(CASES[k]["payload"])), tasks))
    by_key: dict[str, list] = {}
    for k, r in paired:
        by_key.setdefault(k, []).append(r)
    report = {}
    for k, runs in by_key.items():
        ok = [r for r in runs if "_ERROR" not in r]
        report[k] = {
            "expect": CASES[k]["expect"],
            "decisions": dict(Counter(r.get("decision") for r in ok)),
            "abort_reasons": dict(Counter(r.get("abort_reason") for r in ok if r.get("abort_reason"))),
            "errors": sum(1 for r in runs if "_ERROR" in r),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
