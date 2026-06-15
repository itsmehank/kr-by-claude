"""analyze_chart_v3 입력 빌더 — ZIP 첨부 대신 **텍스트 인라인 + 차트 PNG 첨부**.

배경: ZIP 첨부 방식은 LLM 에이전트가 unzip 후 14개 파일을 도구로 탐색하느라
8~12 턴을 돌았다(측정). 입력을 프롬프트에 직접 인라인하면 turns→1 로 붕괴,
배치 처리량 ~29%↓, 잡당 토큰 ~80%↓, classification 불변(2단계 격리측정 45/45).

dedup:
  - market_context.json 만 제외 — payload.market_context 와 **바이트 동일**.
  - daily.csv / weekly.csv 는 **유지**. (daily.csv 제외 시 borderline 종목의
    late_stage_base 플래그가 baseline 대비 저하되는 정황이 있어 보존.)
  - market_index_*.csv 는 payload 에 없는 고유 데이터 → 유지.

GUARD: 데이터 정합성 검사(check_data_integrity)는 ZIP 경로(build_analysis_zip)와
동일하게 빌더 진입 시 호출 — 오염 입력 fail-fast 유지.
"""
from __future__ import annotations

import io
import json
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from psycopg import Connection

from api.services.integrity_guard import check_data_integrity
from api.services.chart_render import render_daily_chart, render_weekly_chart
from api.services.csv_builder import build_daily_csv, build_weekly_csv, build_index_csv
from api.services.market_context_builder import INDEX_CODE_MAP
from api.services.corporate_actions_builder import build_corporate_actions
from api.services.minervini_detail_builder import build_minervini_detail
from api.services.payload_builder import build_payload


def _s(x) -> str:
    return x.decode("utf-8") if isinstance(x, bytes) else x


def build_analysis_inline(
    conn: Connection, ticker: str, on_date: date
) -> tuple[str, list[str], bytes]:
    """analyze_chart_v3 인라인 입력 빌드.

    Returns:
        inline_text: 프롬프트 본문 뒤에 append 할 데이터 섹션(markdown).
        png_paths: [daily_chart.png, weekly_chart.png] 임시파일 절대경로
                   (호출자가 call_claude @첨부 후 부모 디렉토리 정리 책임).
        freeze_bytes: 감사·재현용 ZIP (inline_input.md + 차트 PNG 2장).

    Raises:
        DataIntegrityError: 데이터 정합성 가드 위반 시(호출자가 정책 결정).
        ValueError: 종목 미존재.
    """
    # 데이터 정합성 가드 — build_analysis_zip 과 동일 위치/동작 (fail-fast)
    check_data_integrity(conn, ticker, on_date)

    with conn.cursor() as cur:
        cur.execute("SELECT name, market, sector FROM stocks WHERE ticker = %s", (ticker,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Stock not found: {ticker}")
    _name, market, _sector = row

    payload = build_payload(conn, ticker, on_date)
    corp_actions = build_corporate_actions(conn, ticker, lookback_years=5, as_of_date=on_date)
    minervini = build_minervini_detail(conn, ticker, on_date)
    daily_csv = _s(build_daily_csv(conn, ticker, days=60, on_date=on_date))      # 유지
    weekly_csv = _s(build_weekly_csv(conn, ticker, weeks=104, on_date=on_date))  # 유지
    index_code = INDEX_CODE_MAP.get(market, "1001")
    idx_daily = _s(build_index_csv(conn, index_code, "daily", lookback=60, on_date=on_date))
    idx_weekly = _s(build_index_csv(conn, index_code, "weekly", lookback=104, on_date=on_date))
    # market_context.json 은 인라인 안 함 — payload.market_context 와 바이트 동일(dedup)

    daily_png = render_daily_chart(conn, ticker, range_days=365, on_date=on_date)
    weekly_png = render_weekly_chart(conn, ticker, range_weeks=104, on_date=on_date)
    pdir = Path(tempfile.mkdtemp(prefix="achart_inline_"))
    dpath = pdir / "daily_chart.png"
    dpath.write_bytes(daily_png)
    wpath = pdir / "weekly_chart.png"
    wpath.write_bytes(weekly_png)

    parts = [
        "## 입력 데이터 (인라인)",
        "아래는 분석 입력 데이터입니다. 먼저 첨부된 차트 PNG 2장"
        "(daily_chart.png, weekly_chart.png)을 examine 한 뒤 아래 데이터로 분석하세요.",
        "### payload.json\n```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```",
        "### minervini.json\n```json\n" + json.dumps(minervini, ensure_ascii=False, indent=2) + "\n```",
        "### corporate_actions.json\n```json\n" + json.dumps(corp_actions, ensure_ascii=False, indent=2) + "\n```",
        "### daily.csv\n```csv\n" + daily_csv + "\n```",
        "### weekly.csv\n```csv\n" + weekly_csv + "\n```",
        "### market_index_daily.csv\n```csv\n" + idx_daily + "\n```",
        "### market_index_weekly.csv\n```csv\n" + idx_weekly + "\n```",
    ]
    inline_text = "\n\n".join(parts)

    # freeze 아티팩트(감사·재현용): 실제로 전송된 입력 = inline_text + 차트 2장
    fbuf = io.BytesIO()
    with zipfile.ZipFile(fbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inline_input.md", inline_text)
        zf.writestr("daily_chart.png", daily_png)
        zf.writestr("weekly_chart.png", weekly_png)

    return inline_text, [str(dpath), str(wpath)], fbuf.getvalue()
