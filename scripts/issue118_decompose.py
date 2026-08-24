"""#118 7차 ① — 미포착 승자 MECE 분해 + ② 잔여 런웨이 충분 포착률.

봉인 자구(설계 §5.5): 평가 시점 = 창 내 통과 조건 수(c1~c8) 최대 일(동수 →
anchor 최근접). A = c1~c5 실패 ≥2 / B = ¬A ∧ 총 실패=1 ∧ (c8 실패면 rs≥60)
/ C = 나머지(rs_gate 단독 실패·평가 불능 포함 — 구성비 보고). 검산 A+B+C =
미포착 전수. B 마진: 실패 조건의 임계 대비 상대 부족분(상폐는 c8 만 — 명기).
rs≥60 은 분류 전용. 런웨이 지표는 봉인 지위·라벨 자구로 출력.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

import pandas as pd
import psycopg

from kr_pipeline.backtest.p1_recall import pass_window

DB = "postgresql://localhost/kr_pipeline"
EP_CSV = "data/verification/issue115_p1_episodes_20260821.csv"
COLLAPSE = "data/verification/issue118_recall_collapse_20260822.json"

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


def margin_of(cond: str, row) -> float | None:
    """실패 조건의 임계 대비 상대 부족분(%) — 양수 = 부족 크기."""
    (_d, *_c, rs, close, s50, s150, s200, w52h, w52l) = row
    f = lambda x: float(x) if x is not None else None
    close, s50, s150, s200 = f(close), f(s50), f(s150), f(s200)
    w52h, w52l = f(w52h), f(w52l)
    try:
        if cond == "c8":
            return float(70 - rs) if rs is not None else None
        if cond == "c5" and close and s50:
            return round((s50 / close - 1) * 100, 3)
        if cond == "c1" and close and s150:
            return round((s150 / close - 1) * 100, 3)
        if cond == "c7" and close and w52h:
            return round((w52h * 0.75 / close - 1) * 100, 3)
        if cond == "c6" and close and w52l:
            return round((w52l * 1.25 / close - 1) * 100, 3)
        if cond == "c2" and s150 and s200:
            return round((s200 / s150 - 1) * 100, 3)
        if cond == "c4" and s50 and s150:
            return round((s150 / s50 - 1) * 100, 3)
    except (TypeError, ZeroDivisionError):
        return None
    return None                              # c3(추세 기울기) 등 — 마진 비정의


def main() -> int:
    eps = pd.read_csv(EP_CSV, dtype={"ticker": str})
    eps["anchor"] = pd.to_datetime(eps.anchor).dt.date
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT date FROM index_daily WHERE index_code='1001' "
                    "ORDER BY date")
        trading = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT ticker FROM delisted_adj_quality "
                    "WHERE (flags->>'stkdp_unresolved')::bool")
        carve = {r[0] for r in cur.fetchall()}

        buckets = Counter()
        b_fail_mix = Counter()
        c_mix = Counter()
        b_margins = defaultdict(list)
        n_missed = 0
        for r in eps.itertuples():
            dl = bool(r.is_delisted)
            if dl and r.ticker in carve:
                continue
            w = pass_window(trading, r.anchor)
            cur.execute(DEL_SQL if dl else SURV_SQL, (r.ticker, w))
            rows = cur.fetchall()
            # 게이트 통과(리콜 포착) 에피소드는 분해 대상 아님
            passed = any(all(bool(x) for x in row[1:10]) for row in rows)
            if passed:
                continue
            n_missed += 1
            if not rows:
                buckets["C"] += 1
                c_mix["평가불능(윈도우 무자료)"] += 1
                continue
            # 평가 시점: c1~c8 통과 수 최대, 동수 → anchor 최근접(최신일)
            best = max(rows, key=lambda row: (
                sum(1 for x in row[1:9] if x is True), row[0]))
            cs = {f"c{k}": (best[k] is True) for k in range(1, 9)}
            fails = [k for k, v in cs.items() if not v]
            rs_gate_ok = best[9] is True
            rs = best[10]
            n_c15 = sum(1 for k in ("c1", "c2", "c3", "c4", "c5") if not cs[k])
            if n_c15 >= 2:
                buckets["A"] += 1
            elif len(fails) == 1 and (fails[0] != "c8" or
                                      (rs is not None and rs >= 60)):
                buckets["B"] += 1
                b_fail_mix[fails[0]] += 1
                m = margin_of(fails[0], best)
                if m is not None:
                    b_margins[fails[0]].append(m)
                elif dl and fails[0] != "c8":
                    b_margins["_delisted_margin_na"].append(0)
            else:
                buckets["C"] += 1
                key = ("rs_gate단독" if not fails and not rs_gate_ok else
                       "+".join(fails[:3]) or "기타")
                c_mix[key] += 1

        collapse = json.load(open(COLLAPSE))
        lt = collapse["leadtime"]
        pre = collapse["recall_final"]["passed"]
        n_all = collapse["recall_final"]["judged"]
        runway = {
            "status": "기준선 관측 — 합격 임계 없음. 용도 = 재측정 비교·방향 일관성",
            "label": "필터 상태 기준 상한 — 운영 포착 아님",
            "pre_onset_rate": round(pre / n_all, 4),
            "midrun_runway_ge_20pp_rate": round(
                lt["mid_run"] * lt["midrun_residual_excess"]["share_ge_20pp"]
                / n_all, 4),
            "combined_upper_bound": round(
                (pre + lt["mid_run"] *
                 lt["midrun_residual_excess"]["share_ge_20pp"]) / n_all, 4),
            "note_absolute_descriptive": ("절대 ≥+20% 병기는 별도 산출 — 앵커 "
                                          "상수(시장초과 도메인)와 차원 상이 주석"),
        }

    total = sum(buckets.values())
    out = {
        "generated": str(date.today()),
        "missed_total": n_missed,
        "buckets": dict(buckets),
        "mece_check": {"sum": total, "equals_missed": total == n_missed},
        "B_fail_mix": dict(b_fail_mix),
        "B_margins": {k: {"n": len(v),
                          "median": round(float(pd.Series(v).median()), 3),
                          "p75": round(float(pd.Series(v).quantile(0.75)), 3)}
                      for k, v in b_margins.items() if v},
        "C_mix_top": dict(c_mix.most_common(10)),
        "runway_capture": runway,
    }
    path = f"data/verification/issue118_decompose_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False)[:1200])
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
