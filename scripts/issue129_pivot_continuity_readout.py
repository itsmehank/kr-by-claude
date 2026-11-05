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
                 판정 비입력 — 별도 descriptive 로 같이 센다(반사실: 옛 pivot 이었어도
                 발화했을지).
  지표 3 [descriptive] unknown(base_start 결측) 원인 구성비.
  #46 승계: 로그 '[pivot-continuity]' 경고 수 vs 저장본 same-base pivot 변경 행 수.

사용:  uv run python scripts/issue129_pivot_continuity_readout.py [--logs ~/.kr-by-claude]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from kr_pipeline.common.thresholds import GATE_PROMOTION_PRICE_RATIO

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
    # 패턴 왕복 A→B→A (종목별 연속 행, continuity 무관)
    bysym = defaultdict(list)
    for r in rows:
        bysym[r["symbol"]].append(r)
    rt = 0
    hist = Counter()
    for rs in bysym.values():
        pats = [rs[0]["pc"].get("prev_pattern")] + [r["pattern"] for r in rs]
        for i in range(len(pats) - 2):
            if pats[i] and pats[i + 1] and pats[i] != pats[i + 1] and pats[i] == pats[i + 2]:
                rt += 1
        hist[sum(1 for r in rs if r["pc"].get("pattern_changed"))] += 1
    out["pattern_round_trips"] = rt
    out["pattern_changed_per_symbol_hist"] = {str(k): v for k, v in sorted(hist.items())}
    return out


def metric2(cur, rows):
    down = [r for r in rows if r["pc"]["base_continuity"] in ("same", "near")
            and _pct(r) is not None and _pct(r) < 0]
    evals, breakout_fired, breakout_due_to_lowering, go_now, entry_syms = [], [], [], [], []
    promo_no_fire_old = 0
    for r in down:
        cur.execute(
            """SELECT evaluated_at, trigger_type, decision, close, wait_reason, analyzed_for_date
                 FROM trigger_evaluation_log WHERE symbol=%s AND prior_classification_at=%s
                ORDER BY evaluated_at""", (r["symbol"], r["classified_at"]))
        prev_pv = r["pc"]["prev_pivot_price"]
        new_pv = float(r["pivot_price"]) if r["pivot_price"] is not None else None
        for e in cur.fetchall():
            if e["trigger_type"] not in UPWARD_TYPES:
                continue
            close = float(e["close"]) if e["close"] is not None else None
            rec = {
                "symbol": r["symbol"], "classified_at": r["classified_at"].date().isoformat(),
                "classification": r["classification"], "continuity": r["pc"]["base_continuity"],
                "prev_pivot": prev_pv, "new_pivot": new_pv, "change_pct": _pct(r),
                "eval_date": (e["analyzed_for_date"] or e["evaluated_at"].date()).isoformat(),
                "trigger_type": e["trigger_type"], "decision": e["decision"], "close": close,
                "wait_reason": e["wait_reason"],
                "would_fire_under_old_pivot": (
                    None if close is None or prev_pv is None else
                    (close > prev_pv if e["trigger_type"] in BREAKOUT_TYPES
                     else close >= prev_pv * GATE_PROMOTION_PRICE_RATIO)),
            }
            evals.append(rec)
            if e["trigger_type"] in BREAKOUT_TYPES:
                breakout_fired.append(rec)
                if close is not None and prev_pv is not None and close <= prev_pv:
                    breakout_due_to_lowering.append(rec)
                if e["decision"] == "go_now":
                    go_now.append(rec)
            elif rec["would_fire_under_old_pivot"] is False:
                promo_no_fire_old += 1
        cur.execute("SELECT COUNT(*) n FROM entry_params WHERE symbol=%s AND prior_classification_at=%s",
                    (r["symbol"], r["classified_at"]))
        if cur.fetchone()["n"]:
            entry_syms.append(r["symbol"])
    return {
        "downward_rereads_same_near": len(down),
        "downward_rereads_same": sum(1 for r in down if r["pc"]["base_continuity"] == "same"),
        "upward_evaluations_after": len(evals),
        "promotion_evaluations": sum(1 for e in evals if e["trigger_type"] == "promotion"),
        "promotion_would_not_fire_under_old_pivot": promo_no_fire_old,
        "breakout_evaluations": len(breakout_fired),
        "breakout_only_because_pivot_lowered": len(breakout_due_to_lowering),
        "go_now": len(go_now),
        "entry_params_rows": len(entry_syms),
        "verdict_input": len(breakout_fired),          # 사전등록 지표 2 = 돌파 발화 사례 수
        "evaluations": evals,
    }


def metric3(cur, rows):
    unk = [r for r in rows if r["pc"]["base_continuity"] == "unknown"]
    cause = Counter()
    for r in unk:
        cur.execute("SELECT base_start_date FROM weekly_classification WHERE symbol=%s AND classified_at=%s",
                    (r["symbol"], r["pc"]["prev_classified_at"]))
        p = cur.fetchone()
        prev_bsd = p["base_start_date"] if p else None
        key = "|".join([
            "new_bsd_null" if r["base_start_date"] is None else "new_bsd_ok",
            "prev_bsd_null" if prev_bsd is None else "prev_bsd_ok",
            r["classification"] or "null",
            "pattern_none" if r["pattern"] in (None, "none") else "pattern_set",
            "pivot_null" if r["pivot_price"] is None else "pivot_set",
        ])
        cause[key] += 1
    return {"unknown": len(unk), "causes": dict(cause.most_common())}


def log_parity(rows, logs_dir):
    stored = [r for r in rows if r["pc"]["base_continuity"] == "same" and _pct(r) not in (None, 0)]
    per_file = {}
    for f in sorted(glob.glob(os.path.join(os.path.expanduser(logs_dir), "launchd-*.log"))):
        with open(f, "rb") as fh:
            n = sum(1 for line in fh if b"[pivot-continuity]" in line)
        if n:
            per_file[os.path.basename(f)] = n
    return {"stored_same_base_pivot_changed": len(stored),
            "stored_by_month": dict(sorted(Counter(r["classified_at"].date().isoformat()[:7] for r in stored).items())),
            "log_warnings_by_file": per_file, "log_warnings_total": sum(per_file.values())}


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
    print(f"[M1] pattern round-trips {res['metric1']['pattern_round_trips']}")
    print(f"[M2] downward same+near {m2['downward_rereads_same_near']} (same {m2['downward_rereads_same']}) | upward evals {m2['upward_evaluations_after']} "
          f"= promotion {m2['promotion_evaluations']} (old-pivot 반사실 미발화 {m2['promotion_would_not_fire_under_old_pivot']}) "
          f"+ breakout {m2['breakout_evaluations']} (하향 때문에만 발화 {m2['breakout_only_because_pivot_lowered']}) | go_now {m2['go_now']} entry_params {m2['entry_params_rows']}")
    for e in m2["evaluations"]:
        if e["trigger_type"] in BREAKOUT_TYPES:
            print("   breakout:", json.dumps(e, ensure_ascii=False))
    print(f"[M3] unknown {res['metric3']['unknown']}: {res['metric3']['causes']}")
    print(f"[#46] {res['issue46_log_parity']}")
    print(f"verdict: {res['verdict']}")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
