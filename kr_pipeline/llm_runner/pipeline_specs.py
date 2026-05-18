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
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--mode=full-refresh"], "is_heavy": True},
            {"id": "backfill", "label": "백필 (1년)",
             "args": ["--mode=backfill", "--years=1"], "is_heavy": True},
        ],
        "default_cron": "30 18 * * 1-5",
        "schedule_label": "평일 매일",
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
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--mode=full-refresh"], "is_heavy": True},
            {"id": "backfill", "label": "백필",
             "args": ["--mode=backfill"], "is_heavy": True},
        ],
        "default_cron": "0 3 * * 6",
        "schedule_label": "주 1회 (토)",
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
            {"id": "backfill", "label": "백필 (5년)",
             "args": ["--mode=backfill", "--years=5"], "is_heavy": True},
            {"id": "refresh-mapping", "label": "기업코드 매핑 갱신",
             "args": ["--mode=refresh-mapping"], "is_heavy": True},
        ],
        "default_cron": "30 4 * * 6",
        "schedule_label": "주 1회 (토)",
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
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--target=daily", "--mode=full-refresh"], "is_heavy": True},
            {"id": "backfill", "label": "백필",
             "args": ["--target=daily", "--mode=backfill"], "is_heavy": True},
        ],
        "default_cron": "0 19 * * 1-5",
        "schedule_label": "평일 매일",
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
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--target=weekly", "--mode=full-refresh"], "is_heavy": True},
            {"id": "backfill", "label": "백필",
             "args": ["--target=weekly", "--mode=backfill"], "is_heavy": True},
        ],
        "default_cron": "0 4 * * 6",
        "schedule_label": "주 1회 (토)",
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
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--mode=full-refresh"], "is_heavy": True},
            {"id": "backfill", "label": "백필",
             "args": ["--mode=backfill"], "is_heavy": True},
        ],
        "default_cron": "30 19 * * 1-5",
        "schedule_label": "평일 매일",
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
        "default_cron": "30 16 * * 1-5",
        "schedule_label": "평일 매일",
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
            {"id": "real", "label": "주말 batch (실제 호출)",
             "args": ["--mode=weekend"], "is_heavy": True},
        ],
        "default_cron": "20 3 * * 6",
        "schedule_label": "주 1회 (토)",
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
