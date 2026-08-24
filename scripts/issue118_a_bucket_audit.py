"""#118 부속 — A 버킷(의도된 포기) 내부 감사 [descriptive·판정 비입력].

질문(사용자): A 79.3% 가 (i) 실제로 Stage 2 미확립이라 안 잡은 것인지
(ii) 템플릿 구현 오류인지. 측정:
1. A 에피소드의 평가 시점 실패 조건 조합 구성비 (c1~c5 축 — 구조 조건).
2. A 에피소드를 템플릿이 시세 도중([anchor, anchor+91일])에라도 잡았는가 —
   '완전한 Stage 2 진입 후 늦게 포착' 설계의 작동 증거.
3. 수동 점검 표본 20건 (ticker, anchor, 평가일, 실패 조건, 값 스냅샷).
분해 정의·평가 시점 규칙 = 7차 봉인 자구 동일(재사용).
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from datetime import date, timedelta

import pandas as pd
import psycopg

from kr_pipeline.backtest.p1_recall import pass_window

DB = "postgresql://localhost/kr_pipeline"
EP_CSV = "data/verification/issue115_p1_episodes_20260821.csv"

SURV_SQL = (
    "SELECT d.date, minervini_c1, minervini_c2, minervini_c3, minervini_c4, "
    "minervini_c5, minervini_c6, minervini_c7, (b.rs_rating >= 70), "
    "rs_line_not_declining_7m, b.rs_rating, d.adj_close, d.sma_50, d.sma_150, "
    "d.sma_200, d.w52_high, d.w52_low "
    "FROM daily_indicators d JOIN bt_rs_daily b USING (ticker, date) "
    "WHERE ticker=%s AND date = ANY(%s) ORDER BY date")
DEL_SQL = (
    "SELECT g.date, c1, c2, c3, c4, c5, c6, c7, c8, rs_gate, b.rs_rating, "
    "NULL, NULL, NULL, NULL, NULL, NULL "
    "FROM bt_delisted_indicators g LEFT JOIN bt_rs_daily b "
    "ON b.ticker = g.ticker AND b.date = g.date "
    "WHERE g.ticker=%s AND g.date = ANY(%s) ORDER BY g.date")
GATE_SURV = (
    "SELECT MIN(date) FROM daily_indicators d JOIN bt_rs_daily b "
    "USING (ticker, date) WHERE ticker=%s AND date = ANY(%s) AND minervini_c1 "
    "AND minervini_c2 AND minervini_c3 AND minervini_c4 AND minervini_c5 AND "
    "minervini_c6 AND minervini_c7 AND rs_line_not_declining_7m "
    "AND b.rs_rating >= 70")
GATE_DEL = ("SELECT MIN(date) FROM bt_delisted_indicators WHERE ticker=%s "
            "AND date = ANY(%s) AND gate_pass")


def main() -> int:
    rng = random.Random(20260824)
    eps = pd.read_csv(EP_CSV, dtype={"ticker": str})
    eps["anchor"] = pd.to_datetime(eps.anchor).dt.date
    combo = Counter()
    later = {"caught_midrun": 0, "never_in_run": 0}
    samples = []
    n_a = 0
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT date FROM index_daily WHERE index_code='1001' "
                    "ORDER BY date")
        trading = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT ticker FROM delisted_adj_quality "
                    "WHERE (flags->>'stkdp_unresolved')::bool")
        carve = {r[0] for r in cur.fetchall()}
        for r in eps.itertuples():
            dl = bool(r.is_delisted)
            if dl and r.ticker in carve:
                continue
            w = pass_window(trading, r.anchor)
            cur.execute(DEL_SQL if dl else SURV_SQL, (r.ticker, w))
            rows = cur.fetchall()
            if not rows:
                continue
            if any(all(bool(x) for x in row[1:10]) for row in rows):
                continue
            best = max(rows, key=lambda row: (
                sum(1 for x in row[1:9] if x is True), row[0]))
            fails15 = [f"c{k}" for k in range(1, 6) if best[k] is not True]
            if len(fails15) < 2:
                continue                     # A 버킷만
            n_a += 1
            combo["+".join(fails15)] += 1
            run = [d for d in trading
                   if r.anchor <= d <= r.anchor + timedelta(days=91)]
            cur.execute(GATE_DEL if dl else GATE_SURV, (r.ticker, run))
            first = cur.fetchone()[0]
            later["caught_midrun" if first else "never_in_run"] += 1
            if len(samples) < 400 and rng.random() < 0.1:
                samples.append({
                    "ticker": r.ticker, "anchor": r.anchor.isoformat(),
                    "eval_date": best[0].isoformat(), "fails_c1_5": fails15,
                    "close": str(best[11]), "sma150": str(best[13]),
                    "sma200": str(best[14]), "w52_high": str(best[15]),
                    "midrun_first_pass": first.isoformat() if first else None,
                    "is_delisted": dl})
    rng.shuffle(samples)
    out = {"generated": str(date.today()),
           "grade": "descriptive — 판정 비입력 (7차 분해 정의 재사용)",
           "n_A": n_a,
           "fail_combo_top": dict(combo.most_common(12)),
           "later_catch": {**later,
                           "caught_midrun_share": round(
                               later["caught_midrun"] / n_a, 4) if n_a else None},
           "manual_samples_20": samples[:20]}
    path = f"data/verification/issue118_a_bucket_audit_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "manual_samples_20"},
                     ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
