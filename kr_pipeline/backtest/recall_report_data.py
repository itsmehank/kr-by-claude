"""recall 감사 보고서 데이터 산출 (spec §6 채점 + §9 퍼널 + 보조 진단, 전부 결정론).

출력: data/backtest/recall_report_data_20260705.json
      data/backtest/recall_funnel_20260705.csv  (§9-1 에피소드 퍼널 귀속표)

버킷·감사 결과는 불변 입력(잠금) — 본 스크립트는 채점·집계만 추가한다.
보조 진단(게이트 any-day 스캔)은 버킷을 바꾸지 않는 보고서 부록용.
"""
from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from kr_pipeline.backtest import phases as ph
from kr_pipeline.backtest.recall_phase2 import (
    load_episodes, load_bars, load_phase1_rows, TABLE,
)
from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as gate_evaluate

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "backtest"
BUCKETS_CSV = DATA_DIR / "recall_phase2_buckets_20260705.csv"
AUDIT_JSON = DATA_DIR / "recall_trigger_audit_20260702.json"
OUT_JSON = DATA_DIR / "recall_report_data_20260705.json"
OUT_FUNNEL = DATA_DIR / "recall_funnel_20260705.csv"

CLIMAX_RET_PCT = 25.0   # prompt climax 정량 정의 (§6)
EXTENDED_GAP_PCT = 15.0  # prompt extended 정의


def _connect():
    load_dotenv()
    return psycopg.connect(os.environ["DATABASE_URL"])


