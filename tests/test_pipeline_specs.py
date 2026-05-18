"""PIPELINE_SPECS 검증 — 모든 cron 작업 정의."""


def test_pipeline_specs_has_required_groups():
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    groups = {s["group"] for s in PIPELINE_SPECS}
    assert {"data", "indicators", "llm"}.issubset(groups)


def test_pipeline_specs_has_all_modules():
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    ids = {s["id"] for s in PIPELINE_SPECS}
    required = {
        "universe", "ohlcv", "weekly", "corporate-actions",
        "indicators-daily", "indicators-weekly", "market-context",
        "llm-full-daily", "llm-weekend", "llm-performance",
    }
    assert required.issubset(ids), f"missing: {required - ids}"


def test_each_spec_has_required_fields():
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "id" in spec
        assert "group" in spec
        assert "label" in spec
        assert "description" in spec
        assert "module" in spec
        assert "modes" in spec and len(spec["modes"]) > 0
        assert "default_cron" in spec
        assert "pipeline_db_name" in spec
        for mode in spec["modes"]:
            assert "id" in mode
            assert "label" in mode
            assert "args" in mode


def test_get_spec_by_id():
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    spec = get_spec("ohlcv")
    assert spec is not None
    assert spec["module"] == "kr_pipeline.ohlcv"
    assert any(m["id"] == "incremental" for m in spec["modes"])


def test_get_spec_returns_none_for_unknown():
    from kr_pipeline.llm_runner.pipeline_specs import get_spec
    assert get_spec("nonexistent") is None


def test_get_mode_returns_args():
    from kr_pipeline.llm_runner.pipeline_specs import get_mode_args

    args = get_mode_args("ohlcv", "incremental")
    assert "--mode=incremental" in args


def test_get_mode_args_unknown_returns_none():
    from kr_pipeline.llm_runner.pipeline_specs import get_mode_args
    assert get_mode_args("ohlcv", "nonexistent") is None


def test_modes_have_is_heavy_flag():
    """모든 mode 는 is_heavy 플래그를 가져야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        for mode in spec["modes"]:
            assert "is_heavy" in mode, f"{spec['id']}.{mode['id']} 누락"
            assert isinstance(mode["is_heavy"], bool)


def test_incremental_modes_not_heavy():
    """incremental / dry-run 모드는 heavy 아님."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    assert get_spec("ohlcv")["modes"][0]["is_heavy"] is False  # incremental
    assert get_spec("llm-full-daily")["modes"][0]["is_heavy"] is False  # dry-run default


def test_backfill_modes_are_heavy():
    """backfill / real LLM 모드는 heavy."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    ohlcv_backfill = next(m for m in get_spec("ohlcv")["modes"] if m["id"] == "backfill")
    assert ohlcv_backfill["is_heavy"] is True
    llm_real = next(m for m in get_spec("llm-full-daily")["modes"] if m["id"] == "real")
    assert llm_real["is_heavy"] is True


def test_each_spec_has_description():
    """모든 spec 는 description 을 가져야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "description" in spec, f"{spec['id']} 누락"
        assert isinstance(spec["description"], str)
        assert len(spec["description"]) > 10


def test_pipeline_db_name_matches_existing_runs():
    """pipeline_db_name 이 pipeline_runs 의 실제 pipeline 값과 매칭."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    assert get_spec("universe")["pipeline_db_name"] == "universe"
    assert get_spec("ohlcv")["pipeline_db_name"] == "ohlcv"
    assert get_spec("weekly")["pipeline_db_name"] == "weekly"
    assert get_spec("indicators-daily")["pipeline_db_name"] == "indicators"
    assert get_spec("indicators-weekly")["pipeline_db_name"] == "indicators"
    assert get_spec("market-context")["pipeline_db_name"] == "market_context"
    assert get_spec("corporate-actions")["pipeline_db_name"] == "corporate_actions"
    assert get_spec("llm-full-daily")["pipeline_db_name"] == "llm_daily_delta"
    assert get_spec("llm-weekend")["pipeline_db_name"] == "llm_weekend"
    assert get_spec("llm-performance")["pipeline_db_name"] == "llm_performance"
