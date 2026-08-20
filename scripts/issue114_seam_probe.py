"""#114 세그먼트 게이트 재현 + 잔여 27% 오차 시작점 분석 (read-only 진단).

1) 게이트 재현: 절단 = 미해결(분류 원장 rows) ∪ 비정밀(gap_fallback·유상 갭)
   → 봉인 수치(issue114_segment_gate_v2_20260819.json)와 완전 일치 확인.
2) 잔여 종목(세그먼트 p99>1%): 오차 스텝(|Δlog q|>0.5%) 날짜를 찾아
   근접 증거(재구성 이벤트/주식수 이벤트/공시/detail ≤7일)와의 거리 +
   달력일 클러스터링(수집 이음새 시그니처) 측정 → 유형 분류:
   event_residual(증거 인접) / stock_div(연말 배당락 창 무증거) / small_isolated.
3) stock_div 확증: 스텝 이후 180일 내(주총 후 4월 신주상장) 동일 비율
   주식수 증가 매칭 + 반사실 컷 [diagnostic-upper-bound](주식배당 스텝 절단 시
   p99 붕괴 여부).

판정(2026-08-19 실측): pykrx 수집 이음새 가설 기각 — 스텝은 매년 배당락일
(12/27~29)과 실제 이벤트 인접에 집중, 수집일 클러스터링 없음.
"""
from __future__ import annotations

import bisect
import json
import math
import sys
from collections import Counter
from datetime import date

import psycopg

from kr_pipeline.ohlcv.adj_reconstruct import (  # noqa: E402
    MIN_CHANGE, db_factor_jumps, factor_curve, share_events,
)

DB = "postgresql://localhost/kr_pipeline"
ROOT = "."
SCOPE = f"{ROOT}/data/verification/issue114_survivor_scope.json"
LEDGER = f"{ROOT}/data/verification/issue114_residual_classify_20260819.json"
WARMUP = 252
BIG_GAP, MATCH_TOL, WINDOW = 1.35, 1.4, 45
V5 = "--v5" in sys.argv                     # v4.1 + 주식배당 detail (11차)


def load(cur, t):
    cur.execute("SELECT date, close, adj_close FROM daily_prices WHERE ticker=%s "
                "AND close>0 AND adj_close>0 ORDER BY date", (t,))
    rows = cur.fetchall()
    closes = [(d, float(c)) for d, c, _ in rows]
    adj = {d: float(a) for d, _, a in rows}
    cur.execute("SELECT date, shares FROM share_counts WHERE ticker=%s ORDER BY date", (t,))
    shares = {d: int(s) for d, s in cur.fetchall()}
    cur.execute("SELECT endpoint, record_date, ratio::float, method, rcept_no "
                "FROM corp_action_details WHERE ticker=%s", (t,))
    details = [{"endpoint": e, "record_date": rd, "ratio": rt, "method": m,
                "rcept_no": rc} for e, rd, rt, m, rc in cur.fetchall()]
    cur.execute("SELECT event_type, event_date FROM corporate_actions WHERE ticker=%s", (t,))
    actions = cur.fetchall()
    return closes, adj, shares, details, actions


