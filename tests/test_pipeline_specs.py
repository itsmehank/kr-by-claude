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
        assert "schedule_label" in spec
        assert "pipeline_db_name" in spec
        assert "long_description" in spec
        assert "inputs" in spec
        assert "outputs" in spec
        assert "depends_on" in spec
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


def test_each_spec_has_schedule_label():
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "schedule_label" in spec, f"{spec['id']} 누락"
        assert isinstance(spec["schedule_label"], str)
        assert len(spec["schedule_label"]) > 0


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


def test_each_spec_has_long_description():
    """모든 spec 은 long_description (>20자) 을 가져야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "long_description" in spec, f"{spec['id']} 누락"
        assert isinstance(spec["long_description"], str)
        assert len(spec["long_description"]) > 20, f"{spec['id']} 너무 짧음"


def test_each_spec_has_io_tables():
    """모든 spec 은 inputs / outputs (list[str]) 를 가져야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "inputs" in spec and isinstance(spec["inputs"], list), f"{spec['id']} inputs 누락"
        assert "outputs" in spec and isinstance(spec["outputs"], list), f"{spec['id']} outputs 누락"
        for t in spec["inputs"] + spec["outputs"]:
            assert isinstance(t, str)
        assert len(spec["outputs"]) > 0, f"{spec['id']} outputs 비어있음"


def test_each_spec_has_depends_on():
    """모든 spec 은 depends_on (list[str]) 을 가져야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "depends_on" in spec and isinstance(spec["depends_on"], list), f"{spec['id']} depends_on 누락"
        for dep in spec["depends_on"]:
            assert isinstance(dep, str)


def test_depends_on_referential_integrity():
    """depends_on 의 모든 id 가 PIPELINE_SPECS 에 실제 존재해야 함."""
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    all_ids = {s["id"] for s in PIPELINE_SPECS}
    for spec in PIPELINE_SPECS:
        for dep in spec["depends_on"]:
            assert dep in all_ids, f"{spec['id']} depends_on '{dep}' 존재하지 않음"


def test_modes_have_params_when_applicable():
    """params 가 있는 모드는 ohlcv.backfill, corporate-actions.backfill 만."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    # ohlcv backfill: years param
    ohlcv_backfill = next(m for m in get_spec("ohlcv")["modes"] if m["id"] == "backfill")
    assert "params" in ohlcv_backfill
    assert len(ohlcv_backfill["params"]) == 1
    p = ohlcv_backfill["params"][0]
    assert p["name"] == "years"
    assert p["type"] == "int"
    assert p["default"] == 2

    # corporate-actions backfill: years param default 5
    ca_backfill = next(m for m in get_spec("corporate-actions")["modes"] if m["id"] == "backfill")
    assert ca_backfill["params"][0]["default"] == 5


def test_backfill_removed_from_redundant_pipelines():
    """weekly, indicators-daily/weekly, market-context 의 backfill 모드는 full-refresh 와 중복이므로 제거됨."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    for pid in ["weekly", "indicators-daily", "indicators-weekly", "market-context"]:
        mode_ids = {m["id"] for m in get_spec(pid)["modes"]}
        assert "backfill" not in mode_ids, f"{pid} 에 backfill 아직 있음"


def test_renamed_labels():
    """주요 모드 label 변경 확인."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    ohlcv_fr = next(m for m in get_spec("ohlcv")["modes"] if m["id"] == "full-refresh")
    assert ohlcv_fr["label"] == "보유 기간 재정정"

    ohlcv_bf = next(m for m in get_spec("ohlcv")["modes"] if m["id"] == "backfill")
    assert ohlcv_bf["label"] == "과거 N년 적재"

    weekly_fr = next(m for m in get_spec("weekly")["modes"] if m["id"] == "full-refresh")
    assert weekly_fr["label"] == "보유 기간 재집계"

    ind_fr = next(m for m in get_spec("indicators-daily")["modes"] if m["id"] == "full-refresh")
    assert ind_fr["label"] == "전체 기간 재계산"


def test_known_dependency_mapping():
    """확정된 핵심 의존 관계 검증."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    assert get_spec("universe")["depends_on"] == []
    assert get_spec("ohlcv")["depends_on"] == []
    assert "ohlcv" in get_spec("weekly")["depends_on"]
    assert set(get_spec("indicators-daily")["depends_on"]) == {"ohlcv", "corporate-actions"}
    assert set(get_spec("indicators-weekly")["depends_on"]) == {"weekly", "corporate-actions"}
    assert set(get_spec("market-context")["depends_on"]) == {"indicators-daily", "ohlcv"}
    assert set(get_spec("llm-full-daily")["depends_on"]) == {"indicators-daily", "market-context", "ohlcv"}
    assert set(get_spec("llm-weekend")["depends_on"]) == {"indicators-daily", "indicators-weekly", "market-context"}
    assert set(get_spec("llm-performance")["depends_on"]) == {"ohlcv", "llm-full-daily"}
