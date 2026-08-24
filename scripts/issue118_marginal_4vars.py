"""#118 체크리스트 4 — marginal 역선택 4변수 측정 (11차 기준 봉인 후 실행).

측정창 2017~24 고정(봉인). 대상 = 생존 종목 전환일 단면(상폐 제외 — marginal
장치는 실전 지표 표면(margin 원천값)이 daily_indicators 에만 존재, 명기).

- mc 정의 = tt_marginal_summary 동일(SSOT): 조건 PASS AND margin<3.0(c8 은
  rating point). 결측 규약 보수 승계(PASS 인데 margin 결측 → mc 미확정).
- 발화 = mc≥3 (TT_MARGINAL_DEMOTION_COUNT). 해소 = tt_recovery_ok 정확한 역
  (8조건 all pass AND mc<3), 스캔 63거래일.
- 지연비용 1차 = 차단 트리거 가상 성과(결정론 시뮬 [design-judgment]:
  지연 구간 내 첫 '60일 종가 신고 돌파 + 거래량≥1.5×50일평균' 일의 h20
  초과수익). 드리프트(전환→해소 초과수익) = 보조.
- 세 수량 무조건 보고: 순효과(≡이탈군 회피손실−해소군 지연비용)·편중도·
  역선택도. 발의 성립 = ①′ 순효과<0 AND ②′ 첫 전환 편중 재현.
  발의 ≠ 변경. 결과 관측 후 자구 변경 금지.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date

import numpy as np
import pandas as pd
import psycopg

from kr_pipeline.backtest.minervini_forward import (
    agg_bootstrap_ci, extract_transitions, forward_excess,
)
from kr_pipeline.common.thresholds import (
    TT_MARGIN_MARGINAL_PCT, TT_MARGINAL_DEMOTION_COUNT,
)

DB = "postgresql://localhost/kr_pipeline"
WIN = (date(2017, 1, 1), date(2024, 12, 31))
RESOLVE_ROWS = 63
IDX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}


def margins_frame(df: pd.DataFrame) -> pd.DataFrame:
    c, s50, s150, s200 = df.adj_close, df.sma_50, df.sma_150, df.sma_200
    w52h, w52l, rs = df.w52_high, df.w52_low, df.rs_rating
    m = pd.DataFrame(index=df.index)
    m["m1"] = np.minimum((c - s150) / s150, (s150 - s200) / s200) * 100
    m["m2"] = (s150 - s200) / s200 * 100
    m["m3"] = (s200 / s200.shift(22) - 1) * 100
    m["m4"] = np.minimum((s50 - s150) / s150, (s150 - s200) / s200) * 100
    m["m5"] = (c - s50) / s50 * 100
    m["m6"] = (c - w52l * 1.25) / (w52l * 1.25) * 100
    m["m7"] = (c - w52h * 0.75) / (w52h * 0.75) * 100
    m["m8"] = rs - 70
    return m


def main() -> int:
    out_events = []
    mc_null = 0
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("SELECT index_code, date, close FROM index_daily")
        idx = defaultdict(dict)
        for code, d, cl in cur.fetchall():
            idx[code][d] = float(cl)
        cur.execute("SELECT ticker, market FROM stocks WHERE delisted_at IS NULL")
        mkt_of = dict(cur.fetchall())
        cur.execute("SELECT index_code, date, current_status "
                    "FROM market_context_daily")
        regime = {}
        for code, d, st in cur.fetchall():
            regime[(code, d)] = st

        cur.execute("SELECT DISTINCT ticker FROM daily_indicators ORDER BY 1")
        tickers = [r[0] for r in cur.fetchall()]
        for t in tickers:
            cur.execute(
                "SELECT d.date, d.adj_close, d.sma_50, d.sma_150, d.sma_200, "
                "d.w52_high, d.w52_low, d.rs_rating, d.minervini_pass, "
                "d.minervini_c1, d.minervini_c2, d.minervini_c3, d.minervini_c4, "
                "d.minervini_c5, d.minervini_c6, d.minervini_c7, d.minervini_c8, "
                "p.volume FROM daily_indicators d "
                "JOIN daily_prices p USING (ticker, date) "
                "WHERE d.ticker=%s ORDER BY d.date", (t,))
            raw = cur.fetchall()
            if len(raw) < 30:
                continue
            df = pd.DataFrame(raw, columns=[
                "date", "adj_close", "sma_50", "sma_150", "sma_200", "w52_high",
                "w52_low", "rs_rating", "mp", "c1", "c2", "c3", "c4", "c5",
                "c6", "c7", "c8", "volume"])
            for col in ("adj_close", "sma_50", "sma_150", "sma_200", "w52_high",
                        "w52_low", "volume", "rs_rating"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            mg = margins_frame(df).astype(float)
            cmat = df[[f"c{k}" for k in range(1, 9)]].to_numpy()
            mmat = mg.to_numpy()
            passed = cmat == True                                   # noqa: E712
            marg = passed & (mmat < TT_MARGIN_MARGINAL_PCT)
            bad = passed & ~np.isfinite(mmat)                       # PASS+결측
            mc = np.where(bad.any(axis=1), -1, marg.sum(axis=1))    # -1=미확정
            allpass = passed.all(axis=1)
            vol = df.volume
            avg50 = vol.rolling(50, min_periods=50).mean()
            hi60 = df.adj_close.rolling(60, min_periods=60).max().shift(1)
            brk = (df.adj_close > hi60) & (vol >= 1.5 * avg50)
            rows = [(r.date, float(r.adj_close), bool(r.mp) if r.mp is not None
                     else None, None) for r in df.itertuples()]
            iclose = idx[IDX_CODE.get(mkt_of.get(t) or "KOSPI", "1001")]
            trs = extract_transitions(rows)
            for seq, i in enumerate(trs):
                d0 = rows[i][0]
                if not (WIN[0] <= d0 <= WIN[1]):
                    continue
                if mc[i] < 0:
                    mc_null += 1
                    continue
                x20 = forward_excess(rows, i, 20, iclose)
                ev = {"ticker": t, "date": d0.isoformat(), "first": seq == 0,
                      "mc": int(mc[i]), "fired": bool(mc[i] >=
                                                      TT_MARGINAL_DEMOTION_COUNT),
                      "x20": x20,
                      "regime": regime.get((IDX_CODE.get(
                          mkt_of.get(t) or "KOSPI", "1001"), d0)),
                      "marg_conds": [f"c{k+1}" for k in range(8) if marg[i][k]]}
                if ev["fired"]:
                    j0 = None
                    for j in range(i + 1, min(i + 1 + RESOLVE_ROWS, len(rows))):
                        if allpass[j] and 0 <= mc[j] < TT_MARGINAL_DEMOTION_COUNT:
                            j0 = j
                            break
                    ev["resolved"] = j0 is not None
                    if j0 is not None:
                        blocked = [j for j in range(i + 1, j0 + 1) if brk.iloc[j]]
                        ev["n_blocked"] = len(blocked)
                        ev["delay_cost"] = (forward_excess(rows, blocked[0] - 1,
                                                           20, iclose)
                                            if blocked else 0.0)
                        d1, dj = rows[i + 1][0], rows[j0][0]
                        p1, pj = rows[i + 1][1], rows[j0][1]
                        i1, ij = iclose.get(d1), iclose.get(dj)
                        ev["drift_aux"] = ((pj / p1 - 1) * 100 -
                                           (ij / i1 - 1) * 100
                                           if i1 and ij else None)
                    else:
                        ev["avoided_loss"] = -x20 if x20 is not None else None
                out_events.append(ev)

    evs = out_events
    fired = [e for e in evs if e["fired"]]
    calm = [e for e in evs if not e["fired"]]

    def mstat(vals):
        vs = [v for v in vals if v is not None]
        return {"n": len(vs), "mean": round(float(np.mean(vs)), 3) if vs else None}

    def cci(sub, key):
        by = defaultdict(lambda: (0.0, 0))
        for e in sub:
            v = e.get(key)
            if v is None:
                continue
            s, c = by[e["ticker"]]
            by[e["ticker"]] = (s + v, c + 1)
        return list(agg_bootstrap_ci(dict(by))) if by else None

    resolved = [e for e in fired if e.get("resolved")]
    escaped = [e for e in fired if e.get("resolved") is False]
    delay = mstat([e.get("delay_cost") for e in resolved])
    avoid = mstat([e.get("avoided_loss") for e in escaped])
    net = (avoid["mean"] - delay["mean"]
           if avoid["mean"] is not None and delay["mean"] is not None else None)
    sel = {"fired_x20": mstat([e["x20"] for e in fired]),
           "calm_x20": mstat([e["x20"] for e in calm]),
           "fired_ci": cci(fired, "x20"), "calm_ci": cci(calm, "x20")}
    adverse = (sel["fired_x20"]["mean"] - sel["calm_x20"]["mean"]
               if sel["fired_x20"]["mean"] is not None
               and sel["calm_x20"]["mean"] is not None else None)
    cond_mix = Counter(c for e in fired for c in e["marg_conds"])
    top_share = (max(cond_mix.values()) / sum(cond_mix.values())
                 if cond_mix else None)
    fire_first = mstat([1.0 if e["fired"] else 0.0
                        for e in evs if e["first"]])
    fire_rep = mstat([1.0 if e["fired"] else 0.0
                      for e in evs if not e["first"]])
    by_regime = {}
    for rg in {e["regime"] for e in evs}:
        sub = [e for e in evs if e["regime"] == rg]
        by_regime[str(rg)] = {
            "n": len(sub),
            "fire_rate": round(sum(e["fired"] for e in sub) / len(sub), 4),
            "x20_mean": mstat([e["x20"] for e in sub])["mean"]}

    out = {
        "generated": str(date.today()), "grade": "탐색 (판정 기준 = 11차 봉인)",
        "window": [str(WIN[0]), str(WIN[1])], "scope_note":
            "생존 한정 — marginal 장치는 실전 지표 표면(margin 원천값) 전용, 명기",
        "n_events": len(evs), "mc_undetermined": mc_null,
        "fire_rate": round(len(fired) / len(evs), 4) if evs else None,
        "v1_net_effect": {
            "avoided_loss_escaped": avoid, "delay_cost_resolved": delay,
            "resolved_n": len(resolved), "escaped_n": len(escaped),
            "resolve_rate": round(len(resolved) / len(fired), 4) if fired else None,
            "net_effect": round(net, 3) if net is not None else None,
            "drift_aux_mean": mstat([e.get("drift_aux") for e in resolved])["mean"],
        },
        "v2_blocked_triggers": {
            "events_with_block": sum(1 for e in resolved if e.get("n_blocked")),
            "total_blocked": sum(e.get("n_blocked") or 0 for e in resolved),
        },
        "v3_condition_mix": {"counts": dict(cond_mix.most_common()),
                             "top_share": round(top_share, 4) if top_share else None},
        "v4_stratification": {
            "fire_rate_first": fire_first, "fire_rate_repeat": fire_rep,
            "by_regime": by_regime,
        },
        "adverse_selection": {"diff_fired_minus_calm": round(adverse, 3)
                              if adverse is not None else None, **sel},
        "proposal_check": {
            "cond1_net_negative": (net is not None and net < 0),
            "cond2_first_concentration": (
                fire_first["mean"] is not None and fire_rep["mean"] is not None
                and fire_first["mean"] > fire_rep["mean"]),
            "routing": ("margin_def" if top_share and top_share >= 0.5
                        else "mc_threshold"),
        },
    }
    path = f"data/backtest/issue118_marginal_4vars_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items()
                      if k not in ("v3_condition_mix",)}, ensure_ascii=False)[:1500])
    print("cond_mix:", dict(cond_mix.most_common(5)), "top_share", top_share)
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
