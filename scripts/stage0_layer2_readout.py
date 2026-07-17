"""0단계 층② 판독 + F1 전수조사 — 재현 가능한 스크립트화 (PR #51 리뷰 반영).

리포트 §4(층② 머지 후 실측 판독)와 §2 발견 F1 의 수치가 ad-hoc SQL 로만 존재해
감사 불능이던 것을 단일 스크립트로 고정한다. production DB read-only.

주의: 표본 B 무인 백필이 진행 중이면 행수가 실행 시점마다 표류한다 — 출력에
실행 시각과 테이블 행수를 함께 기록하므로 리포트 수치와의 차이는 표류분으로
해석한다(리포트에 명시).

측정 항목:
  1. 강등 룰 발화율 pre/post 머지(07-14 경계) — 2E_tier1/2E_tier2/2F/8_5
  2. 선계산 순종 교차검증 — a_precompute_replay.json 의 demotion_trigger=true
     (symbol, sat) 가 저장 분류에서 entry 로 나온 위반 건수 (era 별)
  3. 머지 후 entry + 8_5_extended_band 발화 행 상세 (±밴드 검산용 close 포함)
  4. §8.5 밴드 would-be 발화율 (머지 전 entry 행, weekly + backtest)
  5. F1 전수조사 — daily_prices adj OHLC 불변식 위반 (모집단 구분·최근성)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from kr_pipeline.db.connection import connect
from kr_pipeline.common.thresholds import PIVOT_EXTENDED_BAND_MULT

A_REPLAY_PATH = Path("data/verification/2026-07-17-stage0/a_precompute_replay.json")
OUT_PATH = Path("data/verification/2026-07-17-stage0/layer2_readout.json")

MERGE_CUT = "2026-07-14"  # #37/#38 머지(07-13) 이후 첫 백필 실행일


def main() -> int:
    out: dict = {"executed_at": datetime.now().isoformat(timespec="seconds"),
                 "merge_cut": MERGE_CUT,
                 "band_mult": PIVOT_EXTENDED_BAND_MULT}

    with connect() as conn, conn.cursor() as cur:
        # 0. 행수 스냅샷 (백필 표류 해석 기준)
        cur.execute("SELECT count(*) FROM backtest_classification")
        out["backtest_rows_now"] = cur.fetchone()[0]

        # 1. 발화율 pre/post
        cur.execute(
            """
            SELECT CASE WHEN classified_at >= %s THEN 'post' ELSE 'pre' END era,
                   count(*) n,
                   count(*) FILTER (WHERE triggered_rules ? '2E_tier1') t1,
                   count(*) FILTER (WHERE triggered_rules ? '2E_tier2') t2,
                   count(*) FILTER (WHERE triggered_rules ? '2F_failed_breakout') f,
                   count(*) FILTER (WHERE triggered_rules ? '8_5_extended_band') band
              FROM backtest_classification GROUP BY 1
            """, (MERGE_CUT,))
        out["firing_rates"] = {
            r[0]: {"n": r[1], "2E_tier1": r[2], "2E_tier2": r[3],
                   "2F_failed_breakout": r[4], "8_5_extended_band": r[5]}
            for r in cur.fetchall()
        }

        # 2. 선계산 순종 교차검증 (A 재생 산출물 필요)
        fired = json.loads(A_REPLAY_PATH.read_text(encoding="utf-8"))[
            "demotion_fired_records"]
        out["demotion_fired_n"] = len(fired)
        pairs = [(r["symbol"], r["sat"]) for r in fired]
        cur.execute(
            """
            SELECT CASE WHEN classified_at >= %s THEN 'post' ELSE 'pre' END era,
                   classification, count(*)
              FROM backtest_classification
             WHERE (symbol, analyzed_for_date::text) IN
                   (SELECT unnest(%s::text[]), unnest(%s::text[]))
             GROUP BY 1, 2 ORDER BY 1, 2
            """,
            (MERGE_CUT, [p[0] for p in pairs], [p[1] for p in pairs]))
        obedience: dict = {}
        for era, cls, n in cur.fetchall():
            obedience.setdefault(era, {})[cls] = n
        out["demotion_obedience"] = obedience
        out["demotion_violations"] = {
            era: d.get("entry", 0) for era, d in obedience.items()}

        # 3. 머지 후 entry / 밴드 발화 상세
        cur.execute(
            """
            SELECT symbol, analyzed_for_date, classification, watch_reason,
                   pivot_price,
                   (SELECT COALESCE(adj_close, close) FROM daily_prices p
                     WHERE p.ticker = b.symbol AND p.date <= b.analyzed_for_date + 1
                     ORDER BY p.date DESC LIMIT 1),
                   triggered_rules ? '8_5_extended_band'
              FROM backtest_classification b
             WHERE classified_at >= %s
               AND (classification = 'entry'
                    OR triggered_rules ? '8_5_extended_band')
             ORDER BY analyzed_for_date
            """, (MERGE_CUT,))
        out["post_entry_rows"] = [
            {"symbol": r[0], "sat": str(r[1]), "classification": r[2],
             "watch_reason": r[3],
             "pivot_price": float(r[4]) if r[4] is not None else None,
             "close_at": float(r[5]) if r[5] is not None else None,
             "banded": bool(r[6])}
            for r in cur.fetchall()
        ]

        # 4. §8.5 would-be (머지 전 entry)
        cur.execute(
            """
            SELECT 'weekly' src, count(*),
                   count(*) FILTER (WHERE c.close > w.pivot_price * %s)
              FROM weekly_classification w
              JOIN LATERAL (
                SELECT COALESCE(adj_close, close) AS close FROM daily_prices p
                 WHERE p.ticker = w.symbol AND p.date <= w.classified_at::date
                 ORDER BY p.date DESC LIMIT 1) c ON true
             WHERE w.classification = 'entry' AND w.pivot_price IS NOT NULL
               AND w.classified_at < '2026-07-13'
            UNION ALL
            SELECT 'backtest', count(*),
                   count(*) FILTER (WHERE c.close > b.pivot_price * %s)
              FROM backtest_classification b
              JOIN LATERAL (
                SELECT COALESCE(adj_close, close) AS close FROM daily_prices p
                 WHERE p.ticker = b.symbol AND p.date <= b.analyzed_for_date + 1
                 ORDER BY p.date DESC LIMIT 1) c ON true
             WHERE b.classification = 'entry' AND b.pivot_price IS NOT NULL
               AND b.classified_at < %s
            """,
            (PIVOT_EXTENDED_BAND_MULT, PIVOT_EXTENDED_BAND_MULT, MERGE_CUT))
        out["band_would_be_premerge"] = {
            r[0]: {"entry_n": r[1], "would_fire": r[2]} for r in cur.fetchall()}

        # 5. F1 전수조사
        cur.execute(
            """
            SELECT CASE WHEN high = 0 THEN 'halt_like(high=0)'
                        ELSE 'factor_mismatch(high>0)' END pop,
                   count(*), count(DISTINCT ticker),
                   count(*) FILTER (WHERE date >= '2025-01-01'),
                   max(adj_close - adj_high)
              FROM daily_prices WHERE adj_close > adj_high GROUP BY 1
            """)
        out["f1_adj_close_gt_high"] = {
            r[0]: {"rows": r[1], "tickers": r[2], "since_2025": r[3],
                   "max_gap": float(r[4])}
            for r in cur.fetchall()
        }
        cur.execute("SELECT count(*) FROM daily_prices WHERE adj_close < adj_low")
        out["f1_adj_close_lt_low"] = cur.fetchone()[0]

    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "post_entry_rows"},
                     ensure_ascii=False, indent=2))
    print(f"post_entry_rows: {len(out['post_entry_rows'])}건")
    print(f"saved → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
