import re


def test_frozen_sample_is_100_unique_sorted():
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    assert len(FROZEN_SAMPLE) == 100
    assert len(set(FROZEN_SAMPLE)) == 100
    assert FROZEN_SAMPLE == sorted(FROZEN_SAMPLE)
    assert all(re.fullmatch(r"\d{6}", t) for t in FROZEN_SAMPLE)


def test_frozen_sample_matches_preregistration_doc():
    """동결 목록이 사전등록 문서의 100종목과 정확히 일치(권위 보존)."""
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    txt = open("docs/superpowers/backtest-profitability-sample.md").read()
    doc = sorted(set(re.findall(r"\b\d{6}\b", txt)))
    assert set(FROZEN_SAMPLE) == set(doc)
