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
        "module": "kr_pipeline.universe",
        "pipeline_db_name": "universe",
        "modes": [
            {"id": "default", "label": "전체 갱신", "args": []},
        ],
        "default_cron": "0 4 1 * *",
    },
    {
        "id": "ohlcv",
        "group": "data",
        "label": "OHLCV (일봉)",
        "module": "kr_pipeline.ohlcv",
        "pipeline_db_name": "ohlcv",
        "modes": [
            {"id": "incremental", "label": "증분 (30일)",
             "args": ["--mode=incremental", "--window-days=30"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--mode=full-refresh"]},
            {"id": "backfill", "label": "백필 (1년)",
             "args": ["--mode=backfill", "--years=1"]},
        ],
        "default_cron": "30 18 * * 1-5",
    },
    {
        "id": "weekly",
        "group": "data",
        "label": "Weekly (주봉)",
        "module": "kr_pipeline.weekly",
        "pipeline_db_name": "weekly",
        "modes": [
            {"id": "incremental", "label": "증분 (4주)",
             "args": ["--mode=incremental", "--window-weeks=4"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--mode=full-refresh"]},
            {"id": "backfill", "label": "백필",
             "args": ["--mode=backfill"]},
        ],
        "default_cron": "0 3 * * 6",
    },
    {
        "id": "corporate-actions",
        "group": "data",
        "label": "Corporate Actions",
        "module": "kr_pipeline.corporate_actions",
        "pipeline_db_name": "corporate_actions",
        "modes": [
            {"id": "incremental", "label": "증분 (7일)",
             "args": ["--mode=incremental", "--window-days=7"]},
            {"id": "backfill", "label": "백필 (5년)",
             "args": ["--mode=backfill", "--years=5"]},
            {"id": "refresh-mapping", "label": "기업코드 매핑 갱신",
             "args": ["--mode=refresh-mapping"]},
        ],
        "default_cron": "30 4 * * 6",
    },

    # ─── 지표 계산 ────────────────────────────────────────────────
    {
        "id": "indicators-daily",
        "group": "indicators",
        "label": "Indicators (일봉)",
        "module": "kr_pipeline.indicators",
        "pipeline_db_name": "indicators",
        "mode_prefix": "daily-",
        "modes": [
            {"id": "incremental", "label": "증분 (30일)",
             "args": ["--target=daily", "--mode=incremental", "--window-days=30"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--target=daily", "--mode=full-refresh"]},
            {"id": "backfill", "label": "백필",
             "args": ["--target=daily", "--mode=backfill"]},
        ],
        "default_cron": "0 19 * * 1-5",
    },
    {
        "id": "indicators-weekly",
        "group": "indicators",
        "label": "Indicators (주봉)",
        "module": "kr_pipeline.indicators",
        "pipeline_db_name": "indicators",
        "mode_prefix": "weekly-",
        "modes": [
            {"id": "incremental", "label": "증분 (4주)",
             "args": ["--target=weekly", "--mode=incremental", "--window-weeks=4"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--target=weekly", "--mode=full-refresh"]},
            {"id": "backfill", "label": "백필",
             "args": ["--target=weekly", "--mode=backfill"]},
        ],
        "default_cron": "0 4 * * 6",
    },
    {
        "id": "market-context",
        "group": "indicators",
        "label": "Market Context",
        "module": "kr_pipeline.market_context",
        "pipeline_db_name": "market_context",
        "modes": [
            {"id": "incremental", "label": "증분 (30일)",
             "args": ["--mode=incremental", "--window-days=30"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--mode=full-refresh"]},
            {"id": "backfill", "label": "백필",
             "args": ["--mode=backfill"]},
        ],
        "default_cron": "30 19 * * 1-5",
    },

    # ─── LLM 분석 ────────────────────────────────────────────────
    {
        "id": "llm-full-daily",
        "group": "llm",
        "label": "LLM 평일 전체 분석",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_daily_delta",
        "modes": [
            {"id": "default", "label": "평일 통합 (dry-run)",
             "args": ["--mode=full-daily", "--dry-run"]},
            {"id": "real", "label": "평일 통합 (실제 호출)",
             "args": ["--mode=full-daily"]},
        ],
        "default_cron": "30 16 * * 1-5",
    },
    {
        "id": "llm-weekend",
        "group": "llm",
        "label": "LLM 주말 분류",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_weekend",
        "modes": [
            {"id": "default", "label": "주말 batch (dry-run)",
             "args": ["--mode=weekend", "--dry-run"]},
            {"id": "real", "label": "주말 batch (실제 호출)",
             "args": ["--mode=weekend"]},
        ],
        "default_cron": "20 3 * * 6",
    },
    {
        "id": "llm-performance",
        "group": "llm",
        "label": "LLM 성과 backfill",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_performance",
        "modes": [
            {"id": "default", "label": "Performance backfill",
             "args": ["--mode=performance"]},
        ],
        "default_cron": "0 23 * * *",
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
