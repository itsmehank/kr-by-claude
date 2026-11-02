"""#112 — 2차 필터(LLM 분류) 선별 가치: entry+watch vs ignore forward excess (탐색 등급).

설계: docs/superpowers/specs/2026-11-02-issue112-selection-value-design.md
측정 관례는 #111(minervini_forward)과 동일 — T+1 adj_close → +h 관측행, 지수 단리 차,
종목 클러스터 부트스트랩(같은 rng 관례). 전 과정 읽기 전용.
"""
from __future__ import annotations

import random
from bisect import bisect_right
from datetime import date
from itertools import groupby
from typing import Iterator

from psycopg import Connection

from kr_pipeline.backtest.minervini_forward import BOOT_B, HORIZONS, SEED
from kr_pipeline.backtest.phases import INDEX_OF

PriceRow = tuple[date, float]

SAMPLE_WINDOWS: dict[str, tuple[date, date]] = {
    "A": (date(2021, 1, 1), date(2024, 12, 31)),
    "B": (date(2021, 1, 1), date(2024, 12, 31)),
    "C": (date(2017, 7, 1), date(2020, 12, 31)),
}
SELECTED = ("entry", "watch")
REJECTED = ("ignore",)
# 기각 사유 단일 라벨 우선순위 — 데이터 결함(reverse_split) > climax > topping > 기타 (설계 §4-3)
_REASON_PRIORITY = (
    ("reverse_split_distortion", "reverse_split"),
    ("climax_run", "climax"),
    ("topping_distribution", "topping"),
)


def cell_excess(rows: list[PriceRow], analyzed_for_date: date, horizon: int,
                index_close: dict[date, float]) -> float | None:
    """분류일 다음 관측행(T+1) → T+1+horizon 관측행 초과수익(%p). 결손 → None (설계 §3)."""
    dates = [r[0] for r in rows]
    j = bisect_right(dates, analyzed_for_date)
    k = j + horizon
    if j >= len(rows) or k >= len(rows):
        return None
    d1, p1 = rows[j]
    d2, p2 = rows[k]
    i1, i2 = index_close.get(d1), index_close.get(d2)
    if i1 is None or i2 is None:
        return None
    return (p2 / p1 - 1) * 100 - (i2 / i1 - 1) * 100


def assign_sample(ticker: str, analyzed_for_date: date,
                  sets: dict[str, set[str]]) -> str | None:
    """표본 귀속 — 종목 소속 ∧ 날짜 창 (설계 §2). 미해당 → None."""
    for name, (lo, hi) in SAMPLE_WINDOWS.items():
        if ticker in sets.get(name, set()) and lo <= analyzed_for_date <= hi:
            return name
    return None


def ignore_reason(risk_flags: list[str] | None) -> str:
    flags = set(risk_flags or [])
    for flag, label in _REASON_PRIORITY:
        if flag in flags:
            return label
    return "other"


def _by_ticker(cells: list[dict], key: str, group: str) -> dict[str, tuple[float, int]]:
    out: dict[str, tuple[float, int]] = {}
    for c in cells:
        if c["group"] != group or c.get(key) is None:
            continue
        s, n = out.get(c["ticker"], (0.0, 0))
        out[c["ticker"]] = (s + c[key], n + 1)
    return out


def _mean_median(vals: list[float]) -> tuple[float, float]:
    vs = sorted(vals)
    n = len(vs)
    med = vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2
    return sum(vs) / n, med


MIN_CLUSTERS = 5   # 한 군의 종목 클러스터가 이보다 적으면 CI 를 내지 않는다(부트스트랩 퇴화 — 설계 §4-3 reverse_split)