def weekly_metrics(conn, ticker: str, anchor: date) -> dict:
    """§6 채점 입력: anchor 기준 1/2/3주 수익률, SMA50 이격%, RS rating."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, adj_close FROM daily_prices WHERE ticker=%s"
            " AND date BETWEEN %s AND %s ORDER BY date",
            (ticker, anchor - timedelta(days=30), anchor),
        )
        px = [(d, float(c)) for d, c in cur.fetchall() if c is not None]
        cur.execute(
            "SELECT i.rs_rating, i.sma_50, p.adj_close FROM daily_indicators i"
            " JOIN daily_prices p USING (ticker, date) WHERE i.ticker=%s AND i.date=%s",
            (ticker, anchor),
        )
        r = cur.fetchone()
    out = {"rs_rating": float(r[0]) if r and r[0] is not None else None,
           "sma50_gap_pct": None}
    if r and r[1] and r[2]:
        out["sma50_gap_pct"] = round((float(r[2]) / float(r[1]) - 1) * 100, 1)
    close_now = px[-1][1] if px else None
    for wk in (1, 2, 3):
        key = f"ret_{wk}w_pct"
        out[key] = None
        target = anchor - timedelta(weeks=wk)
        past = [c for d, c in px if d <= target]
        if past and close_now:
            out[key] = round((close_now / past[-1] - 1) * 100, 1)
    return out


def score_ignore_row(conn, ticker: str, row: dict) -> dict:
    """§6: ignore 행의 딱지 정의-충족 채점 + RS 컬럼."""
    m = weekly_metrics(conn, ticker, row["analyzed_for_date"])
    flags = row["risk_flags"] or []
    if isinstance(flags, str):
        flags = json.loads(flags)
    rets = [m.get("ret_1w_pct"), m.get("ret_2w_pct"), m.get("ret_3w_pct")]
    rets = [x for x in rets if x is not None]
    climax_def_met = bool(rets) and max(rets) >= CLIMAX_RET_PCT
    extended_def_met = (m["sma50_gap_pct"] is not None
                        and m["sma50_gap_pct"] > EXTENDED_GAP_PCT)
    return {
        "anchor": str(row["analyzed_for_date"]), "risk_flags": flags,
        "pattern": row["pattern"], **m,
        "climax_flagged": "climax_run" in flags,
        "climax_def_met": climax_def_met,
        "extended_flagged": "extended_from_ma" in flags,
        "extended_def_met": extended_def_met,
        "reasoning_head": (row["reasoning"] or "")[:200],
    }


WAIT_FACTORS = {
    "volume_below": r"거래량[^.]{0,30}(미달|부족|0\.\d+배|1\.[0-3]\d?배)",
    "close_weak_range": r"(하단권|중간권|중간 구간|상단.{0,6}(실패|마감 실패)|약한 마감)",
    "close_below_pivot": r"(pivot[^.]{0,15}(아래|재이탈|이탈)|종가[^.]{0,20}(재이탈|하회))",
    "wide_loose_spread": r"(wide.?and.?loose|스프레드[^.]{0,20}배)",
    "watch_reason_not_allowed": r"(§3\.5[^.]{0,30}미해당|허용 사유[^.]{0,20}(아님|미해당)|go_now 허용 사유)",
    "market_phase": r"(rally_attempt|correction|downtrend|confirmed_uptrend 미도달|시장[^.]{0,20}(비우호|미확인))",
}


def categorize_wait(reasoning: str) -> list[str]:
    hits = [k for k, pat in WAIT_FACTORS.items() if re.search(pat, reasoning or "")]
    return hits or ["other"]


def main() -> None:
    conn = _connect()
    buckets = list(csv.DictReader(open(BUCKETS_CSV)))
    audit = json.load(open(AUDIT_JSON))["results"]
    audit_by_key = {(r["ticker"], r["breakout_date"]): r for r in audit}
    eps = {(e["ticker"], e["ep_start"]): e for e in load_episodes(conn)}

    # ── §6: classification_miss 의 ignore 주 채점 ──
    cls_miss_scores = []
    for b in buckets:
        if b["bucket"] != "classification_miss":
            continue
        ep = eps[(b["ticker"], b["ep_start"])]
        rows = load_phase1_rows(conn, ep)
        for row in rows:
            if row["classification"] == "ignore":
                s = score_ignore_row(conn, b["ticker"], row)
                s["ticker"] = b["ticker"]
                cls_miss_scores.append(s)

    # ── wait 사유 분포 + 시장 국면 ──
    pmaps: dict[str, list] = {}
    market_of: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, market FROM stocks")
        market_of = {r[0]: r[1] for r in cur.fetchall()}
    factor_counts = Counter()
    phase_counts = Counter()
    for r in audit:
        for f in categorize_wait(r["reasoning"]):
            factor_counts[f] += 1
        code = ph.INDEX_OF.get(market_of.get(r["ticker"], "KOSPI"), "1001")
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
        phase_counts[ph.phase_at(pmaps[code], date.fromisoformat(r["breakout_date"])) or "?"] += 1

    # ── 보조 진단: production 게이트 any-day 스캔 (버킷 불변, 부록) ──
    bars_all = load_bars(conn, sorted({b["ticker"] for b in buckets}))
    anyday = Counter()
    per_ep_anyday = {}
    for b in buckets:
        if b["bucket"] not in ("trigger_miss", "pivot_miss"):
            continue
        ep = eps[(b["ticker"], b["ep_start"])]
        rows = [r for r in load_phase1_rows(conn, ep) if r["classification"] == "watch"]
        fired = None
        for row in rows:
            if row["pivot_price"] is None:
                continue
            pivot = float(row["pivot_price"])
            prev_close = None
            for bar in bars_all[b["ticker"]]:
                if bar["date"] <= row["analyzed_for_date"]:
                    prev_close = bar["adj_close"]
                    continue
                if bar["date"] > ep["ep_end"]:
                    break
                if bar["adj_close"] and bar["sma_50"] and bar["vol50"]:
                    g = gate_evaluate(
                        close=bar["adj_close"], pivot_price=pivot,
                        volume=bar["volume"], avg_volume_50d=bar["vol50"],
                        stop_loss=None, sma_50=bar["sma_50"],
                        classification="watch", prev_close=prev_close,
                        watch_reason=row["watch_reason"])
                    if g == "breakout_from_watch":
                        fired = str(bar["date"])
                        break
                prev_close = bar["adj_close"]
            if fired:
                break
        key = f"{b['bucket']}:{'fired' if fired else 'never'}"
        anyday[key] += 1
        per_ep_anyday[f"{b['ticker']}@{b['ep_start']}"] = fired

    # ── §9-1 퍼널 CSV (표본 120 + caught 시점 잔여상승분) ──
    funnel = []
    for b in buckets:
        ep = eps[(b["ticker"], b["ep_start"])]
        rec = dict(b)
        rec["gate_anyday_fired"] = per_ep_anyday.get(f"{b['ticker']}@{b['ep_start']}")
        rec["caught_upside_pct"] = None
        if b["bucket"] == "caught" and b["audited_anchor"]:
            a = date.fromisoformat(b["audited_anchor"])
            peak = date.fromisoformat(b["peak_date"])
            with conn.cursor() as cur:
                cur.execute("SELECT adj_close FROM daily_prices WHERE ticker=%s AND date=%s",
                            (b["ticker"], a))
                c0 = cur.fetchone()
                cur.execute("SELECT MAX(adj_close) FROM daily_prices WHERE ticker=%s"
                            " AND date BETWEEN %s AND %s", (b["ticker"], a, peak))
                cp = cur.fetchone()
            if c0 and c0[0] and cp and cp[0]:
                rec["caught_upside_pct"] = round((float(cp[0]) / float(c0[0]) - 1) * 100, 1)
        funnel.append(rec)
    with open(OUT_FUNNEL, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(funnel[0].keys()))
        w.writeheader()
        w.writerows(funnel)

    # ── coverage: 터사일 가중 역산 (§9) ──
    pool_per_tertile = 258
    tert = defaultdict(Counter)
    for b in buckets:
        tert[b["tertile"]][b["bucket"]] += 1
    coverage = {}
    for t, c in sorted(tert.items()):
        n = sum(c.values())
        coverage[t] = {"sample": dict(c), "caught_rate": c["caught"] / n,
                       "pool_est_caught": round(c["caught"] / n * pool_per_tertile, 1)}

    out = {
        "sample_buckets": dict(Counter(b["bucket"] for b in buckets)),
        "tertile_coverage": coverage,
        "wait_factor_counts": dict(factor_counts.most_common()),
        "breakout_market_phase": dict(phase_counts.most_common()),
        "gate_anyday_scan": dict(anyday),
        "cls_miss_ignore_scores": cls_miss_scores,
        "audit_decisions": dict(Counter(r["decision"] for r in audit)),
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2)[:3000])
    print(f"\nJSON: {OUT_JSON}\nFUNNEL: {OUT_FUNNEL}")


if __name__ == "__main__":
    main()
