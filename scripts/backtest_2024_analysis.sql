-- 2024 백테스트 분석: classification_backfill × forward-return(+4주/+12주)
-- 사용: psql postgresql://localhost/kr_pipeline -f scripts/backtest_2024_analysis.sql
WITH bf AS (
  SELECT symbol, analyzed_for_date AS sat, classification, confidence,
         pattern, watch_reason, risk_flags
  FROM classification_backfill
  WHERE analyzed_for_date BETWEEN '2024-01-06' AND '2024-12-28'
    AND symbol IN ('003230','101930','399720','200470','257720','000320','900340','267260')
),
base AS (
  SELECT b.*,
    (SELECT adj_close FROM daily_prices p
      WHERE p.ticker=b.symbol AND p.date<=b.sat ORDER BY p.date DESC LIMIT 1) AS px0
  FROM bf b
)
SELECT base.symbol, s.name, base.sat, base.classification,
  base.confidence, base.pattern, base.watch_reason, base.risk_flags,
  round((( SELECT adj_close FROM daily_prices p
            WHERE p.ticker=base.symbol AND p.date<=base.sat + 28
            ORDER BY p.date DESC LIMIT 1) / NULLIF(base.px0,0) - 1) * 100, 1) AS fwd_4w_pct,
  round((( SELECT adj_close FROM daily_prices p
            WHERE p.ticker=base.symbol AND p.date<=base.sat + 84
            ORDER BY p.date DESC LIMIT 1) / NULLIF(base.px0,0) - 1) * 100, 1) AS fwd_12w_pct
FROM base JOIN stocks s ON s.ticker=base.symbol
ORDER BY base.symbol, base.sat;
