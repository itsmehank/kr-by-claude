# kr-by-claude

KOSPI / KOSDAQ 일봉 데이터 적재 파이프라인 및 후속 분석 도구.

## 셋업
1. `uv sync`
2. `.env.example` 를 `.env` 로 복사 후 DB URL 채움
3. `psql -f kr_pipeline/db/schema.sql $DATABASE_URL` 로 스키마 생성

## 실행
- 종목 마스터: `uv run python -m kr_pipeline.universe`
- 일봉 백필: `uv run python -m kr_pipeline.ohlcv --mode=backfill --years=2`
- 일봉 증분: `uv run python -m kr_pipeline.ohlcv --mode=incremental --window-days=30`
- 수정종가 재적재: `uv run python -m kr_pipeline.ohlcv --mode=full-refresh`
