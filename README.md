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
- 시장 컨텍스트 백필: `uv run python -m kr_pipeline.market_context --mode=backfill`
- 시장 컨텍스트 증분: `uv run python -m kr_pipeline.market_context --mode=incremental --window-days=30`
- 시장 컨텍스트 재적재: `uv run python -m kr_pipeline.market_context --mode=full-refresh`
- 기업행위 매핑 갱신: `uv run python -m kr_pipeline.corporate_actions --mode=refresh-mapping`
- 기업행위 백필: `uv run python -m kr_pipeline.corporate_actions --mode=backfill --years=5`
- 기업행위 증분: `uv run python -m kr_pipeline.corporate_actions --mode=incremental --window-days=7`

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

-- 오늘의 Pocket Pivot 종목 (V2)
SELECT i.date, s.ticker, s.name, s.sector, i.volume_ratio_50d, i.rs_rating
  FROM daily_indicators i
  JOIN stocks s USING (ticker)
 WHERE i.date = (SELECT MAX(date) FROM daily_indicators)
   AND i.pocket_pivot_flag = TRUE
 ORDER BY i.volume_ratio_50d DESC;

-- 최근 25 영업일 시장 distribution day 누적 (#4 시장 추세 판정 입력)
SELECT date, 
       COUNT(*) FILTER (WHERE distribution_day_flag = TRUE) AS distribution_count
  FROM daily_indicators
 WHERE date >= (SELECT MAX(date) FROM daily_indicators) - INTERVAL '40 days'
 GROUP BY date
 ORDER BY date DESC LIMIT 25;

-- Volume dry-up + RS Rating 강세 (base 형성 후보)
SELECT i.date, s.ticker, s.name, i.volume_ratio_50d, i.rs_rating
  FROM daily_indicators i
  JOIN stocks s USING (ticker)
 WHERE i.date = (SELECT MAX(date) FROM daily_indicators)
   AND i.volume_dry_up_flag = TRUE
   AND i.rs_rating >= 70
 ORDER BY i.rs_rating DESC LIMIT 20;

-- 오늘의 시장 컨텍스트 (KOSPI + KOSDAQ)
SELECT date, index_code, current_status, 
       distribution_day_count_last_25, 
       last_follow_through_day, 
       days_since_follow_through,
       pct_stocks_above_200d_ma
  FROM market_context_daily
 WHERE date = (SELECT MAX(date) FROM market_context_daily)
 ORDER BY index_code;

-- 최근 30 일 KOSPI 시장 추세 변화
SELECT date, current_status, distribution_day_count_last_25, pct_stocks_above_200d_ma
  FROM market_context_daily
 WHERE index_code = '1001'
   AND date >= (SELECT MAX(date) FROM market_context_daily) - INTERVAL '30 days'
 ORDER BY date DESC;

-- 12주 이내 역분할 발생 종목 (LLM 분석 우선 제외 대상)
SELECT ticker, event_date, event_type, ratio, raw_disclosure_title
  FROM corporate_actions
 WHERE event_type IN ('reverse_split', 'capital_reduction')
   AND event_date >= CURRENT_DATE - INTERVAL '84 days'
 ORDER BY event_date DESC;

-- 최근 1년 이벤트 종류 분포
SELECT event_type, COUNT(*) AS cnt
  FROM corporate_actions
 WHERE event_date >= CURRENT_DATE - INTERVAL '1 year'
 GROUP BY event_type
 ORDER BY cnt DESC;

-- 매핑 없는 활성 종목 (refresh-mapping 필요한지 확인)
SELECT COUNT(*) AS missing_mapping
  FROM stocks s
 WHERE s.delisted_at IS NULL
   AND NOT EXISTS (SELECT 1 FROM dart_corp_codes d WHERE d.stock_code = s.ticker);
```