def v3_events_tagged(closes, shares, details):
    """adj_reconstruct.v3_events(use_cr=False) 동일 로직 + provenance 태그."""
    dates = [d for d, _ in closes]
    close_of = dict(closes)
    se = share_events(sorted(shares), shares)
    events = []  # (date, ratio, prov)
    used = set()
    for i in range(1, len(closes)):
        _, c_prev = closes[i - 1]
        d, c = closes[i]
        if c_prev <= 0 or c <= 0:
            continue
        g = c / c_prev
        if abs(math.log(g)) <= math.log(BIG_GAP):
            continue
        best = None
        for j, (ds, rs) in enumerate(se):
            if j in used or rs <= 0 or abs((ds - d).days) > WINDOW:
                continue
            dist = abs(math.log(rs) - math.log(g))
            if dist < math.log(MATCH_TOL) and (best is None or dist < best[0]):
                best = (dist, j, rs)
        if best is not None:
            used.add(best[1])
            events.append((d, best[2], "gap_share"))
        else:
            events.append((d, g, "gap_fallback"))

    big_dates = [d for d, _, _ in events]
    cands = []
    for det in details:
        rd = det.get("record_date")
        ep = det.get("endpoint", "")
        if rd is None or ep == "crDecsn":
            continue
        if ep == "stkdpDecsn":
            if not V5 or not det.get("ratio") or det["ratio"] <= 0:
                continue
            rc = det.get("rcept_no") or ""
            if rc[:8] > rd.strftime("%Y%m%d"):
                continue                    # 기준일 후 접수 — 참조는 원공시로 조정
            cands.append(("stkdp", rd, rc, det))
            continue
        method = det.get("method") or ""
        if ep == "piicDecsn" and "주주" not in method:
            continue
        kind = "piic" if ep == "piicDecsn" else "fric"
        cands.append((kind, rd, det.get("rcept_no") or "", det))
    cands.sort(key=lambda x: (x[0], x[1]))
    picked = []
    for c in cands:
        if picked and picked[-1][0] == c[0] and (c[1] - picked[-1][1]).days <= 14:
            if c[2] >= picked[-1][2]:
                picked[-1] = c
            continue
        picked.append(c)
    for kind, rd, _, det in picked:
        k = bisect.bisect_left(dates, rd)
        if k == 0:
            continue
        ex = dates[k - 1]
        if kind == "stkdp":
            if (rd - ex).days > 7:
                continue
            if rd.month == 12 and rd.day >= 28:
                if k < 2:
                    continue
                ex = dates[k - 2]           # 결산 락일 = 폐장일 직전 거래일
        elif (rd - ex).days > 7:
            if k > len(dates) - 1:
                continue
            ex = dates[k]
        if any(abs((ex - bd).days) <= 3 for bd in big_dates):
            continue
        if kind in ("fric", "stkdp"):
            alloc = det.get("ratio")
            if alloc is None or alloc <= 0:
                continue
            events.append((ex, 1.0 / (1.0 + float(alloc)), kind))
        else:
            prev_i = dates.index(ex) - 1
            if prev_i < 0:
                continue
            c_prev, c_ex = close_of[dates[prev_i]], close_of[ex]
            if c_prev <= 0 or c_ex <= 0:
                continue
            r_evt = c_ex / c_prev
            if abs(math.log(r_evt)) < math.log(1.01):
                continue
            events.append((ex, r_evt, "piic_gap"))
    events.sort()
    return events


def step_type(d: date, has_evidence: bool) -> str:
    ye = (d.month == 12 and d.day >= 24) or (d.month == 1 and d.day <= 5)
    if has_evidence:
        return "event_residual"
    return "stock_div" if ye else "small_isolated"


def seg_stats(q: dict[date, float], seg: list[date]) -> tuple[int, float]:
    errs = sorted(abs(q[d] - 1) for d in seg)
    n = len(errs)
    return n, errs[min(int(0.99 * n), n - 1)]


