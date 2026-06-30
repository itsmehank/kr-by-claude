"""_sample() 이 DB 상태와 무관하게 동결 100종목을 반환함을 검증."""
from __future__ import annotations


def test_sample_returns_frozen_regardless_of_db(db):
    from kr_pipeline.backtest.profitability_cli import _sample
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    got = _sample(db)
    assert sorted(got) == sorted(FROZEN_SAMPLE)
    assert len(got) == 100
