"""(#45) 결정론 사전 측정 — extended-at-trigger 후 같은 주 buy zone 복귀 빈도.

read-only. 방법·기준: docs/superpowers/specs/2026-07-21-issue45-extended-gate-prereg.md §2.
윈도 = analyzed_for_date(토요일 앵커) + 달력 7일(다음 금요일까지 ≈ 5거래일).
"""
import os

import psycopg

SQL = """
WITH entries AS (
  SELECT symbol, analyzed_for_date, pivot_price::float AS pivot
    FROM backtest_classification
   WHERE classification = 'entry' AND pivot_price IS NOT NULL
),
win AS (
  SELECT e.symbol, e.analyzed_for_date, e.pivot, p.date,
         COALESCE(p.adj_close, p.close)::float AS c
    FROM entries e
    JOIN daily_prices p
      ON p.ticker = e.symbol
     AND p.date > e.analyzed_for_date
     AND p.date <= e.analyzed_for_date + 7
),
first_trig AS (
  SELECT DISTINCT ON (symbol, analyzed_for_date)
         symbol, analyzed_for_date, pivot, date AS trig_date, c AS trig_close
    FROM win
   WHERE c > pivot
   ORDER BY symbol, analyzed_for_date, date
),
ext AS (
  SELECT * FROM first_trig WHERE trig_close > pivot * 1.05
),
returned AS (
  SELECT DISTINCT x.symbol, x.analyzed_for_date
    FROM ext x
    JOIN win w
      ON w.symbol = x.symbol
     AND w.analyzed_for_date = x.analyzed_for_date
     AND w.date > x.trig_date
   WHERE w.c > x.pivot AND w.c <= x.pivot * 1.05
)
SELECT (SELECT count(*) FROM entries)    AS entry_cells,
       (SELECT count(*) FROM first_trig) AS triggered,
       (SELECT count(*) FROM ext)        AS extended_at_trigger,
       (SELECT count(*) FROM returned)   AS returned_same_week
"""


def main() -> None:
    dsn = os.environ.get("DATABASE_URL", "dbname=kr_pipeline")
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL)
        entry_cells, triggered, ext, ret = cur.fetchone()
    print(f"entry cells (pivot 有): {entry_cells}")
    print(f"first trigger in-week:  {triggered}")
    print(f"extended at trigger:    {ext} ({ext / triggered * 100:.1f}% of triggered)" if triggered else "n/a")
    print(f"returned to buy zone:   {ret} ({ret / ext * 100:.1f}% of extended)" if ext else "returned: n/a")


if __name__ == "__main__":
    main()
