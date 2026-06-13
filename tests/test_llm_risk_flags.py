from kr_pipeline.llm_runner.risk_flags import RISK_FLAGS_TAXONOMY
from kr_pipeline.llm_runner.store import _clean_risk_flags


def test_topping_distribution_in_taxonomy():
    assert "topping_distribution" in RISK_FLAGS_TAXONOMY


def test_clean_keeps_topping_distribution():
    # taxonomy 등록 flag 는 보존돼야 함 (drop 되면 §6.2 감사 데이터 유실)
    assert _clean_risk_flags(["topping_distribution"]) == ["topping_distribution"]
