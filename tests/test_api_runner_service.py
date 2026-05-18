"""runner_service — subprocess 실행 + 중복/동시 방지."""
from datetime import datetime, date, timezone, timedelta


def test_check_recent_success_today_blocks_rerun(db):
    """오늘 같은 모드 success run 있으면 재실행 거부."""
    from api.services.runner_service import check_can_run

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at, rows_affected)
               VALUES ('llm_weekend', 'weekend', 'success', %s, %s, 100)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )

    result = check_can_run(db, mode="weekend")
    assert result["can_run"] is False
    assert result["reason"] == "duplicate"
    assert result["existing_run_id"] is not None


def test_check_recent_failed_allows_rerun(db):
    """최근 fail 은 재실행 허용."""
    from api.services.runner_service import check_can_run

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
               VALUES ('llm_daily_delta', 'daily-delta', 'failed', %s, %s)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )

    result = check_can_run(db, mode="daily-delta")
    assert result["can_run"] is True


def test_check_running_blocks_rerun(db):
    """현재 running 인 모드 재실행 거부."""
    from api.services.runner_service import check_can_run

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at)
               VALUES ('llm_weekend', 'weekend', 'running', %s)""",
            (datetime.now(timezone.utc),),
        )

    result = check_can_run(db, mode="weekend")
    assert result["can_run"] is False
    assert result["reason"] == "already_running"


def test_check_force_bypasses_duplicate(db):
    """force=True 면 중복 무시."""
    from api.services.runner_service import check_can_run

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
               VALUES ('llm_weekend', 'weekend', 'success', %s, %s)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )

    result = check_can_run(db, mode="weekend", force=True)
    assert result["can_run"] is True


def test_spawn_subprocess_returns_pid(mocker):
    """subprocess.Popen 호출되고 PID 반환."""
    from api.services.runner_service import spawn_runner

    fake_proc = mocker.Mock()
    fake_proc.pid = 12345
    mock_popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    result = spawn_runner(mode="weekend", dry_run=True, limit=5)
    assert result["pid"] == 12345
    args = mock_popen.call_args[0][0]
    assert "--mode=weekend" in args
    assert "--dry-run" in args
    assert "--limit=5" in args


def test_check_can_run_pipeline_with_mode_prefix(db):
    """indicators-daily vs indicators-weekly: 같은 pipeline_db_name 이지만 mode_prefix 로 구분."""
    from datetime import datetime, timezone
    from api.services.runner_service import check_can_run_pipeline

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
               VALUES ('indicators', 'daily-incremental', 'success', %s, %s)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )

    result = check_can_run_pipeline(db, pipeline_id="indicators-daily")
    assert result["can_run"] is False
    assert result["reason"] == "duplicate"

    result = check_can_run_pipeline(db, pipeline_id="indicators-weekly")
    assert result["can_run"] is True


def test_spawn_pipeline_universe(mocker):
    from api.services.runner_service import spawn_pipeline

    fake_proc = mocker.Mock()
    fake_proc.pid = 55555
    mock_popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    result = spawn_pipeline("universe", "default")
    assert result["pid"] == 55555
    args = mock_popen.call_args[0][0]
    assert "kr_pipeline.universe" in args


def test_spawn_pipeline_appends_user_params(mocker):
    """params={'years': 3} 가 --years=3 으로 cmd 에 append."""
    from api.services.runner_service import spawn_pipeline

    fake_proc = mocker.Mock()
    fake_proc.pid = 77777
    mock_popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    spawn_pipeline("ohlcv", "backfill", params={"years": 3})
    args = mock_popen.call_args[0][0]
    assert "--years=3" in args
    assert "--mode=backfill" in args


def test_spawn_pipeline_uses_param_default_when_not_provided(mocker):
    """params 안 주면 mode 의 default 사용."""
    from api.services.runner_service import spawn_pipeline

    fake_proc = mocker.Mock()
    fake_proc.pid = 88888
    mock_popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    spawn_pipeline("ohlcv", "backfill")  # params 없음
    args = mock_popen.call_args[0][0]
    assert "--years=2" in args  # ohlcv backfill default = 2


def test_spawn_pipeline_with_indicator_target(mocker):
    from api.services.runner_service import spawn_pipeline

    fake_proc = mocker.Mock()
    fake_proc.pid = 66666
    mock_popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    result = spawn_pipeline("indicators-weekly", "incremental")
    args = mock_popen.call_args[0][0]
    assert "kr_pipeline.indicators" in args
    assert "--target=weekly" in args
    assert "--mode=incremental" in args
