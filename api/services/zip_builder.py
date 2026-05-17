"""LLM 분석용 ZIP 빌더. 13 파일 묶기."""
import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path

from psycopg import Connection

from api.services.chart_render import render_daily_chart, render_weekly_chart
from api.services.csv_builder import build_daily_csv, build_weekly_csv, build_index_csv
from api.services.market_context_builder import build_market_context, INDEX_CODE_MAP
from api.services.corporate_actions_builder import build_corporate_actions
from api.services.minervini_detail_builder import build_minervini_detail
from api.services.payload_builder import build_payload


PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


README_TEMPLATE = """# LLM 분석 패키지

## 대상
- 종목: {ticker} {name}
- 시장: {market}
- 섹터: {sector}
- 분석 기준일: {as_of_date}
- 생성 시각: {generated_at}

## 2-Step Workflow

1. **Step 1**: `prompt_step1_analyze.md` 와 함께 다음을 입력:
   - `payload.json` (텍스트로)
   - `daily_chart.png`, `weekly_chart.png` (이미지)

   → LLM 이 classification (entry/watch/ignore) + pattern + risk_flags 반환.

2. **Step 2** (Step 1 결과가 `entry` 일 때만): `prompt_step2_entry_params.md` 와 함께:
   - `payload.json` + Step 1 결과를 `prior_analysis` 로 포함
   - `daily_chart.png`, `weekly_chart.png`

   → LLM 이 진입 파라미터 17개 필드 반환.

## 파일 설명

- `payload.json`: 통합 페이로드 (LLM 입력 핵심)
- `market_context.json`: 시장 컨텍스트 (audit)
- `corporate_actions.json`: 기업행위 이력 (audit)
- `minervini.json`: 8 조건 detail (보조)
- `daily.csv` / `weekly.csv`: 종목 시계열 (사람용)
- `kospi_daily.csv` / `kospi_weekly.csv`: 시장 지수 시계열 (audit)
- `daily_chart.png` / `weekly_chart.png`: 차트 이미지 (LLM 멀티모달 입력)
"""


def build_analysis_zip(conn: Connection, ticker: str, on_date: date | None = None) -> bytes:
    """13 파일을 ZIP bytes 로 반환."""
    if on_date is None:
        on_date = date.today()

    with conn.cursor() as cur:
        cur.execute("SELECT name, market, sector FROM stocks WHERE ticker = %s", (ticker,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Stock not found: {ticker}")
    name, market, sector = row

    payload = build_payload(conn, ticker, on_date)
    market_ctx = build_market_context(conn, market, on_date)
    corp_actions = build_corporate_actions(conn, ticker, lookback_years=5, as_of_date=on_date)
    minervini = build_minervini_detail(conn, ticker, on_date)

    daily_csv = build_daily_csv(conn, ticker, days=60)
    weekly_csv = build_weekly_csv(conn, ticker, weeks=104)
    index_code = INDEX_CODE_MAP.get(market, "1001")
    kospi_daily_csv = build_index_csv(conn, index_code, "daily", lookback=60)
    kospi_weekly_csv = build_index_csv(conn, index_code, "weekly", lookback=104)

    daily_chart_png = render_daily_chart(conn, ticker, range_days=365)
    weekly_chart_png = render_weekly_chart(conn, ticker, range_weeks=104)

    readme = README_TEMPLATE.format(
        ticker=ticker, name=name, market=market, sector=sector or "-",
        as_of_date=on_date.isoformat(),
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )

    prompt_step1 = (PROMPTS_DIR / "analyze_chart_v3.md").read_text(encoding="utf-8")
    prompt_step2 = (PROMPTS_DIR / "calculate_entry_params_v2_0.md").read_text(encoding="utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", readme)
        zf.writestr("prompt_step1_analyze.md", prompt_step1)
        zf.writestr("prompt_step2_entry_params.md", prompt_step2)
        zf.writestr("payload.json", json.dumps(payload, ensure_ascii=False, indent=2))
        zf.writestr("market_context.json", json.dumps(market_ctx, ensure_ascii=False, indent=2))
        zf.writestr("corporate_actions.json", json.dumps(corp_actions, ensure_ascii=False, indent=2))
        zf.writestr("minervini.json", json.dumps(minervini, ensure_ascii=False, indent=2))
        zf.writestr("daily.csv", daily_csv)
        zf.writestr("weekly.csv", weekly_csv)
        zf.writestr("kospi_daily.csv", kospi_daily_csv)
        zf.writestr("kospi_weekly.csv", kospi_weekly_csv)
        zf.writestr("daily_chart.png", daily_chart_png)
        zf.writestr("weekly_chart.png", weekly_chart_png)
    return buf.getvalue()
