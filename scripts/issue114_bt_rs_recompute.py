"""#114 RS 무편향 전 구간 재계산 (설계 v2 — 12차 승인, 로컬 DB 전용).

유니버스 원리(봉인): 날짜 d = "당일 라이브 계산의 반사실적 재현 — d 에 상장·
거래 중이던 전 종목". 생존 = 현행 Phase A/B 와 동일(같은 함수 import·같은
소스·종목별 관측행 기준 shift). 상폐 = delisted_adj_prices(v5-d 확정본,
carve=stkdp_unresolved 제외) + 레거시(daily_prices 보유 상폐 — 참조 adj 사용).

산출 = bt_rs_daily/bt_rs_weekly (라이브 표면 무접촉). 동시 측정:
1) 회귀 앵커 — 생존만 백분위 == daily/weekly_indicators.rs_rating (불일치 계수)
2) 편향 이동 — 생존 Δrs 연도별×밴드별(65~75 강조)·c8(70) 플립 양방향·
   일자별 상폐 편입 수
3) 방향 트립와이어(사전등록) — 생존 Δrs 중앙 ≥ 0 AND fail→pass 우세.
   위반 → 채택 전 버그 조사 강제(보고서에 verdict 기록, exit 1).
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date

import pandas as pd
import psycopg

from kr_pipeline.indicators.compute.rs_rating import (
    assign_rs_rating_percentiles, compute_ibd_strength_factor,
)

DB = "postgresql://localhost/kr_pipeline"
BANDS = [(0, 59), (60, 64), (65, 75), (76, 89), (90, 99)]


def band_of(r):
    for lo, hi in BANDS:
        if lo <= r <= hi:
            return f"{lo}-{hi}"
    return "na"


def sf_by_ticker(rows, qs):
    """[(ticker, date, close)] 정렬 입력 → {ticker: {date: sf}} (관측행 shift)."""
    out = {}
    cur_t, ds, cs = None, [], []

    def flush():
        if cur_t is None or not ds:
            return
        s = pd.Series(cs, index=ds, dtype=float)
        sf = compute_ibd_strength_factor(s, *qs)
        out[cur_t] = sf.to_dict()

    for t, d, c in rows:
        if t != cur_t:
            flush()
            cur_t, ds, cs = t, [], []
        ds.append(d)
        cs.append(float(c))
    flush()
    return out


def recompute(target: str) -> dict:
    daily = target == "daily"
    qs = (63, 126, 189, 252) if daily else (13, 26, 39, 52)
    table = "bt_rs_daily" if daily else "bt_rs_weekly"
    dcol = "date" if daily else "week_end_date"
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NULL")
        live_set = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT ticker FROM delisted_adj_quality "
                    "WHERE (flags->>'stkdp_unresolved')::bool")
        carve = {r[0] for r in cur.fetchall()}

        if daily:
            cur.execute("SELECT ticker, date, adj_close FROM daily_prices "
                        "WHERE adj_close > 0 ORDER BY ticker, date")
        else:
            cur.execute("SELECT ticker, week_end_date, adj_close FROM weekly_prices "
                        "WHERE adj_close > 0 ORDER BY ticker, week_end_date")
        ref_rows = cur.fetchall()
        live_sf = sf_by_ticker([r for r in ref_rows if r[0] in live_set], qs)
        legacy_sf = sf_by_ticker([r for r in ref_rows if r[0] not in live_set], qs)

        if daily:
            cur.execute("SELECT ticker, date, adj_close FROM delisted_adj_prices "
                        "WHERE ticker != ALL(%s) ORDER BY ticker, date",
                        (list(carve),))
            del_rows = cur.fetchall()
        else:
            cur.execute(
                "SELECT ticker, MAX(date) AS wed, "
                "(ARRAY_AGG(adj_close ORDER BY date DESC))[1] AS c "
                "FROM delisted_adj_prices WHERE ticker != ALL(%s) "
                "GROUP BY ticker, DATE_TRUNC('week', date) "
                "ORDER BY ticker, wed", (list(carve),))
            del_rows = cur.fetchall()
        del_sf = sf_by_ticker(del_rows, qs)
        del_sf.update(legacy_sf)            # 레거시 상폐 = 참조 adj 로 편입

        if daily:
            cur.execute("SELECT ticker, date, rs_rating FROM daily_indicators")
        else:
            cur.execute("SELECT ticker, week_end_date, rs_rating "
                        "FROM weekly_indicators")
        stored = {}
        for t, d, r in cur.fetchall():
            stored[(t, d)] = r

        by_date_live = defaultdict(dict)
        for t, m in live_sf.items():
            for d, v in m.items():
                by_date_live[d][t] = v
        by_date_del = defaultdict(dict)
        for t, m in del_sf.items():
            for d, v in m.items():
                by_date_del[d][t] = v

        anchor_mismatch = Counter()
        anchor_cells = 0
        delta_stats = defaultdict(list)      # (year, band) -> [delta]
        flips = Counter()                    # (year, dir)
        incl_series = {}
        cur.execute(f"DELETE FROM {table}")
        conn.commit()
        with cur.copy(f"COPY {table} (ticker, {dcol}, sf, rs_rating, "
                      "is_delisted) FROM STDIN") as cp:
            for d in sorted(by_date_live.keys() | by_date_del.keys()):
                lv = by_date_live.get(d, {})
                dl = by_date_del.get(d, {})
                incl_series[d.isoformat()] = len(
                    [1 for v in dl.values() if pd.notna(v)])
                comb = pd.Series({**lv, **dl}, dtype=float)
                rs_comb = assign_rs_rating_percentiles(comb)
                if lv:
                    rs_live = assign_rs_rating_percentiles(
                        pd.Series(lv, dtype=float))
                    for t, r in rs_live.items():
                        st = stored.get((t, d), "__absent__")
                        if st == "__absent__":
                            continue
                        anchor_cells += 1
                        a = None if pd.isna(r) else int(r)
                        if a != st:
                            anchor_mismatch[d.year] += 1
                for t, r in rs_comb.items():
                    rr = None if pd.isna(r) else int(r)
                    cp.write_row((t, d, None if pd.isna(comb[t]) else
                                  round(float(comb[t]), 8), rr, t not in live_set))
                    if t in live_set and rr is not None:
                        st = stored.get((t, d))
                        if st is not None:
                            delta_stats[(d.year, band_of(st))].append(rr - st)
                            if st < 70 <= rr:
                                flips[(d.year, "fail_to_pass")] += 1
                            elif rr < 70 <= st:
                                flips[(d.year, "pass_to_fail")] += 1
        conn.commit()

    all_d = [x for v in delta_stats.values() for x in v]
    s = pd.Series(all_d)
    f2p = sum(v for (y, dr), v in flips.items() if dr == "fail_to_pass")
    p2f = sum(v for (y, dr), v in flips.items() if dr == "pass_to_fail")
    tripwire_ok = bool(len(s) and s.median() >= 0 and f2p > p2f)
    return {
        "target": target,
        "anchor": {"cells": anchor_cells,
                   "mismatch_total": sum(anchor_mismatch.values()),
                   "mismatch_by_year": {str(k): v for k, v in
                                        sorted(anchor_mismatch.items())}},
        "delta": {"n": len(s),
                  "median": float(s.median()) if len(s) else None,
                  "p90": float(s.quantile(0.9)) if len(s) else None,
                  "max": int(s.max()) if len(s) else None,
                  "min": int(s.min()) if len(s) else None,
                  "by_year_band": {f"{y}|{b}": {
                      "n": len(v), "median": float(pd.Series(v).median()),
                      "p90": float(pd.Series(v).quantile(0.9))}
                      for (y, b), v in sorted(delta_stats.items())}},
        "flips": {"fail_to_pass": f2p, "pass_to_fail": p2f,
                  "by_year": {f"{y}|{dr}": v for (y, dr), v in
                              sorted(flips.items())}},
        "delisted_inclusion": {
            "max": max(incl_series.values()) if incl_series else 0,
            "by_year_mean": {str(y): round(pd.Series(
                [v for k, v in incl_series.items() if k[:4] == str(y)]).mean(), 1)
                for y in sorted({int(k[:4]) for k in incl_series})},
        },
        "tripwire_ok": tripwire_ok,
    }


def main() -> int:
    targets = [a for a in ("daily", "weekly") if f"--{a}" in sys.argv] or \
              ["daily", "weekly"]
    path0 = f"data/verification/issue114_bt_rs_{date.today():%Y%m%d}.json"
    try:                                     # 부분 실행 병합(덮어쓰기 방지)
        out = json.load(open(path0))
    except FileNotFoundError:
        out = {"generated": str(date.today()), "results": {}}
    ok = True
    for tg in targets:
        r = recompute(tg)
        out["results"][tg] = r
        ok = ok and r["tripwire_ok"]
        print(json.dumps({k: v for k, v in r.items()
                          if k not in ("delta",)} |
                         {"delta_summary": {kk: r["delta"][kk] for kk in
                                            ("n", "median", "p90", "max", "min")}},
                         ensure_ascii=False))
    path = f"data/verification/issue114_bt_rs_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved:", path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
