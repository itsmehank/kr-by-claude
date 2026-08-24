"""#118 체크리스트 1 — #111 원판정 재실행 (대체 측정 r111-v2, 탐색 등급).

- 라벨: r111-v2 (2017~24 고정·상폐 편입) — 원판정
  issue111_minervini_transition_judge_20260818.json 을 supersede (소급 수정
  없음, 방향 뒤집힘 시 명시 기록 — 8차 ①).
- 예상 방향(사전 봉인 2026-08-24): 역효과 유지 또는 악화. 위반 → 채택 전
  버그 조사 강제 (8차 ②).
- 전환 정의 = 원판정과 동일(minervini_pass = c1~c8, F→T; 상폐는
  bt_delisted_indicators 의 c1~c8 동가 — rs_gate 미포함으로 등가 유지).
- 함수 재사용: extract_transitions·forward_excess·horizon_stats (복제 금지).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from itertools import groupby

import psycopg

from kr_pipeline.backtest.minervini_forward import (
    HORIZONS, PRIMARY_H, extract_transitions, forward_excess, horizon_stats,
    load_index_closes, load_markets, transition_events, verdict_of,
)

DB = "postgresql://localhost/kr_pipeline"
WIN = (date(2017, 1, 1), date(2024, 12, 31))
ORIGINAL = "data/backtest/issue111_minervini_transition_judge_20260818.json"
INDEX_OF = {"KOSPI": "1001", "KOSDAQ": "2001"}


def delisted_events(conn) -> list[dict]:
    idx = load_index_closes(conn)
    markets = load_markets(conn)
    events: list[dict] = []
    with conn.cursor(name="r111_delisted") as cur:
        cur.itersize = 50_000
        cur.execute(
            "SELECT g.ticker, g.date, p.adj_close, "
            "(c1 AND c2 AND c3 AND c4 AND c5 AND c6 AND c7 AND c8), NULL "
            "FROM bt_delisted_indicators g JOIN delisted_adj_prices p "
            "ON p.ticker = g.ticker AND p.date = g.date "
            "ORDER BY g.ticker, g.date")
        for ticker, grp in groupby(cur, key=lambda r: r[0]):
            rows = [(d, float(a), ps, cc) for _, d, a, ps, cc in grp]
            iclose = idx.get(INDEX_OF.get(markets.get(ticker) or "", "1001"), {})
            for i in extract_transitions(rows):
                ev = {"ticker": ticker, "date": rows[i][0].isoformat(),
                      "is_delisted": True}
                for h in HORIZONS:
                    x = forward_excess(rows, i, h, iclose)
                    if x is not None:
                        ev[f"excess_{h}"] = round(x, 4)
                events.append(ev)
    return events


def in_window(ev) -> bool:
    d = date.fromisoformat(ev["date"])
    return WIN[0] <= d <= WIN[1]


def main() -> int:
    with psycopg.connect(DB) as conn:
        surv_all, _excl = transition_events(conn)
        deli_all = delisted_events(conn)
    surv = [e for e in surv_all if in_window(e)]
    deli = [e for e in deli_all if in_window(e)]
    comb = surv + deli

    def block(events):
        p = horizon_stats(events, PRIMARY_H)
        return {"h20": p, "verdict_h20": verdict_of(*p["ci95"]) if p.get("n")
                else None,
                "h40": horizon_stats(events, 40),
                "h65": horizon_stats(events, 65)}

    orig = json.load(open(ORIGINAL))
    combined = block(comb)
    expectation_met = combined["verdict_h20"] == "역효과"
    out = {
        "label": "r111-v2 (2017~24 고정·상폐 편입) — 대체 측정, 탐색 등급",
        "supersedes": ORIGINAL,
        "expectation_sealed": "역효과 유지 또는 악화 (2026-08-24 사전 봉인)",
        "expectation_met": expectation_met,
        "generated": str(date.today()),
        "window": [str(WIN[0]), str(WIN[1])],
        "original_reference": {"n": orig["n_transitions_total"],
                               "h20": orig["primary_h20"],
                               "verdict": orig["verdict"]},
        "combined": {"n_transitions": len(comb), **combined},
        "survivors_only_window": {"n_transitions": len(surv), **block(surv)},
        "delisted_only": {"n_transitions": len(deli), **block(deli)},
    }
    path = f"data/backtest/issue118_r111_rerun_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ("combined", "survivors_only_window",
                                          "delisted_only", "expectation_met")},
                     ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
