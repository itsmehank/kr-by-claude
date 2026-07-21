"""(#2 H2) 결정론 게이트 완화 시뮬 — LLM 0회, read-only.

기준: docs/superpowers/specs/2026-07-22-issue2-recall-experiment-prereg.md §4
(기준 고정 후 실행). 결과 JSON: data/verification/issue2_h2_gate_sim.json.

변형 구현:
- V1(watch_reason 해제): trigger_gate.ALLOWED_WATCH_REASONS 를 전체 사유(+None)로 패치
- V2(fresh_cross 해제): prev_close 를 min(prev_close, pivot) 로 전달 —
  close>pivot 인 날 fresh_cross 가 항상 성립 (다른 로직 불변, 재구현 드리프트 회피)
- #45 정합: 발화일 close > pivot×1.05 는 결정론 wait(LLM 0회) — 실호출 제외
"""
import json
import statistics
from datetime import timedelta

import psycopg

from kr_pipeline.common.config import Config
from kr_pipeline.common.thresholds import PIVOT_EXTENDED_BAND_MULT
from kr_pipeline.llm_runner.compute import trigger_gate

ALL_REASONS = frozenset({
    "base_forming", "extended", "unfavorable_market", "marginal_tt",
    "valid_base_awaiting_breakout", "suspected_climax_stage_indeterminate", None,
})
UP = ("breakout", "breakout_from_watch")


def _cells(cur):
    cur.execute("""
        SELECT symbol, analyzed_for_date, pivot_price::float, base_low::float,
               classification, watch_reason
          FROM recall_audit_classification
         WHERE classification IN ('watch', 'entry') AND pivot_price IS NOT NULL
         ORDER BY symbol, analyzed_for_date
    """)
    return cur.fetchall()


def _bars(cur, symbol, afd):
    cur.execute("""
        SELECT p.date, COALESCE(p.adj_close, p.close)::float AS close,
               COALESCE(p.adj_volume, p.volume)::float AS volume,
               i.avg_volume_50d::float, i.sma_50::float
          FROM daily_prices p
          LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
         WHERE p.ticker = %s AND p.date >= %s AND p.date <= %s
         ORDER BY p.date
    """, (symbol, afd, afd + timedelta(days=7)))
    return cur.fetchall()


def _ret20(cur, symbol, fire_date, fire_close):
    cur.execute("""
        SELECT COALESCE(adj_close, close)::float FROM daily_prices
         WHERE ticker = %s AND date > %s ORDER BY date LIMIT 20
    """, (symbol, fire_date))
    rows = cur.fetchall()
    if len(rows) < 20 or not fire_close:
        return None
    return (rows[-1][0] / fire_close - 1) * 100


def run_variant(conn, name, *, all_reasons=False, no_fresh_cross=False) -> dict:
    orig = trigger_gate.ALLOWED_WATCH_REASONS
    if all_reasons:
        trigger_gate.ALLOWED_WATCH_REASONS = ALL_REASONS
    fired = real = promo = 0
    rets = []
    try:
        with conn.cursor() as cur:
            for sym, afd, pivot, base_low, cls, wr in _cells(cur):
                bars = _bars(cur, sym, afd)
                cell_fired = cell_real = cell_promo = False
                first_real = None
                prev_close = None
                for d, close, vol, avg50, sma50 in bars:
                    if d == afd:
                        prev_close = close
                        continue
                    if None in (close, vol, avg50, sma50) or close <= 0:
                        prev_close = close if close else prev_close
                        continue
                    pc = prev_close
                    if no_fresh_cross and pc is not None:
                        pc = min(pc, pivot)
                    trig = trigger_gate.evaluate(
                        close=close, pivot_price=pivot, volume=vol,
                        avg_volume_50d=avg50, stop_loss=base_low, sma_50=sma50,
                        classification=cls, prev_close=pc, watch_reason=wr,
                    )
                    if trig in UP:
                        cell_fired = True
                        if close <= pivot * PIVOT_EXTENDED_BAND_MULT:
                            if not cell_real:
                                first_real = (d, close)
                            cell_real = True
                    elif trig == "promotion":
                        cell_promo = True
                    prev_close = close
                fired += cell_fired
                real += cell_real
                promo += cell_promo
                if first_real:
                    r = _ret20(cur, sym, *first_real)
                    if r is not None:
                        rets.append(r)
    finally:
        trigger_gate.ALLOWED_WATCH_REASONS = orig
    return {
        "fired_cells": fired, "real_llm_cells": real,
        "promotion_cells_obs": promo,
        "ret20_median_obs": round(statistics.median(rets), 2) if rets else None,
        "ret20_n": len(rets),
    }


def main() -> None:
    cfg = Config.load()
    with psycopg.connect(cfg.database_url) as conn:
        with conn.cursor() as cur:
            n = len(_cells(cur))
        out = {"population_cells": n, "variants": {}}
        out["variants"]["V0_current"] = run_variant(conn, "V0")
        out["variants"]["V1_all_watch_reasons"] = run_variant(conn, "V1", all_reasons=True)
        out["variants"]["V2_no_fresh_cross"] = run_variant(conn, "V2", no_fresh_cross=True)
        out["variants"]["V3_both"] = run_variant(conn, "V3", all_reasons=True,
                                                 no_fresh_cross=True)
    path = "data/verification/issue2_h2_gate_sim.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
