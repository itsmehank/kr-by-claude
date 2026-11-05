#!/usr/bin/env python
"""#129 pivot_continuity 관측 1차 판독 — 사전등록 지표 1·2·3 + #46 승계 로그 대조.

읽기 전용(운영 DB SELECT 만, KRX 0·DART 0·LLM 0). 결과는 표준 출력 요약 +
data/verification/issue129_pivot_continuity_readout_<YYYYMMDD>.json.

사전등록(이슈 #129 본문, 2026-08-24 봉인):
  지표 1 [descriptive] same/near-base 의 pivot_change_pct 분포·pattern_changed 왕복.
  지표 2 [판정]  pivot 이 직전 활성 판독보다 *하향* 재판독된 뒤, 그 새 pivot 돌파로
                 트리거 평가가 발화한 사례 수 + 그중 go_now 도달 수.
                 '돌파' = trigger_gate 의 close > pivot 경로(breakout·breakout_from_watch).
                 promotion(close ≥ pivot×0.95, §3.3 go_now 금지)은 돌파가 아니므로
                 판정 비입력 — descriptive 로 같이 센다.
                 범위(리뷰 R1-1): 하향 행 자체 + 내려간 pivot 을 그대로 유지한 후속 행
                 (same/near·Δ≤0·pivot<옛 pivot)까지 — 상향 재판독·베이스 변경에서 중단.
                 different(새 베이스) 하향은 재판독이 아니라 제외하되 건수는 병기(R1-5).
  지표 3 [descriptive] unknown(base_start 결측) 원인 구성비 — 정의상 100% 가 한쪽 이상
                 결측이므로 '어느 쪽이 결측인가 × 현재 행 상태' 로 나눈다(R1-3).
  #46 승계: 로그 '[pivot-continuity] same-base' 경고 vs 저장본 same-base pivot 변경 행을
                 (종목, 변화율) 사건 단위로 대조(R1-7).
반사실(옛 pivot 이었다면 발화했을까)은 가격 조건만 본다(fresh_cross·거래량 미반영, R1-4).

사용:  uv run python scripts/issue129_pivot_continuity_readout.py [--logs ~/.kr-by-claude]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from kr_pipeline.common.thresholds import GATE_PROMOTION_PRICE_RATIO
from kr_pipeline.llm_runner.compute.pivot_continuity_stats import (
    downward_chains, parse_log_events, pattern_round_trips, stored_events,
)

BREAKOUT_TYPES = ("breakout", "breakout_from_watch")   # close > pivot 경로(go_now 가능)
UPWARD_TYPES = BREAKOUT_TYPES + ("promotion",)


def _pct(r):
    return r["pc"].get("pivot_change_pct")


def _quantiles(xs):
    s = sorted(xs)
    q = lambda p: s[int(p * (len(s) - 1))]
    return {"min": s[0], "p10": q(.1), "p50": q(.5), "p90": q(.9), "max": s[-1]}


def metric1(rows):
    out = {}
    for cont in ("same", "near", "same+near"):
        sel = [r for r in rows if r["pc"]["base_continuity"] in cont.split("+")]
        ch = [_pct(r) for r in sel if _pct(r) not in (None, 0)]
        pat = [r["pc"].get("pattern_changed") for r in sel]
        d = {
            "n": len(sel), "pivot_changed": len(ch),
            "up": sum(1 for x in ch if x > 0), "down": sum(1 for x in ch if x < 0),
            "pct_null": sum(1 for r in sel if _pct(r) is None),
            "abs_ge_5": sum(1 for x in ch if abs(x) >= 5), "abs_ge_10": sum(1 for x in ch if abs(x) >= 10),
            "down_le_minus5": sum(1 for x in ch if x <= -5),
            "pattern_changed": sum(1 for p in pat if p), "pattern_comparable": sum(1 for p in pat if p is not None),
        }
        if ch:
            d["change_pct"] = _quantiles(ch)
        out[cont] = d
    out["pattern_round_trips"] = pattern_round_trips(rows)
    return out


def _old_pivot_fire(trigger_type, close, old_pv):
    """옛 pivot 기준 가격 조건만의 반사실(R1-4: fresh_cross·거래량 미반영)."""
    if close is None or old_pv is None:
        return None
    if trigger_type in BREAKOUT_TYPES:
        return "breakout" if close > old_pv else ("promotion" if close >= old_pv * GATE_PROMOTION_PRICE_RATIO else "none")
    return "promotion" if close >= old_pv * GATE_PROMOTION_PRICE_RATIO else "none"


def metric2(cur, rows):
    chains = downward_chains(rows)
    starts = [c[0] for c in chains]
    # (symbol, classified_at) → 체인 시작의 옛 pivot(여러 체인에 속하면 가장 이른 시작 기준)
    old_by_key = {}
    for start, old, members in chains:
        for m in members:
            old_by_key.setdefault((m["symbol"], m["classified_at"]), (old, start))
    evals, breakout_fired, breakout_due, go_now, entry_keys = [], [], [], [], set()
    promo_due = 0
    for (sym, cls_at), (old_pv, start) in sorted(old_by_key.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        row = next(m for _s, _o, ms in chains for m in ms if m["symbol"] == sym and m["classified_at"] == cls_at)
        cur.execute(
            """SELECT evaluated_at, trigger_type, decision, close, wait_reason, analyzed_for_date
                 FROM trigger_evaluation_log WHERE symbol=%s AND prior_classification_at=%s
                ORDER BY evaluated_at""", (sym, cls_at))
        new_pv = float(row["pivot_price"]) if row["pivot_price"] is not None else None
        for e in cur.fetchall():
            if e["trigger_type"] not in UPWARD_TYPES:
                continue
            close = float(e["close"]) if e["close"] is not None else None
            cf = _old_pivot_fire(e["trigger_type"], close, old_pv)
            rec = {
                "symbol": sym, "classified_at": cls_at.date().isoformat(), "carry_over": row is not start,
                "chain_start": start["classified_at"].date().isoformat(), "continuity": row["pc"]["base_continuity"],
                "old_pivot": old_pv, "new_pivot": new_pv,
                "eval_date": (e["analyzed_for_date"] or e["evaluated_at"].date()).isoformat(),
                "trigger_type": e["trigger_type"], "decision": e["decision"], "close": close,
                "wait_reason": e["wait_reason"], "old_pivot_price_only_would_fire": cf,
            }
            evals.append(rec)
            if e["trigger_type"] in BREAKOUT_TYPES:
                breakout_fired.append(rec)
                if close is not None and old_pv is not None and close <= old_pv:
                    breakout_due.append(rec)
                if e["decision"] == "go_now":
                    go_now.append(rec)
            elif cf == "none":
                promo_due += 1
        cur.execute("SELECT COUNT(*) n FROM entry_params WHERE symbol=%s AND prior_classification_at=%s", (sym, cls_at))
        if cur.fetchone()["n"]:
            entry_keys.add((sym, cls_at))
    # R1-5: different(새 베이스) 하향 — 제외 사유 병기용 건수
    diff_down = [r for r in rows if r["pc"]["base_continuity"] == "different" and _pct(r) is not None and _pct(r) < 0]
    diff_breakouts = 0
    for r in diff_down:
        cur.execute("""SELECT COUNT(*) n FROM trigger_evaluation_log WHERE symbol=%s AND prior_classification_at=%s
                       AND trigger_type = ANY(%s)""", (r["symbol"], r["classified_at"], list(BREAKOUT_TYPES)))
        diff_breakouts += cur.fetchone()["n"]
    return {
        "downward_rereads_same_near": len(starts),
        "downward_rereads_same": sum(1 for r in starts if r["pc"]["base_continuity"] == "same"),
        "carry_over_rows": len(old_by_key) - len({(s["symbol"], s["classified_at"]) for s in starts}),
        "chains_with_carry_over": sum(1 for c in chains if len(c[2]) > 1),
        "upward_evaluations": len(evals),
        "promotion_evaluations": sum(1 for e in evals if e["trigger_type"] == "promotion"),
        "promotion_old_pivot_price_only_no_fire": promo_due,
        "breakout_evaluations": len(breakout_fired),
        "breakout_symbols": sorted({e["symbol"] for e in breakout_fired}),
        "breakout_close_le_old_pivot": len(breakout_due),
        "go_now": len(go_now),
        "entry_params_rows": len(entry_keys),
        "excluded_different_base_downward_rows": len(diff_down),
        "excluded_different_base_breakout_evaluations": diff_breakouts,
        "verdict_input": len(breakout_fired),          # 사전등록 지표 2 = 돌파 발화 사례 수
        "evaluations": evals,
    }


def metric3(cur, rows):
    unk = [r for r in rows if r["pc"]["base_continuity"] == "unknown"]
    side = Counter(); current_state = Counter(); prev_state = Counter()
    for r in unk:
        cur.execute("SELECT base_start_date, pattern, pivot_price FROM weekly_classification WHERE symbol=%s AND classified_at=%s",
                    (r["symbol"], r["pc"]["prev_classified_at"]))
        p = cur.fetchone() or {}
        new_missing, prev_missing = r["base_start_date"] is None, p.get("base_start_date") is None
        side["both_missing" if new_missing and prev_missing else "current_only_missing" if new_missing else "previous_only_missing"] += 1
        current_state["|".join([r["classification"] or "null",
                                "pattern_none" if r["pattern"] in (None, "none") else "pattern_set",
                                "pivot_null" if r["pivot_price"] is None else "pivot_set"])] += 1
        prev_state["|".join(["prev_pattern_none" if p.get("pattern") in (None, "none") else "prev_pattern_set",
                             "prev_pivot_null" if p.get("pivot_price") is None else "prev_pivot_set"])] += 1
    return {"unknown": len(unk), "missing_side": dict(side.most_common()),
            "current_row_state": dict(current_state.most_common()), "previous_row_state": dict(prev_state.most_common())}


def log_parity(rows, logs_dir):
    stored = stored_events(rows)
    logged = Counter(); per_file = {}
    for f in sorted(glob.glob(os.path.join(os.path.expanduser(logs_dir), "launchd-*.log"))):
        with open(f, "rb") as fh:
            ev = parse_log_events(fh)
        if ev:
            per_file[os.path.basename(f)] = sum(ev.values()); logged += ev
    matched = sum((stored & logged).values())
    return {"stored_same_base_pivot_changed": sum(stored.values()),
            "stored_by_month": dict(sorted(Counter(r["classified_at"].date().isoformat()[:7] for r in rows
                                                   if r["pc"]["base_continuity"] == "same" and _pct(r) not in (None, 0)).items())),
            "log_warnings_by_file": per_file, "log_warnings_total": sum(logged.values()),
            "event_matched": matched,
            "stored_only": [f"{k[0]} {k[1]:+}%" for k in (stored - logged)],
            "log_only": [f"{k[0]} {k[1]:+}%" for k in (logged - stored)]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="~/.kr-by-claude", help="launchd 로그 디렉터리(#46 대조)")
    ap.add_argument("--out-dir", default="data/verification")
    a = ap.parse_args(argv)
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL 미설정", file=sys.stderr)
        return 1
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("""SELECT symbol, classified_at, analyzed_for_date, classification, pattern, pivot_price,
                              base_start_date, pivot_continuity pc
                         FROM weekly_classification WHERE pivot_continuity IS NOT NULL
                        ORDER BY symbol, classified_at""")
        rows = cur.fetchall()
        res = {
            "issue": 129, "generated": date.today().isoformat(),
            "sample": {"rows": len(rows), "symbols": len({r["symbol"] for r in rows}),
                       "from": min(r["classified_at"] for r in rows).date().isoformat(),
                       "to": max(r["classified_at"] for r in rows).date().isoformat(),
                       "by_continuity": dict(Counter(r["pc"]["base_continuity"] for r in rows))},
            "metric1": metric1(rows), "metric2": metric2(cur, rows), "metric3": metric3(cur, rows),
            "issue46_log_parity": log_parity(rows, a.logs),
        }
    m2 = res["metric2"]
    res["verdict"] = ("indicator2_gt_0 → 보류 대안 개봉 논의 개시" if m2["verdict_input"] > 0
                      else "indicator2_eq_0 → 구조적 위험 존재·실전 발현 0 종결")
    out = Path(a.out_dir) / f"issue129_pivot_continuity_readout_{date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    s = res["sample"]
    print(f"sample rows {s['rows']} symbols {s['symbols']} {s['from']}..{s['to']} {s['by_continuity']}")
    for k in ("same", "near", "same+near"):
        d = res["metric1"][k]
        print(f"[M1 {k}] n={d['n']} pivot_changed={d['pivot_changed']} up={d['up']} down={d['down']} "
              f"|x|>=5%={d['abs_ge_5']} down<=-5%={d['down_le_minus5']} pattern_changed={d['pattern_changed']}/{d['pattern_comparable']}"
              + (f" change%={d['change_pct']}" if "change_pct" in d else ""))
    print(f"[M1] pattern round-trips(true consecutive, none 제외) {res['metric1']['pattern_round_trips']}")
    print(f"[M2] downward same+near {m2['downward_rereads_same_near']} (same {m2['downward_rereads_same']}) + carry-over rows {m2['carry_over_rows']} "
          f"(chains with carry-over {m2['chains_with_carry_over']}) | upward evals {m2['upward_evaluations']} = promotion {m2['promotion_evaluations']} "
          f"(옛 pivot 가격조건 미발화 {m2['promotion_old_pivot_price_only_no_fire']}) + breakout {m2['breakout_evaluations']} "
          f"(symbols {m2['breakout_symbols']}, close<=옛 pivot {m2['breakout_close_le_old_pivot']}) | go_now {m2['go_now']} entry_params {m2['entry_params_rows']} "
          f"| excluded different-base: downward rows {m2['excluded_different_base_downward_rows']}, breakout evals {m2['excluded_different_base_breakout_evaluations']}")
    for e in m2["evaluations"]:
        if e["trigger_type"] in BREAKOUT_TYPES:
            print("   breakout:", json.dumps(e, ensure_ascii=False))
    print(f"[M3] unknown {res['metric3']['unknown']} side={res['metric3']['missing_side']} current={res['metric3']['current_row_state']} prev={res['metric3']['previous_row_state']}")
    print(f"[#46] {res['issue46_log_parity']}")
    print(f"verdict: {res['verdict']}")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
