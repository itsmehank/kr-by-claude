import re


def test_frozen_sample_b_is_100_unique_sorted():
    from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
    assert len(FROZEN_SAMPLE_B) == 100
    assert len(set(FROZEN_SAMPLE_B)) == 100
    assert FROZEN_SAMPLE_B == sorted(FROZEN_SAMPLE_B)
    assert all(re.fullmatch(r"\d{6}", t) for t in FROZEN_SAMPLE_B)


def test_frozen_sample_b_disjoint_from_sample_a_and_loaded():
    """재백필 금지 핵심 가드 — B 는 표본 A·추첨 당시 기적재 114 와 전혀 안 겹친다."""
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_AT_DRAW, FROZEN_SAMPLE_B
    assert not set(FROZEN_SAMPLE_B) & set(FROZEN_SAMPLE)
    assert not set(FROZEN_SAMPLE_B) & set(EXCLUDED_AT_DRAW)
    assert set(FROZEN_SAMPLE) <= set(EXCLUDED_AT_DRAW)
    assert len(EXCLUDED_AT_DRAW) == 114


def test_frozen_sample_b_matches_preregistration_doc():
    """동결 목록이 사전등록 문서의 100종목과 정확히 일치(권위 보존)."""
    from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
    txt = open("docs/superpowers/backtest-sample-b.md").read()
    doc = sorted(set(re.findall(r"\b\d{6}\b", txt)))
    assert set(FROZEN_SAMPLE_B) == set(doc)


def test_frozen_sample_b_matches_draw_artifact():
    """동결 목록 = 추첨 산출물(JSON) — 전사 오류 방지."""
    import json
    from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_AT_DRAW, FROZEN_SAMPLE_B
    d = json.load(open("data/backtest/sample_b_draw_20260713.json"))
    assert FROZEN_SAMPLE_B == d["sample_b"]
    assert EXCLUDED_AT_DRAW == d["excluded_at_draw"]
