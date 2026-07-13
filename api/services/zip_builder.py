"""LLM 분석/검증 ZIP 빌더. 14(원본 분석)~15(검증 모드) 파일 묶기."""
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
- **본 ZIP 의 모드: {mode}**  ← `원본 분석` (analysis_result 없음) 또는 `검증` (analysis_result 포함)

## 모드별 사용법

### A. 원본 분석 모드 — analysis_result.json 없음

1. **Step 1**: `prompt_step1_analyze.md` 와 함께 다음을 입력:
   - `payload.json` (텍스트로)
   - `daily_chart.png`, `weekly_chart.png` (이미지)

   → LLM 이 classification (entry/watch/ignore) + pattern + risk_flags 반환.

2. **Step 2** (Step 1 결과가 `entry` 일 때만): `prompt_step2_entry_params.md` 와 함께:
   - `payload.json` + Step 1 결과를 `prior_analysis` 로 포함
   - `daily_chart.png`, `weekly_chart.png`

   → LLM 이 진입 파라미터 18개 필드 반환.

### B. 검증 모드 — analysis_result.json 포함 (자동 채워짐)

ZIP 에 `analysis_result.json` 이 포함돼 있다면 *이미 시스템 LLM 이 수행한 분석* 입니다. 다른 LLM (다른 모델 / 더 큰 모델 / 다른 제공사) 에 *검증* 을 요청할 때:

1. `prompt_verify.md` 를 system prompt 로 사용.
2. user input 에 다음을 함께 제공:
   - `payload.json`, `minervini.json`, `market_context.json`, `corporate_actions.json` (원본 입력)
   - `daily_chart.png`, `weekly_chart.png` (차트)
   - `analysis_result.json` (검증 대상)
   - `prompt_step1_analyze.md` (원본 분석이 따른 룰의 출처)
3. 출력 = 5 차원 검증 결과 JSON (`agreement` + `dimensions` + `key_book_citations` 등).

검증 결과가 `disagree` 이면 두 LLM 의 판단 충돌 — 사람이 책 인용으로 최종 판단.

## 파일 설명

| 파일 | 설명 | 모드 A | 모드 B |
|---|---|---|---|
| `README.md` | 이 파일 | ✓ | ✓ |
| `prompt_step1_analyze.md` | 원본 분석 prompt (룰의 출처) | ✓ | ✓ |
| `prompt_step2_entry_params.md` | 진입 파라미터 prompt | ✓ | ✓ |
| `prompt_verify.md` | 검증 prompt | ✓ | ✓ |
| `payload.json` | 통합 페이로드 (LLM 입력 핵심) | ✓ | ✓ |
| `market_context.json` | 시장 컨텍스트 | ✓ | ✓ |
| `corporate_actions.json` | 기업행위 이력 | ✓ | ✓ |
| `minervini.json` | 8 조건 detail | ✓ | ✓ |
| `daily.csv` / `weekly.csv` | 종목 시계열 | ✓ | ✓ |
| `market_index_daily.csv` / `market_index_weekly.csv` | 시장 지수 | ✓ | ✓ |
| `daily_chart.png` / `weekly_chart.png` | 차트 이미지 | ✓ | ✓ |
| `analysis_result.json` | **시스템 LLM 의 분석 결과 (검증 대상)** | — | ✓ |

## 검증 모드에서 LLM 호출 예시

