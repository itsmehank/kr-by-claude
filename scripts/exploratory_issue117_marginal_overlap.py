"""#117 Q3 선행 점검 — 반복 전환 × marginal_count 중복도. exploratory, 읽기전용.

질문(전문가 3차): 경계 진동(반복 전환) 이벤트가 기존 marginal 강등 메커니즘
(marginal = PASS 이면서 margin < TT_MARGIN_MARGINAL_PCT(3.0)% 인 조건 수,
강등 컷 = TT_MARGINAL_DEMOTION_COUNT(3))으로 이미 포착되는가.

margin 산식 = api/services/minervini_detail_builder.py 의 8조건식을 SQL 재현.
그룹: first(관측창 첫 전환) / repeat_le63(직전 전환과 63행 이내 — 쿨다운 탈락분)
/ repeat_gt63. 각 그룹의 marginal_count 분포 비교.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.db.connection import connect

SQL = """
WITH lagged AS (
  SELECT ticker, date, minervini_pass, adj_close, sma_50, sma_150, sma_200,
         w52_high, w52_low, rs_rating,
         LAG(minervini_pass) OVER w AS prev,
         LAG(sma_200, 22) OVER w AS sma200_22,
         ROW_NUMBER() OVER w AS rn
  FROM daily_indicators
  WINDOW w AS (PARTITION BY ticker ORDER BY date)
),
trans AS (
  SELECT ticker, date, rn,
         rn - LAG(rn) OVER (PARTITION BY ticker ORDER BY date) AS gap,
         CASE WHEN sma_150 > 0 AND sma_200 > 0 THEN
           LEAST((adj_close - sma_150)/sma_150, (sma_150 - sma_200)/sma_200)*100
         END AS m1,
         CASE WHEN sma_200 > 0 THEN (sma_150 - sma_200)/sma_200*100 END AS m2,
         CASE WHEN sma200_22 > 0 THEN (sma_200 - sma200_22)/sma200_22*100 END AS m3,
         CASE WHEN sma_150 > 0 AND sma_200 > 0 THEN
           LEAST((sma_50 - sma_150)/sma_150, (sma_150 - sma_200)/sma_200)*100
         END AS m4,
         CASE WHEN sma_50 > 0 THEN (adj_close - sma_50)/sma_50*100 END AS m5,
         CASE WHEN w52_low > 0 THEN
           (adj_close - w52_low*1.25)/(w52_low*1.25)*100 END AS m6,
         CASE WHEN w52_high > 0 THEN
           (adj_close - w52_high*0.75)/(w52_high*0.75)*100 END AS m7,
         (rs_rating - 70)::numeric AS m8
  FROM lagged
  WHERE minervini_pass = true AND prev = false
),
scored AS (
  SELECT CASE WHEN gap IS NULL THEN 'first'
              WHEN gap <= 63 THEN 'repeat_le63'
              ELSE 'repeat_gt63' END AS grp,
         (m1 < 3.0)::int + (m2 < 3.0)::int + (m3 < 3.0)::int + (m4 < 3.0)::int
         + (m5 < 3.0)::int + (m6 < 3.0)::int + (m7 < 3.0)::int + (m8 < 3.0)::int
         AS mc,
         (m1 IS NULL OR m2 IS NULL OR m3 IS NULL OR m4 IS NULL OR m5 IS NULL
          OR m6 IS NULL OR m7 IS NULL OR m8 IS NULL) AS has_null
  FROM trans
)
SELECT grp, COUNT(*) AS n,
       COUNT(*) FILTER (WHERE has_null) AS n_null,
       ROUND(AVG(mc) FILTER (WHERE NOT has_null), 3) AS mean_mc,
       ROUND(AVG((mc >= 1)::int) FILTER (WHERE NOT has_null), 3) AS share_ge1,
       ROUND(AVG((mc >= 2)::int) FILTER (WHERE NOT has_null), 3) AS share_ge2,
       ROUND(AVG((mc >= 3)::int) FILTER (WHERE NOT has_null), 3) AS share_ge3
FROM scored GROUP BY grp ORDER BY grp;
"""


def main() -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SQL)
        rows = cur.fetchall()
    out = {"issue": 117, "grade": "exploratory",
           "marginal_pct": 3.0, "demotion_count": 3,
           "groups": {r[0]: {"n": r[1], "n_null": r[2],
                             "mean_marginal_count": float(r[3]),
                             "share_mc_ge1": float(r[4]),
                             "share_mc_ge2": float(r[5]),
                             "share_mc_ge3_demotion_cut": float(r[6])}
                      for r in rows}}
    path = (f"data/backtest/exploratory_issue117_marginal_overlap_"
            f"{date.today():%Y%m%d}.json")
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out["groups"], ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
