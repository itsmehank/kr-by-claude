"""llm_runner __main__ — run_tracking 호출 검증."""
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch


def _make_mock_conn():
    """run_tracking 이 내부적으로 쓰는 conn 메서드를 갖춘 mock."""
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.fetchone.return_value = (1,)
    return conn


def _make_mock_connect(mock_conn):
    @contextmanager
    def mock_connect(url):
        yield mock_conn
    return mock_connect


def _make_mock_run_tracking(captured: dict | None = None):
    """run_tracking contextmanager mock — state dict 를 yield 하고 종료 후 captured 에 저장."""
    @contextmanager
    def mock_tracking(conn, *, pipeline, mode, params):
        state = {"run_id": 1, "warnings": [], "rows_affected": None}
        yield state
        if captured is not None:
            captured.update(state)

    return mock_tracking


def test_main_calls_run_tracking_for_weekend_mode(mocker):
    """--mode=weekend 실행 시 run_tracking 이 pipeline='llm_weekend' 로 호출되어야 함."""
    mock_conn = _make_mock_conn()

    mocker.patch(
        "kr_pipeline.common.config.Config.load",
        return_value=MagicMock(database_url="postgresql://test"),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.__main__.connect",
        side_effect=_make_mock_connect(mock_conn),
    )
    tracking_spy = mocker.patch(
        "kr_pipeline.llm_runner.__main__.run_tracking",
        side_effect=_make_mock_run_tracking(),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.modes.run_weekend",
        return_value={"processed": 5, "failures": 0},
    )

    from kr_pipeline.llm_runner.__main__ import main
    with patch.object(sys, "argv", ["llm_runner", "--mode=weekend", "--dry-run", "--limit=5"]):
        rc = main()

    assert rc == 0
    tracking_spy.assert_called_once()
    kw = tracking_spy.call_args.kwargs
    assert kw["pipeline"] == "llm_weekend"
    assert kw["mode"] == "weekend"
    assert kw["params"]["mode"] == "weekend"
    assert kw["params"]["dry_run"] is True


def test_main_calls_run_tracking_for_full_daily_mode(mocker):
    """--mode=full-daily 실행 시 run_tracking 이 pipeline='llm_daily_delta' 로 호출되어야 함."""
    mock_conn = _make_mock_conn()

    mocker.patch(
        "kr_pipeline.common.config.Config.load",
        return_value=MagicMock(database_url="postgresql://test"),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.__main__.connect",
        side_effect=_make_mock_connect(mock_conn),
    )
    tracking_spy = mocker.patch(
        "kr_pipeline.llm_runner.__main__.run_tracking",
        side_effect=_make_mock_run_tracking(),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.modes.run_full_daily",
        return_value={"processed": 10},
    )

    from kr_pipeline.llm_runner.__main__ import main
    with patch.object(sys, "argv", ["llm_runner", "--mode=full-daily", "--dry-run"]):
        rc = main()

    assert rc == 0
    tracking_spy.assert_called_once()
    kw = tracking_spy.call_args.kwargs
    assert kw["pipeline"] == "llm_daily_delta"
    assert kw["mode"] == "full-daily"


def test_main_sets_rows_affected_from_result(mocker):
    """result dict 의 processed 값이 state['rows_affected'] 에 반영되어야 함."""
    mock_conn = _make_mock_conn()
    captured: dict = {}

    mocker.patch(
        "kr_pipeline.common.config.Config.load",
        return_value=MagicMock(database_url="postgresql://test"),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.__main__.connect",
        side_effect=_make_mock_connect(mock_conn),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.__main__.run_tracking",
        side_effect=_make_mock_run_tracking(captured),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.modes.run_weekend",
        return_value={"processed": 42, "failures": 0},
    )

    from kr_pipeline.llm_runner.__main__ import main
    with patch.object(sys, "argv", ["llm_runner", "--mode=weekend", "--dry-run"]):
        rc = main()

    assert rc == 0
    assert captured.get("rows_affected") == 42


def test_pipeline_db_name_mapping_covers_all_modes():
    """PIPELINE_DB_NAME_BY_MODE 가 모든 지원 mode 를 커버해야 함."""
    from kr_pipeline.llm_runner.__main__ import PIPELINE_DB_NAME_BY_MODE

    expected_modes = {"weekend", "daily-delta", "evaluate", "entry", "performance", "full-daily"}
    assert set(PIPELINE_DB_NAME_BY_MODE.keys()) == expected_modes

    # pipeline_specs.py 에 등록된 LLM pipeline 과 일치 확인
    assert PIPELINE_DB_NAME_BY_MODE["weekend"] == "llm_weekend"
    assert PIPELINE_DB_NAME_BY_MODE["full-daily"] == "llm_daily_delta"
    assert PIPELINE_DB_NAME_BY_MODE["performance"] == "llm_performance"
    # daily-delta 와 full-daily 는 같은 pipeline_db_name 공유
    assert PIPELINE_DB_NAME_BY_MODE["daily-delta"] == "llm_daily_delta"
