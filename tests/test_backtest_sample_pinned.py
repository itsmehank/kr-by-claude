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
    """미지 kind 는 거부 — 'c' 는 이제 알려진(보류) kind 라 별도 테스트에서 다룬다
    (tests/test_backtest_frozen_sample_c.py)."""
    import pytest
    from kr_pipeline.backtest.profitability_cli import _sample
    with pytest.raises(SystemExit):
        _sample(db, "z")


def test_backfill_guard_rejects_oversized_sample(db, monkeypatch):
    """라이브 재추첨 등으로 표본이 100 을 넘으면 run_backtest_backfill 호출 전에 거부.

    빈 테스트 DB에서는 run_backtest_backfill 자체가 가짜 101종목에 대해서도
    예외 없이 정상 반환하므로(get_qualifying_tickers가 [] 반환 → 단락), 가드가
    실수로 호출 뒤로 옮겨져도 SystemExit 여부만 보는 테스트는 여전히 통과한다.
    run_backtest_backfill을 호출되면 실패하는 스텁으로 바꿔 호출-전 순서를 증명한다.
    """
    import pytest
    import kr_pipeline.backtest.profitability_cli as cli
    monkeypatch.setattr(cli, "_sample", lambda conn, kind="a": [f"{i:06d}" for i in range(101)])
    monkeypatch.setattr(cli, "run_backtest_backfill",
                        lambda *a, **k: pytest.fail("guard did not short-circuit before backfill call"))
    with pytest.raises(SystemExit):
        cli.cmd_backfill(db, dry_run=True, kind="a", start=cli.START, end=cli.END)


def test_analyze_rejects_sample_b(monkeypatch):
    """analyze --sample=b 는 DB 연결 전에 SystemExit — 표본 A로 조용히 대체되면 안 됨.

    main() 이 connect() 로 실 DB에 붙기 전에 kind 검증을 하므로 DB 없이 통과해야 한다.
    """
    import pytest
    import kr_pipeline.backtest.profitability_cli as cli
    monkeypatch.setattr(cli.sys, "argv", ["prog", "analyze", "--sample=b"])
    with pytest.raises(SystemExit):
        cli.main()
