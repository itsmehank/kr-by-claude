"""신선도 가드 배선 회귀 방지 — __main__ 이 guard 심볼을 import 했는지 확인."""


def test_main_imports_freshness_symbols():
    # __main__ 이 신선도 가드 심볼을 import 했는지(배선 회귀 방지).
    import kr_pipeline.llm_runner.__main__ as m
    assert hasattr(m, "assert_data_fresh")
    assert hasattr(m, "ZoneInfo")
