"""#118 체크리스트 2 — #117 재실행 (r117-v2, 탐색 등급·읽기전용).

- 대체 측정: 원분석 exploratory_issue111_transition_robustness_20260818 을
  supersede 후보(판정은 세션). 상폐 편입 + 좌측 절단 완화("2018-01-01 이후
  첫 전환만" — 데이터 시작 후 ≥1.5년 확보 종목의 진짜 첫 전환).
- 10차 지침: 기간 분해(2017~24 / 2025~26) 사전 보고 승격. 봉인 방향
  "반복 전환이 평균 지배(첫 전환만 우위) 구조 유지"는 통합·기간별 각각 판정.
- 함수 재사용: extract_transitions·forward_excess·horizon_stats.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from itertools import groupby

import psycopg

from kr_pipeline.backtest.minervini_forward import (
    extract_transitions, forward_excess, horizon_stats, iter_ticker_rows,
    load_index_closes, load_markets,
)

DB = "postgresql://localhost/kr_pipeline"
COOLDOWN_ROWS = 63
FIRST_MIN_DATE = date(2018, 1, 1)
P17_24 = (date(2017, 1, 1), date(2024, 12, 31))
P25_26 = (date(2025, 1, 1), date(2026, 12, 31))
INDEX_OF = {"KOSPI": "1001", "KOSDAQ": "2001"}


def cooldown_filter(transitions: list[int], min_gap: int = COOLDOWN_ROWS):
    out = []
    for i in transitions:
        if not out or i - out[-1] >= min_gap:
            out.append(i)
    return out


def collect(conn) -> list[dict]:
    idx = load_index_closes(conn)
    markets = load_markets(conn)
    events = []

    def handle(ticker, rows, delisted):
        iclose = idx.get(INDEX_OF.get(markets.get(ticker) or "", "1001"), {})
        tr = extract_transitions(rows)
        cd = set(cooldown_filter(tr))
        first_i = tr[0] if tr else None
        for i in tr:
            x = forward_excess(rows, i, 20, iclose)
            if x is None:
                continue
            d = rows[i][0]
            events.append({
                "ticker": ticker, "date": d.isoformat(), "excess_20": round(x, 4),
                "is_delisted": delisted, "cooldown": i in cd,
                "first": (i == first_i and d >= FIRST_MIN_DATE),
            })

    for ticker, rows in iter_ticker_rows(conn):
        handle(ticker, rows, False)
    with conn.cursor(name="r117_delisted") as cur:
        cur.itersize = 50_000
        cur.execute(
            "SELECT g.ticker, g.date, p.adj_close, "
            "(c1 AND c2 AND c3 AND c4 AND c5 AND c6 AND c7 AND c8), NULL "
            "FROM bt_delisted_indicators g JOIN delisted_adj_prices p "
            "ON p.ticker = g.ticker AND p.date = g.date "
            "ORDER BY g.ticker, g.date")
        for ticker, grp in groupby(cur, key=lambda r: r[0]):
            rows = [(d, float(a), ps, cc) for _, d, a, ps, cc in grp]
            handle(ticker, rows, True)
    return events


def in_p(ev, p):
    d = date.fromisoformat(ev["date"])
    return p[0] <= d <= p[1]


def main() -> int:
    with psycopg.connect(DB) as conn:
        events = collect(conn)
    variants = {
        "all": events,
        "cooldown63": [e for e in events if e["cooldown"]],
        "first_ge2018": [e for e in events if e["first"]],
    }
    periods = {"2017_24": P17_24, "2025_26": P25_26}
    out = {"label": "r117-v2 (상폐 편입·좌측 절단 완화) — 탐색 등급",
           "supersede_candidate":
               "exploratory_issue111_transition_robustness_20260818.json",
           "expectation_sealed": "반복 전환이 평균 지배(첫 전환만 우위) 구조 "
                                 "유지 — 통합·기간별 각각 판정 (10차)",
           "generated": str(date.today()), "blocks": {}}
    for vname, evs in variants.items():
        out["blocks"][vname] = {"combined_2017_24": horizon_stats(
            [e for e in evs if in_p(e, P17_24)], 20)}
        for pname, p in periods.items():
            out["blocks"][vname][pname] = horizon_stats(
                [e for e in evs if in_p(e, p)], 20)
    # 봉인 방향 판정: first_ge2018 mean > all mean (반복 지배 = 전체가 더 낮음)
    checks = {}
    for pname in ("2017_24", "2025_26"):
        fa = out["blocks"]["first_ge2018"][pname]
        al = out["blocks"]["all"][pname]
        checks[pname] = (fa.get("mean") is not None and al.get("mean") is not None
                         and fa["mean"] > al["mean"])
    out["expectation_met"] = {"by_period": checks, "all_hold": all(checks.values())}
    path = f"data/backtest/issue118_r117_rerun_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False)[:1400])
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
