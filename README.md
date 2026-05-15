# kr-by-claude

KOSPI / KOSDAQ 일봉 데이터 적재 파이프라인 및 후속 분석 도구.

## 셋업
1. `uv sync`
2. `.env.example` 를 `.env` 로 복사 후 DB URL 채움
3. `.env` 환경변수 로드 후 `psql "$DATABASE_URL" -f kr_pipeline/db/schema.sql` 로 스키마 생성
   - 셸에서 한 번에: `set -a; source .env; set +a; psql "$DATABASE_URL" -f kr_pipeline/db/schema.sql`

## 실행
- 종목 마스터: `uv run python -m kr_pipeline.universe`
- 일봉 백필: `uv run python -m kr_pipeline.ohlcv --mode=backfill --years=2`
- 일봉 증분: `uv run python -m kr_pipeline.ohlcv --mode=incremental --window-days=30`
- 수정종가 재적재: `uv run python -m kr_pipeline.ohlcv --mode=full-refresh`
- 주봉 백필: `uv run python -m kr_pipeline.weekly --mode=backfill`
- 주봉 증분: `uv run python -m kr_pipeline.weekly --mode=incremental --window-weeks=4`
- 주봉 재적재: `uv run python -m kr_pipeline.weekly --mode=full-refresh`
- 지표 일봉 백필: `uv run python -m kr_pipeline.indicators --target=daily --mode=backfill`
- 지표 일봉 증분: `uv run python -m kr_pipeline.indicators --target=daily --mode=incremental --window-days=30`
- 지표 일봉 재적재: `uv run python -m kr_pipeline.indicators --target=daily --mode=full-refresh`
- 지표 주봉 백필: `uv run python -m kr_pipeline.indicators --target=weekly --mode=backfill`
- 지표 주봉 증분: `uv run python -m kr_pipeline.indicators --target=weekly --mode=incremental --window-weeks=4`
- 지표 주봉 재적재: `uv run python -m kr_pipeline.indicators --target=weekly --mode=full-refresh`

## Cron 등록

`scripts/cron.example` 참고. `crontab -e` 로 등록.

## 운영 점검 쿼리

```sql
-- 최근 10 회 실행 현황
SELECT id, pipeline, mode, status, started_at, finished_at, rows_affected
FROM pipeline_runs ORDER BY id DESC LIMIT 10;

-- 가장 최근 영업일에 일봉이 안 들어온 종목 수
SELECT COUNT(*) FROM stocks s WHERE s.delisted_at IS NULL AND NOT EXISTS (
  SELECT 1 FROM daily_prices d
  WHERE d.ticker = s.ticker AND d.date = (SELECT MAX(date) FROM daily_prices)
);

-- 가장 최근 주봉 종목 수
SELECT week_end_date, COUNT(DISTINCT ticker) 
FROM weekly_prices 
WHERE week_end_date = (SELECT MAX(week_end_date) FROM weekly_prices)
GROUP BY 1;

-- 종목별 주봉 카운트 분포 (상위 10)
SELECT ticker, COUNT(*) AS week_count 
FROM weekly_prices 
GROUP BY ticker 
ORDER BY 2 DESC LIMIT 10;

-- 미너비니 통과 + RS Rating 80 이상 종목 (#4 분석 대상)
SELECT i.date, s.ticker, s.name, s.sector, i.rs_rating, i.adj_close
  FROM daily_indicators i
  JOIN stocks s USING (ticker)
 WHERE i.date = (SELECT MAX(date) FROM daily_indicators)
   AND i.minervini_pass = TRUE
   AND i.rs_rating >= 80
 ORDER BY i.rs_rating DESC;

-- 미너비니 8 조건 중 통과 개수 분포 (최근 영업일)
SELECT 
  (CASE WHEN minervini_c1 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c2 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c3 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c4 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c5 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c6 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c7 THEN 1 ELSE 0 END +
   CASE WHEN minervini_c8 THEN 1 ELSE 0 END) AS conditions_passed,
  COUNT(*) AS stock_count
FROM daily_indicators
WHERE date = (SELECT MAX(date) FROM daily_indicators)
GROUP BY 1 ORDER BY 1 DESC;
```