def diff_bootstrap(cells: list[dict], *, key: str, sel: str, rej: str,
                   b: int = BOOT_B, seed: int = SEED,
                   min_clusters: int = MIN_CLUSTERS) -> dict:
    """선별군 − 기각군 평균 차이 + 종목 클러스터 부트스트랩 95% CI (설계 §4-1).

    종목 복원추출(sorted tickers, rng.choice — minervini_forward.agg_bootstrap_ci 관례) 후
    양 군을 (합, 개수)로 재집계해 차이를 구한다. 한 군이 비면 그 반복은 건너뛰고 건수를 기록.
    한 군의 클러스터 수 < min_clusters 면 점추정만 내고 CI 는 None(`ci_suppressed` 에 사유).
    """
    sel_t = _by_ticker(cells, key, sel)
    rej_t = _by_ticker(cells, key, rej)
    sel_vals = [c[key] for c in cells if c["group"] == sel and c.get(key) is not None]
    rej_vals = [c[key] for c in cells if c["group"] == rej and c.get(key) is not None]
    out: dict = {"n_sel": len(sel_vals), "n_rej": len(rej_vals),
                 "tickers_sel": len(sel_t), "tickers_rej": len(rej_t),
                 "mean_sel": None, "median_sel": None, "mean_rej": None, "median_rej": None,
                 "pos_rate_sel": None, "pos_rate_rej": None,
                 "diff": None, "ci95": None, "ci_suppressed": None, "skipped_iters": 0}
    if sel_vals:
        out["mean_sel"], out["median_sel"] = (round(x, 3) for x in _mean_median(sel_vals))
        out["pos_rate_sel"] = round(sum(v > 0 for v in sel_vals) / len(sel_vals), 3)
    if rej_vals:
        out["mean_rej"], out["median_rej"] = (round(x, 3) for x in _mean_median(rej_vals))
        out["pos_rate_rej"] = round(sum(v > 0 for v in rej_vals) / len(rej_vals), 3)
    if not sel_vals or not rej_vals:
        return out
    out["diff"] = round(out["mean_sel"] - out["mean_rej"], 3)
    if len(rej_t) < min_clusters:
        out["ci_suppressed"] = f"rej_clusters<{min_clusters}"
        return out
    if len(sel_t) < min_clusters:
        out["ci_suppressed"] = f"sel_clusters<{min_clusters}"
        return out
    tickers = sorted(set(sel_t) | set(rej_t))
    rng = random.Random(seed)
    diffs: list[float] = []
    skipped = 0
    while len(diffs) < b:
        ss = sc = rs = rc = 0.0
        for _ in range(len(tickers)):
            t = rng.choice(tickers)
            if t in sel_t:
                s, c = sel_t[t]
                ss += s
                sc += c
            if t in rej_t:
                s, c = rej_t[t]
                rs += s
                rc += c
        if sc == 0 or rc == 0:
            skipped += 1
            continue
        diffs.append(ss / sc - rs / rc)
    diffs.sort()
    out["ci95"] = [round(diffs[int(0.025 * b)], 3), round(diffs[min(int(0.975 * b), b - 1)], 3)]
    out["skipped_iters"] = skipped
    return out


def hint_of(ci: list[float] | None) -> str:
    """탐색 등급 어휘 — 판정 아님 (설계 §4-1)."""
    if ci is None:
        return "측정 불가(소표본 또는 빈 군)"
    lo, hi = ci
    if lo > 0:
        return "선별 가치 단서"
    if hi < 0:
        return "역선별 단서"
    return "구분 불가"


# --- DB 로더 (읽기 전용) ---

def load_cells(conn: Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, analyzed_for_date, market, classification, risk_flags "
            "FROM backtest_classification ORDER BY symbol, analyzed_for_date")
        return [{"ticker": s, "date": d, "market": m, "classification": c,
                 "group": "sel" if c in SELECTED else ("rej" if c in REJECTED else "other"),
                 "reason": ignore_reason(f) if c in REJECTED else None}
                for s, d, m, c, f in cur.fetchall()]


def iter_price_rows(conn: Connection, tickers: list[str]) -> Iterator[tuple[str, list[PriceRow]]]:
    with conn.cursor(name="selection_value_rows") as cur:
        cur.itersize = 50_000
        cur.execute(
            "SELECT ticker, date, adj_close FROM daily_prices "
            "WHERE ticker = ANY(%s) AND adj_close IS NOT NULL ORDER BY ticker, date",
            (tickers,))
        for ticker, grp in groupby(cur, key=lambda r: r[0]):
            yield ticker, [(d, float(a)) for _, d, a in grp]


def attach_excess(conn: Connection, cells: list[dict],
                  index_close: dict[str, dict[date, float]]) -> dict[int, int]:
    """각 셀에 excess_{h} 부착. horizon 별 결손(제외) 건수 반환."""
    by_ticker: dict[str, list[dict]] = {}
    for c in cells:
        by_ticker.setdefault(c["ticker"], []).append(c)
    excluded = {h: 0 for h in HORIZONS}
    seen: set[str] = set()
    for ticker, rows in iter_price_rows(conn, sorted(by_ticker)):
        seen.add(ticker)
        for c in by_ticker[ticker]:
            iclose = index_close.get(INDEX_OF.get(c["market"], "1001"), {})
            for h in HORIZONS:
                v = cell_excess(rows, c["date"], h, iclose)
                c[f"excess_{h}"] = v
                if v is None:
                    excluded[h] += 1
    for ticker, cs in by_ticker.items():
        if ticker not in seen:
            for c in cs:
                for h in HORIZONS:
                    c[f"excess_{h}"] = None
                    excluded[h] += 1
    return excluded
