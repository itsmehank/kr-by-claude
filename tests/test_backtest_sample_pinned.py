"""_sample() 이 DB 상태와 무관하게 동결 100종목을 반환함을 검증."""
from __future__ import annotations


def test_sample_returns_frozen_regardless_of_db(db):
    from kr_pipeline.backtest.profitability_cli import _sample
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    got = _sample(db)
    assert sorted(got) == sorted(FROZEN_SAMPLE)
    assert len(got) == 100


def test_sample_b_returns_frozen_b_regardless_of_db(db):
    from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
    from kr_pipeline.backtest.profitability_cli import _sample
    got = _sample(db, "b")
    assert sorted(got) == sorted(FROZEN_SAMPLE_B)
    assert len(got) == 100


def test_sample_unknown_kind_rejected(db):
    import pytest
    from kr_pipeline.backtest.profitability_cli import _sample
    with pytest.raises(SystemExit):
        _sample(db, "c")


def test_backfill_guard_rejects_oversized_sample(db, monkeypatch):
    """라이브 재추첨 등으로 표본이 100 을 넘으면 백필이 시작 전에 거부."""
    import pytest
    import kr_pipeline.backtest.profitability_cli as cli
    monkeypatch.setattr(cli, "_sample", lambda conn, kind="a": [f"{i:06d}" for i in range(101)])
    with pytest.raises(SystemExit):
        cli.cmd_backfill(db, dry_run=True, kind="a", start=cli.START, end=cli.END)
