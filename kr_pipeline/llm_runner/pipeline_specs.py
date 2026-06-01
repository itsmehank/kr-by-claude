"""모든 pipeline (cron 작업) 추상화.

frontend / backend 양쪽이 참조하는 단일 진실. 각 pipeline 의:
  - id: UI 식별자 (slug)
  - group: 'data' | 'indicators' | 'llm'
  - label: 사용자 표시명
  - module: subprocess 호출 시 `python -m {module}` 모듈명
  - pipeline_db_name: pipeline_runs.pipeline 컬럼 값
  - mode_prefix (옵션): 같은 pipeline_db_name 안에서 daily/weekly 구분용
                       (pipeline_runs.mode 가 이 prefix 로 시작하는 행만 매치)
  - modes: 실행 모드 리스트 [{id, label, args}]
  - default_cron: cron 표현식
"""
from __future__ import annotations


PIPELINE_SPECS: list[dict] = [
    # ─── 데이터 적재 ──────────────────────────────────────────────
    {
        "id": "universe",
        "group": "data",
        "label": "Universe (종목 목록)",
        "description": "KOSPI/KOSDAQ 상장 종목 목록 (이름·섹터·시장) 을 수집해 stocks 테이블에 갱신.",
        "module": "kr_pipeline.universe",
        "pipeline_db_name": "universe",
        "modes": [
            {"id": "default", "label": "전체 갱신", "args": [], "is_heavy": False},
        ],
        "default_cron": "0 4 1 * *",
        "schedule_label": "월 1회",
        "long_description": "KOSPI/KOSDAQ 의 모든 상장 종목 (이름·섹터·시장) 을 수집해 stocks 테이블에 갱신합니다.\n\n새로 상장되거나 폐지된 종목을 반영하는 작업으로, 다른 모든 분석 작업의 기준이 되는 종목 마스터를 관리합니다.\n\n선행 작업: 없음 (외부 KRX API 만 사용)\n실행 빈도: 월 1회 — 종목 변화가 잦지 않음.",
        "inputs": [],
        "outputs": ["stocks"],
        "depends_on": [],
    },
    {
        "id": "ohlcv",
        "group": "data",
        "label": "OHLCV (일봉)",
        "description": "각 종목의 일별 OHLCV (시가·고가·저가·종가·거래량) 를 KRX 에서 수집.",
        "module": "kr_pipeline.ohlcv",
        "pipeline_db_name": "ohlcv",
        "modes": [
            {"id": "incremental", "label": "증분 (30일)",
             "args": ["--mode=incremental", "--window-days=30"], "is_heavy": False},
            {"id": "incremental-exclude-today", "label": "증분 (30일·오늘 제외, 장중 수동용)",
             "args": ["--mode=incremental", "--window-days=30", "--exclude-today"], "is_heavy": False},
            {"id": "full-refresh", "label": "보유 기간 재정정",
             "args": ["--mode=full-refresh"], "is_heavy": True},
            {"id": "backfill", "label": "과거 N년 적재",
             "args": ["--mode=backfill"], "is_heavy": True,
             "params": [{"name": "years", "label": "연 수", "type": "int", "default": 2, "min": 1, "max": 10}]},
        ],
        "default_cron": "30 18 * * 1-5",
        "schedule_label": "평일 매일",
        "long_description": "각 종목의 일별 OHLCV (시가·고가·저가·종가·거래량) 를 KRX 에서 수집해 daily_prices 테이블에 적재합니다.\n\n증분 모드는 직전 30일을 다시 가져와 정정사항을 반영하고, 백필 모드는 1년 이상 거슬러 올라갑니다.\n\n선행 작업: 없음 (외부 KRX API)\n후속 작업: weekly (주봉 집계), indicators-daily (지표 계산), llm-performance (현재가 비교)",
        "inputs": [],
        "outputs": ["daily_prices"],
        "depends_on": [],
    },
    {
        "id": "weekly",
        "group": "data",
        "label": "Weekly (주봉)",
        "description": "일봉 데이터를 주봉 OHLCV 로 집계 (월 시가 → 금 종가, 주중 고저, 거래량 합).",
        "module": "kr_pipeline.weekly",
        "pipeline_db_name": "weekly",
        "modes": [
            {"id": "incremental", "label": "증분 (4주)",
             "args": ["--mode=incremental", "--window-weeks=4"], "is_heavy": False},
            {"id": "full-refresh", "label": "보유 기간 재집계",
             "args": ["--mode=full-refresh"], "is_heavy": True},
        ],
        "default_cron": "0 3 * * 6",
        "schedule_label": "주 1회 (토)",
        "long_description": "daily_prices 데이터를 주 단위로 집계해 weekly_prices 테이블을 만듭니다.\n\n한 주의 시가는 월요일 시가, 종가는 금요일 종가, 고가·저가는 주중 최대·최소, 거래량은 합계입니다.\n\n선행 작업: ohlcv (일봉 데이터 필수)\n후속 작업: indicators-weekly (주봉 지표 계산)",
        "inputs": ["daily_prices"],
        "outputs": ["weekly_prices"],
        "depends_on": ["ohlcv"],
    },
    {
        "id": "corporate-actions",
        "group": "data",
        "label": "Corporate Actions",
        "description": "액면분할·배당·합병 등 corporate action 이력 수집 — 주가 조정 계수 (adj_close) 계산의 기반.",
        "module": "kr_pipeline.corporate_actions",
        "pipeline_db_name": "corporate_actions",
        "modes": [
            {"id": "incremental", "label": "증분 (7일)",
             "args": ["--mode=incremental", "--window-days=7"], "is_heavy": False},
            {"id": "backfill", "label": "과거 N년 적재",
             "args": ["--mode=backfill"], "is_heavy": True,
             "params": [{"name": "years", "label": "연 수", "type": "int", "default": 5, "min": 1, "max": 10}]},
            {"id": "refresh-mapping", "label": "기업코드 매핑 갱신",
             "args": ["--mode=refresh-mapping"], "is_heavy": True},
        ],
        "default_cron": "30 4 * * 6",
        "schedule_label": "주 1회 (토)",
        "long_description": "액면분할·배당·합병 등 corporate action 이력을 수집해 corporate_actions 테이블에 적재합니다.\n\n이 데이터는 주가의 조정 계수 (adj_close) 를 계산할 때 사용되며, 잘못된 액면분할 처리는 잘못된 지표로 이어집니다.\n\n선행 작업: 없음 (외부 KRX/DART API)\n후속 작업: indicators-daily, indicators-weekly (지표 계산 시 가격 조정)",
        "inputs": [],
        "outputs": ["corporate_actions"],
        "depends_on": [],
    },

    # ─── 지표 계산 ────────────────────────────────────────────────
    {
        "id": "indicators-daily",
        "group": "indicators",
        "label": "Indicators (일봉)",
        "description": "일봉 기반 기술 지표 계산 — 10/21/50/150/200일 이평선, 52주 고·저, RS rating, Minervini Trend Template 통과 여부, pocket pivot / distribution day.",
        "module": "kr_pipeline.indicators",
        "pipeline_db_name": "indicators",
        "mode_prefix": "daily-",
        "modes": [
            {"id": "incremental", "label": "증분 (30일)",
             "args": ["--target=daily", "--mode=incremental", "--window-days=30"], "is_heavy": False},
            {"id": "full-refresh", "label": "전체 기간 재계산",
             "args": ["--target=daily", "--mode=full-refresh"], "is_heavy": True},
        ],
        "default_cron": "0 19 * * 1-5",
        "schedule_label": "평일 매일",
        "long_description": "일봉 OHLCV 데이터를 기반으로 기술 지표를 계산해 daily_indicators 테이블에 적재합니다.\n\n계산 항목:\n- 이동평균선 (10/21/50/150/200일)\n- 52주 고가·저가\n- RS Rating (시장 대비 상대강도)\n- Minervini Trend Template 통과 여부\n- Pocket Pivot / Distribution Day\n\n선행 작업: ohlcv, corporate-actions (가격 조정 적용)\n후속 작업: market-context, llm-full-daily, llm-weekend",
        "inputs": ["daily_prices", "corporate_actions"],
        "outputs": ["daily_indicators"],
        "depends_on": ["ohlcv", "corporate-actions"],
    },
    {
        "id": "indicators-weekly",
        "group": "indicators",
        "label": "Indicators (주봉)",
        "description": "주봉 기반 기술 지표 계산 — 10/30/40주 이평선, 52주 고·저, RS rating, Minervini Trend Template 통과 여부.",
        "module": "kr_pipeline.indicators",
        "pipeline_db_name": "indicators",
        "mode_prefix": "weekly-",
        "modes": [
            {"id": "incremental", "label": "증분 (4주)",
             "args": ["--target=weekly", "--mode=incremental", "--window-weeks=4"], "is_heavy": False},
            {"id": "full-refresh", "label": "전체 기간 재계산",
             "args": ["--target=weekly", "--mode=full-refresh"], "is_heavy": True},
        ],
        "default_cron": "0 4 * * 6",
        "schedule_label": "주 1회 (토)",
        "long_description": "주봉 OHLCV 데이터를 기반으로 주봉 기준 기술 지표를 계산해 weekly_indicators 테이블에 적재합니다.\n\n계산 항목:\n- 이동평균선 (10/30/40주)\n- 52주 고가·저가\n- RS Rating (주봉 기준)\n- Minervini Trend Template 통과 여부\n\n선행 작업: weekly, corporate-actions\n후속 작업: llm-weekend",
        "inputs": ["weekly_prices", "corporate_actions"],
        "outputs": ["weekly_indicators"],
        "depends_on": ["weekly", "corporate-actions"],
    },
    {
        "id": "market-context",
        "group": "indicators",
        "label": "Market Context",
        "description": "시장 전반 컨텍스트 — KOSPI 추세, distribution day 카운트, follow-through day, 200일선 위 종목 비율.",
        "module": "kr_pipeline.market_context",
        "pipeline_db_name": "market_context",
        "modes": [
            {"id": "incremental", "label": "증분 (30일)",
             "args": ["--mode=incremental", "--window-days=30"], "is_heavy": False},
            {"id": "full-refresh", "label": "전체 기간 재계산",
             "args": ["--mode=full-refresh"], "is_heavy": True},
        ],
        "default_cron": "30 19 * * 1-5",
        "schedule_label": "평일 매일",
        "long_description": "시장 전반 상황 — KOSPI 와 KOSDAQ 각각의 추세 단계, distribution day 수, follow-through day, 200일선 위 종목 비율 등 — 을 계산해 market_context_daily 테이블에 적재합니다.\n\n각 종목의 LLM 분석 시 그 종목 시장의 컨텍스트를 함께 전달해 LLM 이 시장 분위기를 고려한 판단을 할 수 있게 합니다.\n\n선행 작업: indicators-daily, ohlcv (200일선 위 종목 비율 + KOSPI/KOSDAQ 지수 일봉)\n후속 작업: llm-full-daily, llm-weekend",
        "inputs": ["daily_indicators", "daily_prices"],
        "outputs": ["market_context_daily"],
        "depends_on": ["indicators-daily", "ohlcv"],
    },

    # ─── LLM 분석 ────────────────────────────────────────────────
    {
        "id": "llm-full-daily",
        "group": "llm",
        "label": "LLM 평일 전체 분석",
        "description": "LLM 으로 평일 통합 분석 — 신규 후보 분류 → 진입 시그널 생성 → 직전 시그널 평가 → 성과 backfill 한 번에.",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_daily_delta",
        "modes": [
            {"id": "default", "label": "평일 통합 (dry-run)",
             "args": ["--mode=full-daily", "--dry-run"], "is_heavy": False},
            {"id": "real", "label": "평일 통합 (실제 호출)",
             "args": ["--mode=full-daily"], "is_heavy": True},
        ],
        "default_cron": "0 20 * * 1-5",
        "schedule_label": "평일 매일",
        "long_description": "신규 종목 분류 → 진입 시그널 생성 → 직전 시그널 평가 → 성과 backfill 을 LLM 으로 통합 처리합니다.\n\nLLM 에 전달되는 payload 에는 일봉 OHLCV, 지표, 시장 컨텍스트, 액면분할 이력이 모두 포함됩니다.\n\n선행 작업: indicators-daily, market-context, ohlcv (오늘 데이터) — 모두 19:30 까지 끝난 후 20:00 에 실행\n후속 작업: 없음 (분석 결과는 신호 테이블에 직접 적재)",
        "inputs": ["daily_indicators", "market_context_daily", "daily_prices"],
        "outputs": ["entry_params", "signal_performance"],
        "depends_on": ["indicators-daily", "market-context", "ohlcv"],
    },
    {
        "id": "llm-weekend",
        "group": "llm",
        "label": "LLM 주말 분류",
        "description": "LLM 으로 주말 전체 종목 batch 분류 — Trend Stage 4단계 (accumulation / advancing / distribution / declining) 판정.",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_weekend",
        "modes": [
            {"id": "default", "label": "주말 batch (dry-run)",
             "args": ["--mode=weekend", "--dry-run"], "is_heavy": False},
            {"id": "test", "label": "테스트 (N개만 실제 호출)",
             "args": ["--mode=weekend"], "is_heavy": True,
             "params": [{"name": "limit", "label": "종목 수", "type": "int",
                         "default": 3, "min": 1, "max": 20}]},
            {"id": "real", "label": "주말 batch (실제 호출)",
             "args": ["--mode=weekend"], "is_heavy": True},
        ],
        "default_cron": "20 3 * * 6",
        "schedule_label": "주 1회 (토)",
        "long_description": "평일 분석에서 누락된 전체 종목을 LLM 으로 batch 분류합니다.\n\nMinervini Trend Stage (accumulation / advancing / distribution / declining) 4단계 판정 + 핵심 코멘트 1~2 줄.\n\n토요일 새벽 03:20 에 실행되며, 직전 금요일 데이터를 기준으로 분류합니다.\n\n선행 작업: indicators-daily, indicators-weekly, market-context (금요일 기준)\n후속 작업: 없음",
        "inputs": ["daily_indicators", "weekly_indicators", "market_context_daily"],
        "outputs": ["weekly_classification"],
        "depends_on": ["indicators-daily", "indicators-weekly", "market-context"],
    },
    {
        "id": "llm-performance",
        "group": "llm",
        "label": "LLM 성과 backfill",
        "description": "기존 signal 의 실현 성과 backfill — 진입 후 최고가·최저가·현재가 대비 RR 계산.",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_performance",
        "modes": [
            {"id": "default", "label": "Performance backfill",
             "args": ["--mode=performance"], "is_heavy": True},
        ],
        "default_cron": "0 23 * * *",
        "schedule_label": "매일",
        "long_description": "기존에 LLM 이 생성한 진입 시그널의 실현 성과를 backfill 합니다.\n\n진입 후 최고가·최저가·현재가를 비교해 RR (risk-reward), 최대 손익 등을 계산해 signal_performance 테이블에 적재합니다.\n\nLLM 호출은 없음 — 가격 데이터만으로 계산.\n\n선행 작업: ohlcv (현재가 + 과거 가격), llm-full-daily (평가 대상 시그널)\n후속 작업: 없음",
        "inputs": ["daily_prices", "entry_params"],
        "outputs": ["signal_performance"],
        "depends_on": ["ohlcv", "llm-full-daily"],
    },
]


