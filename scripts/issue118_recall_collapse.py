"""#118 사이클 1 — #115 리콜 구간 붕괴(스냅샷 1회·일자 각인) + 리드타임 분포.

- 상폐 승자 511건을 bt_delisted_indicators 게이트·5차 봉인 윈도우로 판정.
  carve(stkdp_unresolved) 종목 에피소드만 미판정 잔존. RS NaN 은 미충족
  취급(production 동형 — 설계 §1).
- 리드타임(6차 ②-(b) descriptive): 첫 게이트 통과일 ∈ [anchor−28, anchor+91],
  lead = (통과일−anchor)일. 중간 포착(lead≥0)의 잔여 시장초과 =
  통과일→anchor+13주(앵커 격자) 종목수익 − 시장수익 [판정 불입력].
- 절단 주석 상시(6차 ③): 말단 18~24개월 연도.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
import psycopg

from kr_pipeline.backtest.p1_recall import pass_window

DB = "postgresql://localhost/kr_pipeline"
EP_CSV = "data/verification/issue115_p1_episodes_20260821.csv"
IDX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}
UNB_SQL = ("SELECT MIN(date) FROM daily_indicators d "
           "JOIN bt_rs_daily b USING (ticker, date) "
           "WHERE ticker=%s AND date = ANY(%s) AND minervini_c1 AND minervini_c2 "
           "AND minervini_c3 AND minervini_c4 AND minervini_c5 AND minervini_c6 "
           "AND minervini_c7 AND rs_line_not_declining_7m AND b.rs_rating >= 70")
DEL_SQL = ("SELECT MIN(date) FROM bt_delisted_indicators "
           "WHERE ticker=%s AND date = ANY(%s) AND gate_pass")


def main() -> int:
    eps = pd.read_csv(EP_CSV, dtype={"ticker": str})
    eps["anchor"] = pd.to_datetime(eps.anchor).dt.date
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT MAX(date) FROM index_daily WHERE index_code='1001' "
                    "GROUP BY DATE_TRUNC('week', date) ORDER BY 1")
        anchors = [r[0] for r in cur.fetchall()]
        a_idx = {a: i for i, a in enumerate(anchors)}
        cur.execute("SELECT DISTINCT date FROM index_daily WHERE index_code='1001' "
                    "ORDER BY date")
        trading = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT index_code, date, close FROM index_daily")
        idx_close = defaultdict(dict)
        for code, d, c in cur.fetchall():
            idx_close[code][d] = float(c)
        cur.execute("SELECT ticker, market FROM stocks")
        mkt_of = dict(cur.fetchall())
        cur.execute("SELECT ticker FROM delisted_adj_quality "
                    "WHERE (flags->>'stkdp_unresolved')::bool")
        carve = {r[0] for r in cur.fetchall()}

        def price_at(t, dl, d):
            tbl = "delisted_adj_prices" if dl else "daily_prices"
            cur.execute(f"SELECT adj_close FROM {tbl} WHERE ticker=%s AND "
                        "date<=%s ORDER BY date DESC LIMIT 1", (t, d))
            r = cur.fetchone()
            return float(r[0]) if r else None

        # 1) 상폐 승자 판정 → 리콜 붕괴
        del_eps = eps[eps.is_delisted]
        del_pass = del_unjudged = 0
        for r in del_eps.itertuples():
            if r.ticker in carve:
                del_unjudged += 1
                continue
            w = pass_window(trading, r.anchor)
            cur.execute(DEL_SQL, (r.ticker, w))
            if cur.fetchone()[0] is not None:
                del_pass += 1
        surv = eps[~eps.is_delisted]
        surv_pass = int(surv.unbiased_pass.fillna(False).astype(bool).sum())
        n_all = len(eps)
        judged = n_all - del_unjudged
        passed = surv_pass + del_pass
        recall_point = passed / judged if judged else None
        interval = (passed / n_all, (passed + del_unjudged) / n_all)

        # 2) 리드타임 분포 (전 에피소드)
        leads = []
        midrun = []
        for r in eps.itertuples():
            dl = bool(r.is_delisted)
            if dl and r.ticker in carve:
                continue
            lo = r.anchor - timedelta(days=28)
            hi = r.anchor + timedelta(days=91)
            span = [d for d in trading if lo < d <= hi]
            cur.execute(DEL_SQL if dl else UNB_SQL, (r.ticker, span))
            first = cur.fetchone()[0]
            if first is None:
                leads.append(None)
                continue
            lead = (first - r.anchor).days
            leads.append(lead)
            if lead >= 0:
                i = a_idx.get(r.anchor)
                if i is None or i + 13 >= len(anchors):
                    continue
                h = anchors[i + 13]
                m = IDX_CODE.get(mkt_of.get(r.ticker) or "KOSPI", "1001")
                p0, p1 = price_at(r.ticker, dl, first), price_at(r.ticker, dl, h)
                x0, x1 = idx_close[m].get(first), idx_close[m].get(h)
                if p0 and p1 and x0 and x1:
                    midrun.append((p1 / p0 - 1) - (x1 / x0 - 1))

        lead_vals = [x for x in leads if x is not None]
        s = pd.Series(lead_vals)
        mr = pd.Series(midrun)
        out = {
            "snapshot_date": str(date.today()),
            "snapshot_note": "6차 ③ — 스냅샷 1회·일자 각인, 연속 갱신 없음",
            "truncation_note": ("말단 18~24개월(2025~26) 연도별 리콜은 상폐 지연 "
                                "우측 절단 주석 상시 부착 대상"),
            "recall_final": {
                "headline_label": (
                    f"통합 승자 리콜 {recall_point:.4f} (미판정 carve 에피소드 "
                    f"{del_unjudged}건 — 구간 [{interval[0]:.4f}, {interval[1]:.4f}])"),
                "judged": judged, "passed": passed,
                "survivors": {"n": len(surv), "passed": surv_pass},
                "delisted": {"n": len(del_eps), "passed": del_pass,
                             "unjudged_carve": del_unjudged,
                             "recall": round(del_pass / (len(del_eps) - del_unjudged), 4)
                             if len(del_eps) > del_unjudged else None},
            },
            "leadtime": {
                "n_episodes": len(leads),
                "caught_any_in_[-28,+91]": len(lead_vals),
                "caught_share": round(len(lead_vals) / len(leads), 4),
                "pre_onset": sum(1 for x in lead_vals if x < 0),
                "mid_run": sum(1 for x in lead_vals if x >= 0),
                "lead_days_quantiles": {
                    q: float(s.quantile(q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)
                } if len(s) else {},
                "midrun_residual_excess": {
                    "n": len(mr),
                    "median_pct": round(float(mr.median()) * 100, 2) if len(mr) else None,
                    "share_ge_20pp": round(float((mr >= 0.20).mean()), 4) if len(mr) else None,
                    "share_ge_0": round(float((mr >= 0).mean()), 4) if len(mr) else None,
                },
            },
        }
    path = f"data/verification/issue118_recall_collapse_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out["recall_final"], ensure_ascii=False))
    print(json.dumps(out["leadtime"], ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
