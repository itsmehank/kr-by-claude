"""Phase 0 — 미포착 승자 recall 감사: 승자 선정 + 결정론 귀속 (LLM 0회, 읽기전용).

spec: docs/superpowers/specs/2026-07-02-missed-winners-recall-audit-design.md §3.
1차 잠금 고정값: 병합 갭 4주 / 잔여 상승분 컷 20% / 백필 상한 12주 / 버킷 우선순위.
T13 / T26 / L / N_cap 은 2차 잠금 대상 — 본 스크립트는 후보 그리드 전체의 분포를
산출해 2차 잠금 결정 입력을 만든다. 선정 파라미터 외 규칙은 전부 여기 고정 구현.

실행: uv run python -m kr_pipeline.backtest.recall_phase0
출력: data/backtest/recall_phase0_grid_20260702.csv   (그리드별 에피소드 수)
      data/backtest/recall_phase0_episodes_20260702.csv (그리드 전 조합 에피소드 상세)
      stdout 요약 (2차 잠금 결정용)
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv

WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2026, 6, 30)
LOOKBACK_START = date(2024, 1, 1)  # 26주 창 + 게이트 사전 13주 여유

# 1차 잠금 고정값 (spec §3.2/3.3)
MERGE_GAP_WEEKS = 4
RESIDUAL_CUT = 0.20
BACKFILL_CAP = 12
CENSOR_TAIL_WEEKS = 4

# 2차 잠금 후보 그리드 (선정 파라미터 — 분포 산출용)
T13_GRID = [0.20, 0.30, 0.40, 0.50]
T26_GRID = [0.35, 0.50, 0.70]
L_GRID = [500_000_000, 1_000_000_000, 2_000_000_000]  # 5억/10억/20억

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "backtest"
STAMP = "20260702"

IDX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}


def _connect() -> psycopg.Connection:
    load_dotenv()
    return psycopg.connect(os.environ["DATABASE_URL"])


def load_anchors(conn) -> list[date]:
    """ISO 주별 마지막 거래일 (지수 캘린더 기준 — 휴장 금요일도 정확)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date FROM index_daily WHERE index_code='1001'"
            " AND date BETWEEN %s AND %s ORDER BY date",
            (LOOKBACK_START, WINDOW_END),
        )
        days = [r[0] for r in cur.fetchall()]
    by_week: dict[tuple, date] = {}
    for d in days:
        iso = d.isocalendar()
        by_week[(iso[0], iso[1])] = max(d, by_week.get((iso[0], iso[1]), d))
    return sorted(by_week.values())


def load_index_closes(conn, anchors: list[date]) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = {}
    with conn.cursor() as cur:
        for mkt, code in IDX_CODE.items():
            cur.execute(
                "SELECT date, close FROM index_daily WHERE index_code=%s AND date = ANY(%s)",
                (code, anchors),
            )
            out[mkt] = {r[0]: float(r[1]) for r in cur.fetchall()}
    return out


def load_anchor_closes(conn, anchors: list[date]) -> dict[str, dict[date, float]]:
    """종목별 anchor 일 adj_close."""
    closes: dict[str, dict[date, float]] = defaultdict(dict)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, date, adj_close FROM daily_prices WHERE date = ANY(%s)",
            (anchors,),
        )
        for t, d, c in cur.fetchall():
            if c is not None:
                closes[t][d] = float(c)
    return closes


