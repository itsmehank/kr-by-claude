"""#115 6차 ①-1 — 플라시보 anchor 기준선 + lift (로컬 DB 전용).

지위(봉인, 산출 전): 진단 통계 — 합격 임계 없음. 단 lift CI 가 1 을 포함하면
임계 조정 사이클 개시 전 원인 규명 강제.

설계(설계 문서 v3 봉인): 동일 기계(4주 개구간 윈도우·무편향 게이트 bool_or),
연도×시장 매칭 무작위 (종목, anchor) 드로우 5개/에피소드, SEED=20260822.
lift = 생존 승자 리콜 / 플라시보 통과율. CI = ticker 클러스터 부트스트랩
(양측 재표집 1,000회, 2.5/97.5 분위).

병기(①-2): 연도별 포착 승자 건수 + 주말 후보 수 절대값(흐름 충분성).
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from datetime import date

import pandas as pd
import psycopg

from kr_pipeline.backtest.p1_recall import pass_window

DB = "postgresql://localhost/kr_pipeline"
SEED = 20260822
DRAWS_PER_EP = 5
BOOT = 1000
EP_CSV = "data/verification/issue115_p1_episodes_20260821.csv"
WIN_START, WIN_END = date(2017, 1, 1), date(2026, 6, 30)

UNB_SQL = ("SELECT bool_or(minervini_c1 AND minervini_c2 AND minervini_c3 AND "
           "minervini_c4 AND minervini_c5 AND minervini_c6 AND minervini_c7 "
           "AND rs_line_not_declining_7m AND b.rs_rating >= 70) "
           "FROM daily_indicators d JOIN bt_rs_daily b USING (ticker, date) "
           "WHERE ticker=%s AND date = ANY(%s)")


def main() -> int:
    rng = random.Random(SEED)
    eps = pd.read_csv(EP_CSV, dtype={"ticker": str})
    surv = eps[~eps.is_delisted].copy()
    surv["anchor"] = pd.to_datetime(surv.anchor).dt.date
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT MAX(date) FROM index_daily WHERE index_code='1001' "
                    "GROUP BY DATE_TRUNC('week', date) ORDER BY 1")
        anchors = [r[0] for r in cur.fetchall()]
        start_ok = [a for a in anchors if WIN_START <= a <= WIN_END]
        anchors_by_year = defaultdict(list)
        for a in start_ok:
            anchors_by_year[a.year].append(a)
        cur.execute("SELECT DISTINCT date FROM index_daily WHERE index_code='1001' "
                    "ORDER BY date")
        trading = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT ticker, market FROM stocks WHERE delisted_at IS NULL")
        mkt_of = dict(cur.fetchall())
        by_mkt = defaultdict(list)
        for t, m in mkt_of.items():
            by_mkt[m or "KOSPI"].append(t)
        for v in by_mkt.values():
            v.sort()
        winner_cells = {(r.ticker, r.anchor) for r in surv.itertuples()}

        placebo_rows = []                    # (ticker, year, passed)
        cache: dict[tuple, bool] = {}
        for r in surv.itertuples():
            m = mkt_of.get(r.ticker) or "KOSPI"
            pool = by_mkt.get(m) or by_mkt["KOSPI"]
            year_anchors = anchors_by_year[r.anchor.year]
            n = 0
            while n < DRAWS_PER_EP:
                t2 = rng.choice(pool)
                a2 = rng.choice(year_anchors)
                if (t2, a2) in winner_cells:
                    continue
                key = (t2, a2)
                if key not in cache:
                    w = pass_window(trading, a2)
                    if not w:
                        cache[key] = False
                    else:
                        cur.execute(UNB_SQL, (t2, w))
                        cache[key] = bool(cur.fetchone()[0])
                placebo_rows.append((t2, a2.year, cache[key]))
                n += 1

        # 실측 승자 통과(에피소드 원장에서) + 클러스터 부트스트랩
        win_by_ticker = defaultdict(list)
        for r in surv.itertuples():
            win_by_ticker[r.ticker].append(bool(r.unbiased_pass))
        pla_by_ticker = defaultdict(list)
        for t, _y, p in placebo_rows:
            pla_by_ticker[t].append(p)
        w_keys, p_keys = list(win_by_ticker), list(pla_by_ticker)
        recall = sum(sum(v) for v in win_by_ticker.values()) / len(surv)
        placebo = sum(sum(v) for v in pla_by_ticker.values()) / len(placebo_rows)
        lifts = []
        for _ in range(BOOT):
            ws = [win_by_ticker[rng.choice(w_keys)] for _ in w_keys]
            ps = [pla_by_ticker[rng.choice(p_keys)] for _ in p_keys]
            wn = sum(len(x) for x in ws)
            pn = sum(len(x) for x in ps)
            wr = sum(sum(x) for x in ws) / wn if wn else 0
            pr = sum(sum(x) for x in ps) / pn if pn else 0
            if pr > 0:
                lifts.append(wr / pr)
        lifts.sort()
        ci = (lifts[int(0.025 * len(lifts))], lifts[int(0.975 * len(lifts))])

        # ①-2 기회 흐름 절대량: 연도별 포착 승자 수 + 주말 후보 수
        flow = {}
        cur.execute(
            "SELECT EXTRACT(year FROM date)::int, COUNT(*), COUNT(DISTINCT date) "
            "FROM daily_indicators d JOIN bt_rs_daily b USING (ticker, date) "
            "WHERE minervini_c1 AND minervini_c2 AND minervini_c3 AND minervini_c4 "
            "AND minervini_c5 AND minervini_c6 AND minervini_c7 "
            "AND rs_line_not_declining_7m AND b.rs_rating >= 70 "
            "AND date = ANY(%s) GROUP BY 1 ORDER BY 1", (start_ok,))
        for y, npass, nweeks in cur.fetchall():
            flow[str(y)] = {"weekly_candidates_mean": round(npass / nweeks, 1)}
        for r in surv.itertuples():
            y = str(r.anchor.year)
            if y in flow:
                flow[y]["winners_caught"] = flow[y].get("winners_caught", 0) + \
                    int(bool(r.unbiased_pass))

    out = {
        "generated": str(date.today()), "seed": SEED,
        "status": ("진단 통계 — 합격 임계 없음. lift CI 가 1 포함 시 임계 조정 "
                   "사이클 개시 전 원인 규명 강제 (6차 봉인)"),
        "recall_survivors": round(recall, 4),
        "placebo_rate": round(placebo, 4),
        "placebo_draws": len(placebo_rows),
        "lift": round(recall / placebo, 3) if placebo else None,
        "lift_ci95_cluster_bootstrap": [round(ci[0], 3), round(ci[1], 3)],
        "ci_includes_1": bool(ci[0] <= 1.0 <= ci[1]),
        "flow_by_year": flow,
    }
    path = f"data/verification/issue115_p1_placebo_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "flow_by_year"},
                     ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
