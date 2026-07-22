"""(#2 2부) 패자 대조군 프리스크리닝 — 결정론, LLM 0회. 부록 B 동결 파일 생성.

준거: prereg §3 (정정 2026-07-22). 같은 창(승자 발화 분포 2024-08~2026-04)의
주간 앵커에서:
  ①스크리너 통과(minervini_pass & rs_line_not_declining_7m & 비상폐 & adj 무결 —
    recall_phase2.load_episodes 와 동일 게이트)
  ②돌파 프록시: 앵커 이후 20거래일 내, 종가가 "앵커 이전 26주 adj_high 최고가"
    상회한 첫 날 (1층 분류 부재 상태의 후보 선별용 — 실제 pivot 은 1층 백필이 재정의)
  ③패자: 돌파일 종가 대비 +60거래일(≈12주) 종가 수익률 < 0
제외: recall 감사 표본 종목(승자 오염 방지). 상한 40 — 초과 시 md5(ticker||anchor)
오름차순 40건(결정론 의사난수 — 시기 편향 방지). 종목당 최초 앵커 1건.
출력: data/backtest/issue2_control_candidates.csv (동결 = 부록 B)
"""
from __future__ import annotations

import csv
import hashlib
import os
from datetime import date
from pathlib import Path

import psycopg
from dotenv import load_dotenv

WINDOW_START = date(2024, 8, 1)
WINDOW_END = date(2026, 4, 30)
DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "backtest"
FUNNEL_CSV = DATA_DIR / "recall_funnel_20260705.csv"
OUT_CSV = DATA_DIR / "issue2_control_candidates.csv"


def main() -> None:
    load_dotenv()
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    with open(FUNNEL_CSV) as f:
        winners = {r["ticker"] for r in csv.DictReader(f)}

    with conn.cursor() as cur:
        # 주간 앵커 (recall_phase2.load_anchors 와 동일 규약)
        cur.execute(
            "SELECT date FROM index_daily WHERE index_code='1001'"
            " AND date BETWEEN %s AND %s ORDER BY date",
            (WINDOW_START, WINDOW_END),
        )
        days = [r[0] for r in cur.fetchall()]
        by_week: dict[tuple, date] = {}
        for d in days:
            iso = d.isocalendar()
            by_week[(iso[0], iso[1])] = max(d, by_week.get((iso[0], iso[1]), d))
        anchors = sorted(by_week.values())

        # 앵커별 스크리너 통과 종목
        cur.execute(
            """
            SELECT i.ticker, i.date
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date = ANY(%s)
               AND i.minervini_pass = TRUE
               AND i.rs_line_not_declining_7m = TRUE
               AND s.delisted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM daily_prices p
                    WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL)
            """,
            (anchors,),
        )
        passers = [(t, d) for t, d in cur.fetchall() if t not in winners]

    print(f"앵커 {len(anchors)}주 · 스크리너 통과 종목-앵커 {len(passers)}건 (승자 제외)")

    candidates = []
    seen_tickers: set[str] = set()
    with conn.cursor() as cur:
        for t, anchor in sorted(passers):
            if t in seen_tickers:
                continue
            # 앵커 이전 26주 고가 (돌파 기준선 프록시)
            cur.execute(
                "SELECT MAX(adj_high) FROM daily_prices "
                "WHERE ticker=%s AND date <= %s AND date > %s - INTERVAL '26 weeks'",
                (t, anchor, anchor),
            )
            ref = cur.fetchone()[0]
            if not ref:
                continue
            ref = float(ref)
            # 앵커 이후 20거래일 봉
            cur.execute(
                "SELECT date, COALESCE(adj_close, close) FROM daily_prices "
                "WHERE ticker=%s AND date > %s ORDER BY date LIMIT 20",
                (t, anchor),
            )
            fwd = [(d, float(c) if c else None) for d, c in cur.fetchall()]
            bko = next(((d, c) for d, c in fwd if c and c > ref), None)
            if not bko:
                continue
            bko_date, bko_close = bko
            # 돌파 후 60거래일 수익률
            cur.execute(
                "SELECT COALESCE(adj_close, close) FROM daily_prices "
                "WHERE ticker=%s AND date > %s ORDER BY date OFFSET 59 LIMIT 1",
                (t, bko_date),
            )
            r = cur.fetchone()
            if not r or not r[0]:
                continue
            ret12w = (float(r[0]) / bko_close - 1) * 100
            if ret12w >= 0:
                continue
            seen_tickers.add(t)
            candidates.append({
                "ticker": t, "anchor": str(anchor), "breakout_date": str(bko_date),
                "breakout_close": bko_close, "ret_12w_pct": round(ret12w, 2),
                "sort_key": hashlib.md5(f"{t}|{anchor}".encode()).hexdigest(),
            })

    candidates.sort(key=lambda c: c["sort_key"])
    frozen = candidates[:40]
    print(f"패자 후보 {len(candidates)}건 → 동결 {len(frozen)}건")
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(frozen[0].keys()))
        w.writeheader()
        w.writerows(frozen)
    print(f"동결 파일: {OUT_CSV}")


if __name__ == "__main__":
    main()