def main() -> int:
    scope = json.load(open(SCOPE))
    ledger = json.load(open(LEDGER))
    unresolved: dict[str, list[date]] = {}
    for r in ledger["missed_big"]["rows"] + ledger["fp"]["rows"]:
        unresolved.setdefault(r["ticker"], []).append(date.fromisoformat(r["date"]))

    tickers = scope["event_tickers"] + scope["noevent_sample"]
    all_errs = []
    ticker_p99 = {}
    errs_by_ticker = {}
    year_days = Counter()
    residual = {}
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        for t in tickers:
            closes, adj, shares, details, actions = load(cur, t)
            if not closes:
                continue
            events = v3_events_tagged(closes, shares, details)
            ev_plain = [(d, r) for d, r, _ in events]
            imprecise = [d for d, _, p in events if p in ("gap_fallback", "piic_gap")]
            cuts = unresolved.get(t, []) + imprecise
            dates = [d for d, _ in closes]
            f = factor_curve(dates, ev_plain)
            recon = {d: c * f[d] for d, c in closes}
            common = sorted(set(recon) & set(adj))
            if not common:
                continue
            last = common[-1]
            if recon[last] <= 0 or adj[last] <= 0:
                continue
            scale = adj[last] / recon[last]
            cut = max(cuts) if cuts else None
            seg = [d for d in common if adj[d] > 0 and (cut is None or d > cut)]
            seg = seg[WARMUP:]
            if not seg:
                continue
            q = {d: recon[d] * scale / adj[d] for d in seg}
            errs = sorted(abs(q[d] - 1) for d in seg)
            n = len(errs)
            p99 = errs[min(int(0.99 * n), n - 1)]
            ticker_p99[t] = p99
            errs_by_ticker[t] = errs
            all_errs.extend(errs)
            for d in seg:
                year_days[d.year] += 1

            if p99 > 0.01:
                # 오차 스텝 = |Δlog q| > 0.5% (이음새/미포착 이벤트 경계)
                steps = []
                prev = None
                for d in seg:
                    if prev is not None and q[prev] > 0 and q[d] > 0:
                        dq = abs(math.log(q[d]) - math.log(q[prev]))
                        if dq > 0.005:
                            steps.append((d, dq))
                    prev = d
                db_j = [d for d, _ in db_factor_jumps(closes, adj)]
                se_full = share_events(sorted(shares), shares)
                se = [d for d, _ in se_full]
                det_rd = [x["record_date"] for x in details if x["record_date"]]
                act_d = [ad for _, ad in actions]
                out_steps = []
                sd_cuts = []
                for d, dq in steps:
                    def near(lst):
                        return min((abs((d - x).days) for x in lst), default=None)
                    dists = [near([x for x, _ in ev_plain]), near(se),
                             near(det_rd), near(act_d)]
                    st = step_type(d, any(x is not None and x <= 7 for x in dists))
                    sd_match = None
                    if st == "stock_div":
                        sd_cuts.append(d)
                        # 확증: +180일 내(주총 후 신주상장) 동일 비율 주식수 증가
                        for ds, rs in se_full:
                            if rs <= 0 or rs >= 1 or not 0 <= (ds - d).days <= 180:
                                continue
                            if abs(-math.log(rs) - dq) < dq * 0.35 + 0.003:
                                sd_match = {"date": ds.isoformat(),
                                            "inc_pct": round((1 / rs - 1) * 100, 2)}
                                break
                    out_steps.append({
                        "date": d.isoformat(), "dlogq_pct": round(dq * 100, 3),
                        "type": st, "sd_share_match": sd_match,
                        "near_recon_ev": dists[0],
                        "near_db_jump": near(db_j), "near_share_ev": dists[1],
                        "near_detail_rd": dists[2], "near_action": dists[3],
                    })
                residual[t] = {"p99": round(p99, 5), "n_days": n,
                               "seg_start": seg[0].isoformat(),
                               "n_steps": len(steps), "steps": out_steps}
                # 반사실 v3 컷 [diagnostic-upper-bound]: 주식배당 스텝도 절단
                if sd_cuts:
                    cut3 = max(sd_cuts)
                    seg3 = [d for d in seg if d > cut3]
                    if seg3:
                        n3, p99_3 = seg_stats(q, seg3)
                        residual[t]["cf_stockdiv_cut"] = {
                            "n_days": n3, "p99": round(p99_3, 5)}
                    else:
                        residual[t]["cf_stockdiv_cut"] = {"n_days": 0, "p99": None}

    all_errs.sort()
    n = len(all_errs)

    def pct(p):
        return all_errs[min(int(p * n), n - 1)] if n else None

    p99s = sorted(ticker_p99.values())
    m = len(p99s)
    gate = {
        "tickers": m, "ticker_days": n,
        "pooled": {"p50": pct(0.50), "p99": pct(0.99), "max": all_errs[-1] if n else None},
        "ticker_p99": {
            "median": p99s[m // 2] if m else None,
            "p90": p99s[min(int(0.9 * m), m - 1)] if m else None,
            "share_le_0.1pct": sum(1 for x in p99s if x <= 0.001) / m if m else None,
            "share_le_1pct": sum(1 for x in p99s if x <= 0.01) / m if m else None,
        },
        "year_days": {str(y): c for y, c in sorted(year_days.items())},
    }

    # 이음새 시그니처: 잔여 종목 스텝의 달력일 클러스터링 + 유형 census
    step_dates = Counter()
    type_census = Counter()
    ticker_class = Counter()
    cf_p99 = []
    cf_le1 = cf_gt1 = cf_empty = 0
    sd_total = sd_matched = 0
    for t, r in residual.items():
        types = set()
        for s in r["steps"]:
            step_dates[s["date"]] += 1
            type_census[s["type"]] += 1
            types.add(s["type"])
            if s["type"] == "stock_div":
                sd_total += 1
                if s["sd_share_match"]:
                    sd_matched += 1
        if not types:
            k = "no_steps"
        elif types == {"stock_div"}:
            k = "A_stockdiv_only"
        elif "stock_div" in types:
            k = "B_mixed_with_stockdiv"
        elif types == {"event_residual"}:
            k = "C_event_residual_only"
        elif types == {"small_isolated"}:
            k = "D_small_isolated_only"
        else:
            k = "E_event+small"
        ticker_class[k] += 1
        cf = r.get("cf_stockdiv_cut")
        if cf:
            if cf["p99"] is None:
                cf_empty += 1
            else:
                cf_p99.append(cf["p99"])
                if cf["p99"] <= 0.01:
                    cf_le1 += 1
                else:
                    cf_gt1 += 1
    onset = {
        "n_residual_tickers": len(residual),
        "step_type_census": dict(type_census),
        "stock_div_confirm": {"n": sd_total, "share_matched_180d": sd_matched},
        "ticker_class": dict(ticker_class),
        "cf_stockdiv_cut": {"tickers_with_cut": cf_le1 + cf_gt1 + cf_empty,
                            "now_le_1pct": cf_le1, "still_gt_1pct": cf_gt1,
                            "segment_emptied": cf_empty},
        "top_step_dates": step_dates.most_common(20),
        "tickers": residual,
    }
    # 11차 ② carve-out: 주식배당 클래스 종목(stock_div 스텝 보유) 제외 허용치 분포
    carve = sorted(t for t, r in residual.items()
                   if any(s["type"] == "stock_div" for s in r["steps"]))
    co_errs = []
    co_p99s = []
    for t, errs in errs_by_ticker.items():
        if t in carve:
            continue
        co_errs.extend(errs)
        co_p99s.append(ticker_p99[t])
    co_errs.sort()
    co_p99s.sort()
    cn, cm = len(co_errs), len(co_p99s)

    def cpct(p):
        return co_errs[min(int(p * cn), cn - 1)] if cn else None

    carveout = {
        "excluded_tickers": carve, "n_excluded": len(carve),
        "tickers": cm, "ticker_days": cn,
        "pooled": {"p50": cpct(0.50), "p90": cpct(0.90), "p99": cpct(0.99),
                   "max": co_errs[-1] if cn else None},
        "ticker_p99": {
            "median": co_p99s[cm // 2] if cm else None,
            "p90": co_p99s[min(int(0.9 * cm), cm - 1)] if cm else None,
            "p99": co_p99s[min(int(0.99 * cm), cm - 1)] if cm else None,
            "share_le_0.1pct": sum(1 for x in co_p99s if x <= 0.001) / cm if cm else None,
            "share_le_1pct": sum(1 for x in co_p99s if x <= 0.01) / cm if cm else None,
            "max": co_p99s[-1] if cm else None,
        },
    }

    out = {"generated": str(date.today()), "version": "v5" if V5 else "v4.1",
           "gate_replication": gate,
           "carveout_stockdiv": carveout, "onset": onset}
    path = (f"{ROOT}/data/verification/issue114_seam_probe_"
            f"{'v5_' if V5 else ''}{date.today():%Y%m%d}.json")
    with open(path, "w") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print(json.dumps({"gate": gate, "onset_summary": {
        k: v for k, v in onset.items() if k != "tickers"}}, ensure_ascii=False, indent=1))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