def get_spec(pipeline_id: str) -> dict | None:
    for spec in PIPELINE_SPECS:
        if spec["id"] == pipeline_id:
            return spec
    return None


def get_mode_args(pipeline_id: str, mode_id: str) -> list[str] | None:
    spec = get_spec(pipeline_id)
    if spec is None:
        return None
    for mode in spec["modes"]:
        if mode["id"] == mode_id:
            return mode["args"]
    return None


def matches_mode_prefix(mode: str | None, prefix: str | None) -> bool:
    """mode_prefix 가 None 이면 무조건 매치. 있으면 mode.startswith(prefix)."""
    if prefix is None:
        return True
    if mode is None:
        return False
    return mode.startswith(prefix)


def get_default_cron_lines() -> list[str]:
    """PIPELINE_SPECS 의 default_cron + 첫 번째 mode args 로 cron 라인 생성."""
    from pathlib import Path
    project_dir = Path(__file__).parent.parent.parent.resolve()
    lines = []
    for spec in PIPELINE_SPECS:
        default_mode = spec["modes"][0]
        args_str = " ".join(default_mode["args"])
        cmd = f"uv run python -m {spec['module']}"
        if args_str:
            cmd = f"{cmd} {args_str}"
        cron_line = (
            f"{spec['default_cron']}  cd {project_dir} && "
            f"{cmd} >> $HOME/.kr-by-claude/cron.log 2>&1"
        )
        lines.append(cron_line)
    return lines
