"""#112 탐색 러너 — LLM 분류 선별 가치(entry+watch vs ignore) forward excess. 읽기 전용.

설계(방법 고정 2026-11-02): docs/superpowers/specs/2026-11-02-issue112-selection-value-design.md
등급: 탐색(표본 A·B·C 기열람). 실행 후 LOOK_LOG 1행 기입.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import date

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.backtest.frozen_sample_c import FROZEN_SAMPLE_C
from kr_pipeline.backtest.minervini_forward import (
    BOOT_B, HORIZONS, PRIMARY_H, SEED, load_index_closes,
)
from kr_pipeline.backtest.selection_value import (
    assign_sample, attach_excess, diff_bootstrap, diff_bootstrap_stratified, hint_of,
    load_cells,
)
from kr_pipeline.db.connection import connect

SPEC = "docs/superpowers/specs/2026-11-02-issue112-selection-value-design.md"


def _block(cells: list[dict], h: int, *, rej: str = "rej") -> dict:
    out = diff_bootstrap(cells, key=f"excess_{h}", sel="sel", rej=rej)
    out["hint"] = hint_of(out["ci95"])
    return out


def main() -> int:
    sets = {"A": set(FROZEN_SAMPLE), "B": set(FROZEN_SAMPLE_B), "C": set(FROZEN_SAMPLE_C)}
    with connect() as conn:
        conn.execute("SET default_transaction_read_only = on")
        cells = load_cells(conn)
        idx = load_index_closes(conn)
        excluded = attach_excess(conn, cells, idx)
    for c in cells:
        c["sample"] = assign_sample(c["ticker"], c["date"], sets)
        # 층 = 연도. 2017~20 은 기각 셀이 연 1~10 뿐이라(부트스트랩 반복 대부분이 빈 군) 한 층으로 병합
        y = c["date"].year
        c["year"] = "2017-20" if y <= 2020 else str(y)

    counts = Counter(c["classification"] for c in cells)
    samples = Counter((c["sample"] or "unassigned") for c in cells)
    reasons = Counter(c["reason"] for c in cells if c["group"] == "rej")

    out: dict = {
        "issue": 112, "spec": SPEC, "grade": "exploratory",
        "seed": SEED, "b": BOOT_B, "horizons": list(HORIZONS), "primary_h": PRIMARY_H,
        "n_cells": len(cells), "by_classification": dict(counts),
        "by_sample": dict(samples), "ignore_reasons": dict(reasons),
        "excluded_by_horizon": {str(h): excluded[h] for h in HORIZONS},
        # 미귀속 = frozen_sample_b.EXCLUDED_AT_DRAW − FROZEN_SAMPLE (표본 A 동결 전 드리프트 잉여 14종목, 리뷰 R1-1)
        "unassigned_tickers": sorted({c["ticker"] for c in cells if c["sample"] is None}),
        "pooled": {str(h): _block(cells, h) for h in HORIZONS},
        # 민감도: frozen 표본 귀속 셀만(미귀속 = 초기 백필 잔여 종목)
        "pooled_assigned_only_h20": _block([c for c in cells if c["sample"] is not None], PRIMARY_H),
        "by_sample_h20": {s: _block([c for c in cells if c["sample"] == s], PRIMARY_H)
                          for s in ("A", "B", "C")},
        # 연도 층화(기각 셀 수 가중) — 달력 구성 교락 민감도(리뷰 R1-2)
        "pooled_year_stratified_h20": diff_bootstrap_stratified(
            cells, key=f"excess_{PRIMARY_H}", sel="sel", rej="rej", stratum="year"),
        "by_ignore_reason_h20": {},
        "entry_only_h20": None,
    }
    # 기각 사유별: 해당 사유 기각군 vs 전체 선별군
    for r in sorted(reasons):
        sub = [c for c in cells if c["group"] == "sel" or (c["group"] == "rej" and c["reason"] == r)]
        out["by_ignore_reason_h20"][r] = _block(sub, PRIMARY_H)
    # entry 단독(참고): entry 를 sel, ignore 를 rej 로 두고 watch 제외
    ent = [dict(c, group="sel" if c["classification"] == "entry" else c["group"])
           for c in cells if c["classification"] != "watch"]
    out["entry_only_h20"] = _block(ent, PRIMARY_H)
    out["pooled_year_stratified_h20"]["hint"] = hint_of(out["pooled_year_stratified_h20"]["ci95"])

    path = f"data/backtest/exploratory_issue112_selection_value_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(json.dumps({"n_cells": out["n_cells"], "by_sample": out["by_sample"],
                      "excluded": out["excluded_by_horizon"],
                      "pooled_h20": out["pooled"][str(PRIMARY_H)]}, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
