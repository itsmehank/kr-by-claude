"""#115 P1 — 승자 리콜·후보 축소율 측정 러너 (5차 승인 설계 v2, 로컬 DB 전용).

- 창: anchor 2017-01-01~2026-06-30 (ISO 주 마지막 거래일, KOSPI 1001 기준).
- 유니버스: 생존(daily_prices) ∪ 상폐(delisted_adj_prices, carve 5 제외 —
  소비 한정 해제 2호). 상폐 liq_window 행은 anchor 시작점 금지(5차 ①).
- 승자: 봉인 정의(T13 +40%p/T26 +50%p·절대>0·유동성 10억 = anchor 전후
  20거래일 평균 거래대금[에피소드 기준 적응 — 보고 명기]). 우측 절단 봉인 규칙.
- 리콜: 통과 윈도우 (anchor−28, anchor) 개구간. 실전/무편향 이중, 판정=무편향.
  상폐 승자 미판정 → 구간 보고. 게이트 상이 명단·방향 표.
- 축소율: anchor 주별 통과/유니버스 — 실전·무편향, 분모 생존/전체 병기.
- 홀드아웃 규율: 트레이드 시뮬 수치 산출 없음(원장 2행 (iii)).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
import psycopg

from kr_pipeline.backtest.p1_recall import (
    interval_recall, merge_episodes, pass_window, winner_cells_sealed,
)

DB = "postgresql://localhost/kr_pipeline"
WIN_START, WIN_END = date(2017, 1, 1), date(2026, 6, 30)
LIQ_MIN = 1_000_000_000
IDX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}


def load_anchors(cur) -> list[date]:
    cur.execute("SELECT MAX(date) FROM index_daily WHERE index_code='1001' "
                "GROUP BY DATE_TRUNC('week', date) ORDER BY 1")
    return [r[0] for r in cur.fetchall()]


def rolling_liq(dates: list[date], values: list[float]) -> dict[date, float]:
    s = pd.Series(values, index=dates, dtype=float)
    m = s.rolling(41, center=True, min_periods=10).mean()
    return m.to_dict()


def main() -> int:
    out = {"generated": str(date.today()), "window": [str(WIN_START), str(WIN_END)]}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        anchors = load_anchors(cur)
        a_idx = {a: i for i, a in enumerate(anchors)}
        start_ok = [a for a in anchors if WIN_START <= a <= WIN_END]
        # 우측 절단 봉인: 13주(26주) 오프셋 anchor 존재해야 해당 지표 평가
        n13_cut = sum(1 for a in start_ok if a_idx[a] + 13 >= len(anchors))
        n26_cut = sum(1 for a in start_ok if a_idx[a] + 26 >= len(anchors))
        out["right_censor"] = {"anchors_in_window": len(start_ok),
                               "no_13w": n13_cut, "no_26w": n26_cut}

        cur.execute("SELECT index_code, date, close FROM index_daily")
        idx_close: dict[str, dict[date, float]] = defaultdict(dict)
        for code, d, c in cur.fetchall():
            idx_close[code][d] = float(c)
        cur.execute("SELECT ticker, market, delisted_at FROM stocks")
        meta = {t: (m, dl) for t, m, dl in cur.fetchall()}
        cur.execute("SELECT ticker FROM delisted_adj_quality "
                    "WHERE (flags->>'stkdp_unresolved')::bool")
        carve = {r[0] for r in cur.fetchall()}

        anchor_set = set(anchors)
        episodes = []                        # (ticker, is_delisted, start_anchor)
        for src, delisted in (("live", False), ("del", True)):
            if delisted:
                cur.execute(
                    "SELECT p.ticker, p.date, p.adj_close, p.liq_window, r.value "
                    "FROM delisted_adj_prices p JOIN delisted_daily_prices r "
                    "USING (ticker, date) ORDER BY p.ticker, p.date")
            else:
                cur.execute(
                    "SELECT ticker, date, adj_close, false, value FROM daily_prices "
                    "WHERE adj_close > 0 ORDER BY ticker, date")
            rows = cur.fetchall()
            i = 0
            while i < len(rows):
                t = rows[i][0]
                j = i
                while j < len(rows) and rows[j][0] == t:
                    j += 1
                if delisted and t in carve:
                    i = j
                    continue
                mkt = meta.get(t, ("KOSPI", None))[0] or "KOSPI"
                idxm = idx_close.get(IDX_CODE.get(mkt, "1001"), {})
                ds = [r[1] for r in rows[i:j]]
                closes = {r[1]: float(r[2]) for r in rows[i:j]}
                liq_flags = {r[1]: r[3] for r in rows[i:j]}
                liq_avg = rolling_liq(ds, [float(r[4] or 0) for r in rows[i:j]])

                def liq_ok(a, _avg=liq_avg, _lf=liq_flags, _del=delisted):
                    if _del and _lf.get(a):
                        return False        # 5차 ①: 정리매매 행 anchor 금지
                    v = _avg.get(a)
                    return v is not None and v >= LIQ_MIN

                cells = winner_cells_sealed(
                    anchors, closes, idxm, idx13=13, idx26=26, liq_ok=liq_ok)
                cells = [c for c in cells if WIN_START <= anchors[c] <= WIN_END]
                for s, _e in merge_episodes(cells):
                    episodes.append((t, delisted, anchors[s]))
                i = j

        out["episodes"] = {
            "total": len(episodes),
            "delisted": sum(1 for _, dl, _a in episodes if dl),
            "by_year": {}, "delisted_by_year": {},
        }
        for _, dl, a in episodes:
            y = str(a.year)
            out["episodes"]["by_year"][y] = out["episodes"]["by_year"].get(y, 0) + 1
            if dl:
                out["episodes"]["delisted_by_year"][y] = \
                    out["episodes"]["delisted_by_year"].get(y, 0) + 1

        # 통과 상태 (생존 승자만 판정) — 실전 / 무편향
        cur.execute("SELECT DISTINCT date FROM index_daily WHERE index_code='1001' "
                    "ORDER BY date")
        trading = [r[0] for r in cur.fetchall()]
        surv = [(t, a) for t, dl, a in episodes if not dl]
        passed_live = passed_unb = 0
        disagree = []
        ep_rows = []                         # per-episode 원장(CSV — #118 갱신 대비)
        by_year_pass = defaultdict(lambda: [0, 0])   # year -> [unb_passed, n]
        sens = {7: [0, 0], 91: [0, 0]}       # descriptive 민감도(무편향 기준)
        for t, a in surv:
            w = pass_window(trading, a)
            if not w:
                continue
            cur.execute(
                "SELECT bool_or(minervini_pass AND rs_line_not_declining_7m), "
                "bool_or(minervini_c1 AND minervini_c2 AND minervini_c3 AND "
                "minervini_c4 AND minervini_c5 AND minervini_c6 AND minervini_c7 "
                "AND rs_line_not_declining_7m AND b.rs_rating >= 70) "
                "FROM daily_indicators d JOIN bt_rs_daily b USING (ticker, date) "
                "WHERE ticker=%s AND date = ANY(%s)", (t, w))
            live_p, unb_p = cur.fetchone()
            live_p, unb_p = bool(live_p), bool(unb_p)
            passed_live += live_p
            passed_unb += unb_p
            by_year_pass[a.year][0] += unb_p
            by_year_pass[a.year][1] += 1
            ep_rows.append((t, a.isoformat(), False, live_p, unb_p))
            if live_p != unb_p:
                disagree.append({"ticker": t, "anchor": a.isoformat(),
                                 "direction": "live_only" if live_p else "unbiased_only"})
            for days in sens:
                ws = pass_window(trading, a, days=days)
                if ws:
                    cur.execute(
                        "SELECT bool_or(minervini_c1 AND minervini_c2 AND "
                        "minervini_c3 AND minervini_c4 AND minervini_c5 AND "
                        "minervini_c6 AND minervini_c7 AND "
                        "rs_line_not_declining_7m AND b.rs_rating >= 70) "
                        "FROM daily_indicators d JOIN bt_rs_daily b "
                        "USING (ticker, date) WHERE ticker=%s AND date=ANY(%s)",
                        (t, ws))
                    if bool(cur.fetchone()[0]):
                        sens[days][0] += 1
                    sens[days][1] += 1

        n_del = sum(1 for _, dl, _a in episodes if dl)
        out["recall"] = {
            "judgment_input": "unbiased",
            "unbiased": interval_recall(passed=passed_unb, survivors=len(surv),
                                        delisted=n_del),
            "live_gate": interval_recall(passed=passed_live, survivors=len(surv),
                                         delisted=n_del),
            "gate_disagreements": disagree,
            "window_sensitivity_unbiased": {
                str(k): (v[0] / v[1] if v[1] else None) for k, v in sens.items()},
            "unbiased_by_year": {
                str(y): {"passed": v[0], "n": v[1],
                         "recall": round(v[0] / v[1], 4) if v[1] else None}
                for y, v in sorted(by_year_pass.items())},
            # 5차 ⑥: recall 감사 부분창(2025-01~2026-06) 별도 표기
            "audit_subwindow_2025plus": {
                "passed": sum(v[0] for y, v in by_year_pass.items() if y >= 2025),
                "n": sum(v[1] for y, v in by_year_pass.items() if y >= 2025),
            },
        }
        sw = out["recall"]["audit_subwindow_2025plus"]
        sw["recall"] = round(sw["passed"] / sw["n"], 4) if sw["n"] else None
        for t, dl, a in episodes:
            if dl:
                ep_rows.append((t, a.isoformat(), True, None, None))
        pd.DataFrame(ep_rows, columns=["ticker", "anchor", "is_delisted",
                                       "live_pass", "unbiased_pass"]).to_csv(
            f"data/verification/issue115_p1_episodes_{date.today():%Y%m%d}.csv",
            index=False)

        # 후보 축소율 — anchor 주별
        red = []
        for a in start_ok:
            cur.execute(
                "SELECT COUNT(*) FILTER (WHERE minervini_pass AND "
                "rs_line_not_declining_7m), "
                "COUNT(*) FILTER (WHERE minervini_c1 AND minervini_c2 AND "
                "minervini_c3 AND minervini_c4 AND minervini_c5 AND minervini_c6 "
                "AND minervini_c7 AND rs_line_not_declining_7m AND "
                "b.rs_rating >= 70), COUNT(*) "
                "FROM daily_indicators d JOIN bt_rs_daily b USING (ticker, date) "
                "WHERE date=%s", (a,))
            live_n, unb_n, denom_surv = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM delisted_adj_prices WHERE date=%s", (a,))
            denom_del = cur.fetchone()[0]
            red.append((a, live_n, unb_n, denom_surv, denom_surv + denom_del))
        by_year = defaultdict(lambda: [0, 0, 0, 0, 0])
        for a, ln, un, ds_, dt_ in red:
            b = by_year[a.year]
            b[0] += ln; b[1] += un; b[2] += ds_; b[3] += dt_; b[4] += 1
        out["reduction"] = {
            str(y): {"live_pct_of_judgeable": round(v[0] / v[2] * 100, 2),
                     "unbiased_pct_of_judgeable": round(v[1] / v[2] * 100, 2),
                     "unbiased_pct_of_all_traded": round(v[1] / v[3] * 100, 2)}
            for y, v in sorted(by_year.items()) if v[2]}

    path = f"data/verification/issue115_p1_recall_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "reduction"} |
                     {"recall_headline": out["recall"]["unbiased"]["headline"],
                      "gate_disagreements": len(out["recall"]["gate_disagreements"])},
                     ensure_ascii=False, default=str)[:1500])
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
