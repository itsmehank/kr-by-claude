#!/usr/bin/env python
"""#175 저장본 재현 readout — 구(2026-11-06 이전) vs 신 검출기 diff. 읽기 전용(운영 DB SELECT 만, KRX 0·DART 0·LLM 0).

대상: weekly_classification · backtest_classification 의 cup_with_handle entry/watch 전 행.
구 규칙 = compute.handle_low_readout.legacy_detect(독립 재구현, UTC 창 끝·1단 매칭·0.80 컵 평균·분배일 ≥1).
신 규칙 = compute.handle_quality.compute_handle_quality(as_of = COALESCE(analyzed_for_date, KST 날짜 − 1)).

출력(spec 2026-11-06-issue175-handle-low-design.md §6-2):
  (a) 발화 저장 행(triggered_rules.2E_*.handle_quality_metrics): 구·신 규칙이 **오늘 데이터로 둘 다 식별한** 행에서
      구 규칙(재구현) vs 신 규칙의 handle_start·handle_high 전수 일치 + "구 식별·신 비식별(handle_above_pivot 가드 외)" 0건
      = **머지 게이트(exit 2)**. 저장 metrics 와의 차이(stored_drift)는 저장 당시 데이터 빈티지(adj 재적재 등) — 정보만.
      구 규칙도 식별 못 하는 행(legacy_none: #177 하한 5일 이전 저장분·adj 재스케일)은 이번 변경과 무관 — 건수·사유만 기록.
  (b) handle_end 변화 행 목록(기대 = 09:00 KST 이전 실행 행)
  (c) 발화 집합 변화 2×2 + 사유별
  (d) 커버리지 전/후·skip 사유 분포·pivot_eff_source 분포
  (e) handle_low 깊이(pivot_eff 대비 %) 분포·8~12% 밴드 비율·handle_above_pivot 수
  (f) LLM measurements.handle_depth_pct 와 |차| > 3pp 비율
결과 = data/verification/issue175_handle_low_readout_<YYYYMMDD>.json + 표준 출력 요약.

사용:  uv run python scripts/issue175_handle_low_readout.py [--table weekly|backtest|both]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from kr_pipeline.llm_runner.compute.handle_low_readout import (
    compare_fired_rows, fired_transition, kst_fallback_as_of, legacy_detect, quantiles,
)
from kr_pipeline.llm_runner.compute.handle_quality import compute_handle_quality

TABLES = {"weekly": "weekly_classification", "backtest": "backtest_classification"}
_SKIP_RE = re.compile(r"reason=(.+)$")


class _SkipCapture(logging.Handler):
    """검출기 skip 사유(log.info "[handle_quality] skipped … reason=…")를 반환값 대신 로그에서 읽는다(검출기 서명 불변)."""
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.last: str | None = None

    def emit(self, record):
        msg = record.getMessage()
        if "[handle_quality] skipped" in msg:
            m = _SKIP_RE.search(msg)
            self.last = m.group(1) if m else msg


def _d(x):
    return x.date() if isinstance(x, datetime) else x


def _bars(cur, sym, start, end, inclusive: bool):
    cur.execute(
        f"""SELECT p.date, COALESCE(p.adj_high,p.high), COALESCE(p.adj_low,p.low), COALESCE(p.adj_close,p.close),
                   COALESCE(p.adj_volume,p.volume), i.sma_50, COALESCE(i.distribution_day_flag, FALSE), i.avg_volume_50d
              FROM daily_prices p LEFT JOIN daily_indicators i ON i.ticker=p.ticker AND i.date=p.date
             WHERE p.ticker=%s AND p.date >= %s AND p.date {"<=" if inclusive else "<"} %s ORDER BY p.date""",
        (sym, start, end))
    return cur.fetchall()


def _stored_metrics(tr):
    if not tr:
        return None
    for k in ("2E_tier1", "2E_tier2"):
        if k in tr and tr[k].get("handle_quality_metrics"):
            return tr[k]["handle_quality_metrics"]
    return None


def run_table(conn, table: str) -> dict:
    cap = _SkipCapture()
    hq_log = logging.getLogger("kr_pipeline.llm_runner.compute.handle_quality")
    hq_log.addHandler(cap)
    hq_log.setLevel(logging.INFO)
    prev_propagate, hq_log.propagate = hq_log.propagate, False
    cur = conn.cursor()
    cur.execute(f"""SELECT symbol, classified_at, analyzed_for_date, classification, pattern, pivot_price, pivot_basis,
                           base_high, base_low, base_depth_pct, base_start_date, triggered_rules, measurements
                      FROM {table}
                     WHERE pattern = 'cup_with_handle' AND classification IN ('entry','watch')
                     ORDER BY classified_at""")
    cls_rows = cur.fetchall()
    skip_old, skip_new, src_new, trans = Counter(), Counter(), Counter(), Counter()
    reasons_old, reasons_new = Counter(), Counter()
    fired_cmp = {"n": 0, "both_detect": 0, "start_high_match": 0, "mismatch": [], "end_changed": [],
                 "legacy_none": [], "new_none_guard": [], "new_none_other": [], "stored_drift": []}
    depths_new, llm_diff, above_pivot = [], [], 0
    n_old = n_new = 0
    for (sym, cat, afd, c, pat, pv, pb, bh, bl, bd, bsd, tr, meas) in cls_rows:
        cls = {"pattern": pat, "pivot_basis": pb, "base_start_date": bsd, "pivot_price": pv, "base_depth_pct": bd,
               "base_high": bh, "base_low": bl}
        # 구 규칙 창 끝 = 저장 당시 store 경로 그대로: 실전(weekly) = classified_at 의 UTC 날짜 미포함,
        # 백필/백테스트 = gate_at(analyzed_for_date + 1) 미포함(= D 포함)
        legacy_end = (afd + timedelta(days=1)) if table != "weekly_classification" and afd is not None else _d(cat)
        rows_old = _bars(cur, sym, bsd, legacy_end, False) if bsd is not None else []
        old, skip = legacy_detect(rows_old, cls)
        if old is None:
            skip_old[skip] += 1
        else:
            n_old += 1
        # 신 규칙(as_of 포함 창) — 검출기 본체 호출
        as_of = afd or kst_fallback_as_of(cat)
        cap.last = None
        new = compute_handle_quality(conn, sym, cat, cls, as_of=as_of)
        if new is None:
            skip_new[cap.last or "unknown"] += 1
            if cap.last == "handle_above_pivot":
                above_pivot += 1
        else:
            n_new += 1
            src_new[new["metrics"]["pivot_eff_source"]] += 1
            depths_new.append(new["metrics"]["handle_depth_pct"])
            for rs in new["reasons"]:
                reasons_new[rs] += 1
            if meas and meas.get("handle_depth_pct") is not None:
                llm_diff.append(abs(new["metrics"]["handle_depth_pct"] - float(meas["handle_depth_pct"])))
        if old is not None and old["fired"]:
            if old["ratio_b"] > 0.80:
                reasons_old["volume_not_contracting"] += 1
            if old["distribution_days"] >= 1:
                reasons_old["distribution_in_handle"] += 1
        trans[fired_transition(None if old is None else old["fired"], None if new is None else new["fired"])] += 1
        # (a)(b) 저장 발화 행 대조
        stored = _stored_metrics(tr)
        if stored:
            fired_cmp["n"] += 1
            key = {"symbol": sym, "classified_at": cat.isoformat(), "analyzed_for_date": str(afd),
                   "stored": {k: stored.get(k) for k in ("handle_start", "handle_high", "handle_low", "handle_end")}}
            if old is None:
                # 오늘 데이터·현 규칙(#177 하한 5일 등)으로는 구 규칙도 식별 못 함 — 이번 변경과 무관(저장 당시 규칙/데이터 차이)
                fired_cmp["legacy_none"].append({**key, "legacy_skip": skip,
                                                 "new": None if new is None else {k: new["metrics"].get(k) for k in ("handle_start", "handle_high", "pivot_eff_source")},
                                                 "new_skip": None if new is not None else cap.last})
                continue
            if new is None:
                bucket = "new_none_guard" if cap.last == "handle_above_pivot" else "new_none_other"
                fired_cmp[bucket].append({**key, "new_skip": cap.last,
                                          "legacy": {k: old.get(k) for k in ("handle_start", "handle_high", "handle_low")}})
                continue
            fired_cmp["both_detect"] += 1
            cmpr_legacy = compare_fired_rows(old, new["metrics"])          # 게이트: 같은 데이터, 구 vs 신
            cmpr = compare_fired_rows(stored, new["metrics"])              # 정보: 저장 당시 데이터 vs 오늘
            if not (cmpr_legacy["start_match"] and cmpr_legacy["high_match"]):
                fired_cmp["mismatch"].append({"symbol": sym, "classified_at": cat.isoformat(), "kind": "legacy_vs_new",
                                              "cmp": cmpr_legacy,
                                              "legacy": {k: old.get(k) for k in ("handle_start", "handle_high", "handle_end")},
                                              "new": {k: new["metrics"].get(k) for k in ("handle_start", "handle_high", "handle_end", "pivot_eff_source")}})
            elif not (cmpr["start_match"] and cmpr["high_match"]):
                fired_cmp["start_high_match"] += 1
                fired_cmp["stored_drift"].append({"symbol": sym, "classified_at": cat.isoformat(), "cmp": cmpr,
                                                  "stored": {k: stored.get(k) for k in ("handle_start", "handle_high", "handle_end")},
                                                  "legacy_today": {k: old.get(k) for k in ("handle_start", "handle_high")},
                                                  "new": {k: new["metrics"].get(k) for k in ("handle_start", "handle_high", "pivot_eff_source")}})
            else:
                fired_cmp["start_high_match"] += 1
            if cmpr["end_changed"]:
                fired_cmp["end_changed"].append({"symbol": sym, "classified_at": cat.isoformat(),
                                                 "stored_end": stored.get("handle_end"), "new_end": new["metrics"]["handle_end"],
                                                 "kst_hour": cat.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")).hour})
    hq_log.removeHandler(cap)
    hq_log.propagate = prev_propagate
    band = [x for x in depths_new if 8.0 <= x <= 12.0]
    return {
        "table": table, "rows_cwh_entry_watch": len(cls_rows),
        "a_fired_rows": {"n": fired_cmp["n"], "both_detect": fired_cmp["both_detect"],
                         "start_high_match": fired_cmp["start_high_match"],
                         "mismatch_n": len(fired_cmp["mismatch"]), "mismatch": fired_cmp["mismatch"],
                         "legacy_none_n": len(fired_cmp["legacy_none"]), "legacy_none": fired_cmp["legacy_none"],
                         "new_none_guard_n": len(fired_cmp["new_none_guard"]), "new_none_guard": fired_cmp["new_none_guard"],
                         "new_none_other_n": len(fired_cmp["new_none_other"]), "new_none_other": fired_cmp["new_none_other"],
                         "stored_drift_n": len(fired_cmp["stored_drift"]), "stored_drift": fired_cmp["stored_drift"]},
        "b_end_changed": {"n": len(fired_cmp["end_changed"]), "rows": fired_cmp["end_changed"]},
        "c_fired_transition": dict(trans), "c_reasons_old": dict(reasons_old), "c_reasons_new": dict(reasons_new),
        "d_coverage": {"old_detected": n_old, "new_detected": n_new,
                       "old_skip": dict(skip_old), "new_skip": dict(skip_new), "new_pivot_eff_source": dict(src_new)},
        "e_depth_new": {**quantiles(depths_new), "in_8_12_band": len(band),
                        "band_ratio": round(len(band) / len(depths_new), 3) if depths_new else None,
                        "handle_above_pivot": above_pivot},
        "f_llm_depth_abs_diff": {**quantiles(llm_diff), "gt_3pp": sum(1 for x in llm_diff if x > 3),
                                 "gt_3pp_ratio": round(sum(1 for x in llm_diff if x > 3) / len(llm_diff), 3) if llm_diff else None},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", choices=["weekly", "backtest", "both"], default="both")
    args = ap.parse_args()
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "tables": []}
    gate_ok = True
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.read_only = True
        for key in (["weekly", "backtest"] if args.table == "both" else [args.table]):
            r = run_table(conn, TABLES[key])
            out["tables"].append(r)
            a = r["a_fired_rows"]
            if a["mismatch_n"] > 0 or a["new_none_other_n"] > 0:
                gate_ok = False
            summary = {k: v for k, v in r.items() if k not in ("a_fired_rows", "b_end_changed")}
            summary["a_fired_rows"] = {k: v for k, v in a.items()
                                       if k not in ("mismatch", "legacy_none", "new_none_guard", "new_none_other", "stored_drift")}
            summary["b_end_changed_n"] = r["b_end_changed"]["n"]
            print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
            for m in a["mismatch"][:10]:
                print("MISMATCH", json.dumps(m, ensure_ascii=False, default=str))
            for m in a["stored_drift"][:10]:
                print("STORED_DRIFT", json.dumps(m, ensure_ascii=False, default=str))
            for m in a["new_none_other"][:10]:
                print("NEW_NONE_OTHER", json.dumps(m, ensure_ascii=False, default=str))
            for m in a["new_none_guard"][:10]:
                print("NEW_NONE_GUARD", json.dumps(m, ensure_ascii=False, default=str))
            for m in a["legacy_none"][:20]:
                print("LEGACY_NONE", json.dumps(m, ensure_ascii=False, default=str))
            for e in r["b_end_changed"][:10] if isinstance(r["b_end_changed"], list) else r["b_end_changed"]["rows"][:10]:
                print("END_CHANGED", json.dumps(e, ensure_ascii=False, default=str))
    dest = Path("data/verification") / f"issue175_handle_low_readout_{date.today():%Y%m%d}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    print("saved", dest)
    if not gate_ok:
        print("GATE FAIL: 구·신 둘 다 식별한 저장 발화 행의 start/high 불일치 또는 구 식별·신 비식별(가드 외) — spec §11 Q3", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