```
[system] {{prompt_verify.md 본문}}
[user]
  다음은 종목 {{ticker}} 의 분석 결과 검증 요청입니다.

  [입력 데이터]
  payload.json, minervini.json, market_context.json, corporate_actions.json
  weekly_chart.png, daily_chart.png

  [검증 대상]
  analysis_result.json

  [원본 분석이 따른 룰]
  prompt_step1_analyze.md

  → 위 5 차원으로 검증해 JSON 출력 부탁드립니다.
```
"""


def _fetch_latest_analysis_result(conn: Connection, ticker: str, on_date: date) -> dict | None:
    """weekly_classification 의 on_date 이하 가장 최근 분류 1건을 dict 로. 없으면 None.

    on_date 상한이 없으면 과거 시점 ZIP(point-in-time)에 그 이후 분류가 들어가
    README 의 분석 기준일과 모순된다 (corporate_actions ce10e56 과 동일 클래스
    look-ahead)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT symbol, classified_at, source, classification, pattern,
                   pivot_price, pivot_basis, base_high, base_low,
                   base_depth_pct, base_start_date, risk_flags,
                   confidence, reasoning, llm_call_duration_s,
                   llm_input_tokens, llm_output_tokens
              FROM weekly_classification
             WHERE symbol = %s
               AND COALESCE(analyzed_for_date, classified_at::date) <= %s
             ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
             LIMIT 1
            """,
            (ticker, on_date),
        )
        row = cur.fetchone()
    if row is None:
        return None
    (symbol, classified_at, source, classification, pattern,
     pivot_price, pivot_basis, base_high, base_low,
     base_depth_pct, base_start_date, risk_flags,
     confidence, reasoning, dur, tok_in, tok_out) = row
    return {
        "symbol": symbol,
        "classified_at": classified_at.isoformat() if classified_at else None,
        "source": source,
        "classification": classification,
        "pattern": pattern,
        "pivot_price": float(pivot_price) if pivot_price is not None else None,
        "pivot_basis": pivot_basis,
        "base_high": float(base_high) if base_high is not None else None,
        "base_low": float(base_low) if base_low is not None else None,
        "base_depth_pct": float(base_depth_pct) if base_depth_pct is not None else None,
        "base_start_date": base_start_date.isoformat() if base_start_date else None,
        "risk_flags": risk_flags if isinstance(risk_flags, list) else (risk_flags or []),
        "confidence": float(confidence) if confidence is not None else None,
        "reasoning": reasoning,
        "llm_call_duration_s": float(dur) if dur is not None else None,
        "llm_input_tokens": tok_in,
        "llm_output_tokens": tok_out,
    }


def build_analysis_zip(conn: Connection, ticker: str, on_date: date | None = None,
                       include_prior_analysis: bool = True) -> bytes:
    """분석/검증 ZIP 빌더. 14 또는 15 파일 묶기.

    종목에 weekly_classification 분류 이력이 있으면(on_date 이하)
    analysis_result.json 을 추가해 *검증 모드 ZIP* (15 파일) 생성.
    분류 이력 없으면 *원본 분석 ZIP* (14 파일 — prompt_verify.md 는 항상 포함).
    """
    if on_date is None:
        on_date = date.today()

    # Phase 0 Step 3 — integrity guard (raise DataIntegrityError 시 호출자가 정책 결정)
    from api.services.integrity_guard import check_data_integrity
    check_data_integrity(conn, ticker, on_date)

    with conn.cursor() as cur:
        cur.execute("SELECT name, market, sector FROM stocks WHERE ticker = %s", (ticker,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Stock not found: {ticker}")
    name, market, sector = row

    # 분석 결과 (있다면) — 검증 모드 활성화 트리거. on_date 이하만 (look-ahead 방지)
    analysis_result = _fetch_latest_analysis_result(conn, ticker, on_date) if include_prior_analysis else None
    mode = "검증 (analysis_result 포함)" if analysis_result else "원본 분석"

    payload = build_payload(conn, ticker, on_date)
    market_ctx = build_market_context(conn, market, on_date)
    corp_actions = build_corporate_actions(conn, ticker, lookback_years=5, as_of_date=on_date)
    minervini = build_minervini_detail(conn, ticker, on_date)

    daily_csv = build_daily_csv(conn, ticker, days=60, on_date=on_date)
    weekly_csv = build_weekly_csv(conn, ticker, weeks=104, on_date=on_date)
    index_code = INDEX_CODE_MAP.get(market, "1001")
    market_index_daily_csv = build_index_csv(conn, index_code, "daily", lookback=60, on_date=on_date)
    market_index_weekly_csv = build_index_csv(conn, index_code, "weekly", lookback=104, on_date=on_date)

    daily_chart_png = render_daily_chart(conn, ticker, range_days=365, on_date=on_date)
    weekly_chart_png = render_weekly_chart(conn, ticker, range_weeks=104, on_date=on_date)

    prompt_step1 = (PROMPTS_DIR / "analyze_chart_v3.md").read_text(encoding="utf-8")
    # #21: 파일 상단 RETIRED 배너(blockquote)는 아카이브 안내문 — 수동 분석 ZIP 에선
    # 이 문서가 Step-2 '지시문 본문'이므로 배너를 제거해 LLM 이 "사용되지 않는 지시문"
    # 이라는 메타 문장에 반응하지 않게 한다(규칙 본문은 은퇴 시점 동결값 그대로).
    _step2_raw = (PROMPTS_DIR / "calculate_entry_params_v2_0.md").read_text(encoding="utf-8")
    prompt_step2 = "\n".join(
        line for line in _step2_raw.splitlines() if not line.startswith("> ")
    ).lstrip("\n")
    prompt_verify = (PROMPTS_DIR / "verify_analysis_v1.md").read_text(encoding="utf-8")

    readme = README_TEMPLATE.format(
        ticker=ticker, name=name, market=market, sector=sector or "-",
        as_of_date=on_date.isoformat(),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        mode=mode,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", readme)
        zf.writestr("prompt_step1_analyze.md", prompt_step1)
        zf.writestr("prompt_step2_entry_params.md", prompt_step2)
        zf.writestr("prompt_verify.md", prompt_verify)
        zf.writestr("payload.json", json.dumps(payload, ensure_ascii=False, indent=2))
        zf.writestr("market_context.json", json.dumps(market_ctx, ensure_ascii=False, indent=2))
        zf.writestr("corporate_actions.json", json.dumps(corp_actions, ensure_ascii=False, indent=2))
        zf.writestr("minervini.json", json.dumps(minervini, ensure_ascii=False, indent=2))
        zf.writestr("daily.csv", daily_csv)
        zf.writestr("weekly.csv", weekly_csv)
        zf.writestr("market_index_daily.csv", market_index_daily_csv)
        zf.writestr("market_index_weekly.csv", market_index_weekly_csv)
        zf.writestr("daily_chart.png", daily_chart_png)
        zf.writestr("weekly_chart.png", weekly_chart_png)
        if analysis_result is not None:
            zf.writestr("analysis_result.json", json.dumps(analysis_result, ensure_ascii=False, indent=2))
    return buf.getvalue()