def load_markets(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, market FROM stocks")
        return {r[0]: r[1] for r in cur.fetchall()}


def winner_cells(
    anchors, in_window_idx, closes, idx_closes, markets
) -> dict[tuple[float, float], dict[str, list[int]]]:
    """(T13,T26) 그리드 조합별 → ticker → 당첨 anchor 인덱스 목록.

    spec §3.1: (excess13 ≥ T13 AND ret13 > 0) OR (excess26 ≥ T26 AND ret26 > 0).
    수익률 전부 adj_close·anchor 종가 기준.
    """
    grid = {(a, b): defaultdict(list) for a in T13_GRID for b in T26_GRID}
    idx_ret: dict[str, dict[int, tuple[float | None, float | None]]] = {}
    for mkt, ic in idx_closes.items():
        idx_ret[mkt] = {}
        for i in in_window_idx:
            a = anchors[i]
            r13 = r26 = None
            if anchors[i - 13] in ic and a in ic:
                r13 = ic[a] / ic[anchors[i - 13]] - 1
            if anchors[i - 26] in ic and a in ic:
                r26 = ic[a] / ic[anchors[i - 26]] - 1
            idx_ret[mkt][i] = (r13, r26)

    for t, cmap in closes.items():
        mkt = markets.get(t)
        if mkt not in idx_ret:
            continue
        for i in in_window_idx:
            a = anchors[i]
            ca = cmap.get(a)
            if ca is None:
                continue
            ir13, ir26 = idx_ret[mkt][i]
            e13 = e26 = None
            r13 = r26 = None
            c13 = cmap.get(anchors[i - 13])
            c26 = cmap.get(anchors[i - 26])
            if c13 and ir13 is not None:
                r13 = ca / c13 - 1
                e13 = r13 - ir13
            if c26 and ir26 is not None:
                r26 = ca / c26 - 1
                e26 = r26 - ir26
            for (t13, t26), cells in grid.items():
                hit13 = e13 is not None and e13 >= t13 and r13 > 0
                hit26 = e26 is not None and e26 >= t26 and r26 > 0
                if hit13 or hit26:
                    # 셀 초과수익 = 자격 창의 excess 최댓값 (2차 잠금 층화 기준 입력)
                    exc = max(e13 if hit13 else float("-inf"),
                              e26 if hit26 else float("-inf"))
                    cells[t].append((i, exc))
    return grid


def merge_episodes(idx_list: list[int]) -> list[list[int]]:
    """당첨 anchor 인덱스 → 갭 ≤ MERGE_GAP_WEEKS 병합 (spec §3.2)."""
    eps, cur = [], [idx_list[0]]
    for i in idx_list[1:]:
        if i - cur[-1] <= MERGE_GAP_WEEKS:
            cur.append(i)
        else:
            eps.append(cur)
            cur = [i]
    eps.append(cur)
    return eps


def main() -> None:
    conn = _connect()
    anchors = load_anchors(conn)
    pos = {a: k for k, a in enumerate(anchors)}
    in_window_idx = [k for k, a in enumerate(anchors) if WINDOW_START <= a <= WINDOW_END and k >= 26]
    censor_tail = set(in_window_idx[-CENSOR_TAIL_WEEKS:])

    idx_closes = load_index_closes(conn, anchors)
    closes = load_anchor_closes(conn, anchors)
    markets = load_markets(conn)
    grid = winner_cells(anchors, in_window_idx, closes, idx_closes, markets)

    # 그리드 전 조합의 승자 종목 합집합 → 게이트/일별 데이터 일괄 로드
    all_tickers = sorted({t for cells in grid.values() for t in cells})
    print(f"[phase0] anchors={len(anchors)} in-window={len(in_window_idx)} "
          f"winner-ticker union(전 그리드)={len(all_tickers)}")

    gate: dict[str, set[date]] = defaultdict(set)  # 주말 게이트 4조건 (spec §3.3 정정판)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.ticker, i.date
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.ticker = ANY(%s) AND i.date = ANY(%s)
               AND i.minervini_pass = TRUE
               AND i.rs_line_not_declining_7m = TRUE
               AND s.delisted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM daily_prices p
                    WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL)
            """,
            (all_tickers, anchors),
        )
        for t, d in cur.fetchall():
            gate[t].add(d)

    daily: dict[str, list[tuple[date, float, float]]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, date, adj_close, value FROM daily_prices"
            " WHERE ticker = ANY(%s) AND date >= %s ORDER BY ticker, date",
            (all_tickers, LOOKBACK_START),
        )
        for t, d, c, v in cur.fetchall():
            daily[t].append((d, float(c) if c is not None else None, float(v or 0)))

    corp: dict[str, list[date]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, event_date FROM corporate_actions WHERE ticker = ANY(%s)",
            (all_tickers,),
        )
        for t, d in cur.fetchall():
            corp[t].append(d)

    def episode_row(t13, t26, t, ep_idx):
        t_daily = daily[t]
        first_i = ep_idx[0]
        a_first = anchors[first_i]
        cmap = closes[t]
        mkt = markets[t]
        ic = idx_closes[mkt]
        # 시작점 = 첫 당첨 주의 자격 창 시작 (둘 다 자격이면 min — spec §3.2)
        starts = []
        for lb in (13, 26):
            c0, ca = cmap.get(anchors[first_i - lb]), cmap.get(a_first)
            i0, ia = ic.get(anchors[first_i - lb]), ic.get(a_first)
            if c0 and ca and i0 and ia:
                r, ir = ca / c0 - 1, ia / i0 - 1
                thr = t13 if lb == 13 else t26
                if r > 0 and (r - ir) >= thr:
                    starts.append(anchors[first_i - lb])
        ep_start = min(starts) if starts else anchors[first_i - 13]
        last_a = anchors[ep_idx[-1]]
        span = [(d, c) for d, c, _ in t_daily if ep_start <= d <= last_a and c]
        if not span:
            return None
        peak_d, peak_c = max(span, key=lambda x: x[1])
        # 게이트 탐색 창: 시작 −13주 ~ 고점 주 anchor (spec §3.3)
        pre = ep_start - timedelta(weeks=13)
        peak_anchor = next((a for a in reversed(anchors) if a <= peak_d), last_a)
        tt_anchors = [a for a in anchors if pre <= a <= peak_anchor]
        passed = [a for a in tt_anchors if a in gate[t]]
        first_tt = passed[0] if passed else None

        if first_tt is None:
            bucket, residual, liq_ref = "filter_excluded", None, ep_start
        else:
            base_c = cmap.get(first_tt) or next(
                (c for d, c, _ in t_daily if d == first_tt and c), None)
            residual = (peak_c / base_c - 1) if base_c else None
            liq_ref = first_tt
            bucket = ("structurally_uncatchable"
                      if residual is not None and residual < RESIDUAL_CUT
                      else "phase1_candidate")
        # 유동성: 기준일 전후 20거래일 평균 거래대금 (spec §3.1)
        di = [k for k, (d, _, _) in enumerate(t_daily) if d <= liq_ref]
        liq = None
        if di:
            k = di[-1]
            win = t_daily[max(0, k - 20): k + 21]
            vals = [v for _, _, v in win]
            liq = sum(vals) / len(vals) if vals else None

        bf = [a for a in passed if first_tt and first_tt <= a <= peak_anchor]
        truncated = len(bf) > BACKFILL_CAP
        n_bf = min(len(bf), BACKFILL_CAP)
        return {
            "t13": t13, "t26": t26, "ticker": t, "market": mkt,
            "ep_start": ep_start, "first_win_anchor": a_first, "last_win_anchor": last_a,
            "peak_date": peak_d, "n_win_weeks": len(ep_idx),
            "ep_return_pct": round((peak_c / cmap[anchors[first_i - 13]] - 1) * 100, 1)
            if cmap.get(anchors[first_i - 13]) else None,
            "first_tt": first_tt, "residual_upside_pct":
                round(residual * 100, 1) if residual is not None else None,
            "avg_value_20d": int(liq) if liq else None,
            "bucket": bucket, "n_backfill_weeks": n_bf if first_tt else 0,
            "truncated": truncated,
            "censored": ep_idx[-1] in censor_tail,
            "corp_action_flag": any(
                ep_start - timedelta(days=90) <= d <= last_a for d in corp[t]),
        }

    ep_rows = []
    grid_summary = []
    for (t13, t26), cells in sorted(grid.items()):
        combo_eps = 0
        for t, cell_list in cells.items():
            exc_by_idx: dict[int, float] = {}
            for i, exc in cell_list:
                exc_by_idx[i] = max(exc, exc_by_idx.get(i, float("-inf")))
            for ep_idx in merge_episodes(sorted(exc_by_idx)):
                row = episode_row(t13, t26, t, ep_idx)
                if row:
                    # 에피소드 초과수익 = 당첨 주 max(excess13, excess26) 의 최댓값 (2차 잠금)
                    row["ep_excess_pct"] = round(
                        max(exc_by_idx[i] for i in ep_idx) * 100, 1)
                    ep_rows.append(row)
                    combo_eps += 1
        grid_summary.append({"t13": t13, "t26": t26, "episodes": combo_eps})

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ep_path = DATA_DIR / f"recall_phase0_episodes_{STAMP}.csv"
    with open(ep_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ep_rows[0].keys()))
        w.writeheader()
        w.writerows(ep_rows)
    grid_path = DATA_DIR / f"recall_phase0_grid_{STAMP}.csv"
    with open(grid_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t13", "t26", "episodes"])
        w.writeheader()
        w.writerows(grid_summary)

    # ── 2차 잠금 결정용 요약 ──
    print("\n== 그리드별 에피소드 수 ==")
    for g in grid_summary:
        print(f"  T13={g['t13']:.2f} T26={g['t26']:.2f} → {g['episodes']}")
    print("\n== 조합별 버킷/유동성/백필 셀 (2차 잠금 입력) ==")
    for (t13, t26) in sorted(grid.keys()):
        rows = [r for r in ep_rows if r["t13"] == t13 and r["t26"] == t26]
        for L in L_GRID:
            keep = [r for r in rows if (r["avg_value_20d"] or 0) >= L]
            bk = defaultdict(int)
            cells = 0
            for r in keep:
                bk[r["bucket"]] += 1
                if r["bucket"] == "phase1_candidate":
                    cells += r["n_backfill_weeks"]
            print(f"  T13={t13:.2f} T26={t26:.2f} L={L/1e8:.0f}억 → ep={len(keep)} "
                  f"(filter_excl={bk['filter_excluded']} uncatchable={bk['structurally_uncatchable']} "
                  f"phase1={bk['phase1_candidate']}) 백필셀={cells} "
                  f"≈{cells * 159 / 3600 / 6:.1f}h(6병렬)")
    print(f"\nCSV: {ep_path}\n     {grid_path}")


if __name__ == "__main__":
    main()
