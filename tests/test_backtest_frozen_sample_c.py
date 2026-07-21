"""표본 C(독립 검증 구간 2017-H2~2020) 준비 상태 가드 — 이슈 #52.

표본 C 는 사전등록(2026-07-21-independent-window-backtest-prereg.md) 승인 후
scripts/draw_sample_c.py --draw 1회 실행으로 동결된다. 그 전까지:
- frozen_sample_c 는 pending_draw + 빈 목록이어야 하고,
- CLI 는 --sample=c 실행을 명확히 거부해야 하며,
- 동결 후에도 기간 플래그 미명시 실행(기본 2021 윈도 오발사)은 거부되어야 한다.
"""
from __future__ import annotations

import re

import pytest


def test_frozen_sample_c_state_consistent():
    """pending 이면 빈 목록, frozen 이면 100 유니크 정렬 — 두 상태 외엔 없다."""
    from kr_pipeline.backtest.frozen_sample_c import (
        FROZEN_C_STATUS, FROZEN_SAMPLE_C, FROZEN_SEED_C)
    assert FROZEN_SEED_C == 20260721
    assert FROZEN_C_STATUS in ("pending_draw", "frozen")
    if FROZEN_C_STATUS == "pending_draw":
        assert FROZEN_SAMPLE_C == []
    else:
        assert len(FROZEN_SAMPLE_C) == 100
        assert len(set(FROZEN_SAMPLE_C)) == 100
        assert FROZEN_SAMPLE_C == sorted(FROZEN_SAMPLE_C)
        assert all(re.fullmatch(r"\d{6}", t) for t in FROZEN_SAMPLE_C)


def test_frozen_sample_c_matches_draw_artifact():
    """동결 목록 = --draw 산출물 JSON (표본 B 동형 — 손 전사 드리프트 차단).

    pending 상태에서는 산출물이 아직 없을 수 있으므로 frozen 일 때만 검사."""
    import json
    import os

    from kr_pipeline.backtest.frozen_sample_c import FROZEN_C_STATUS, FROZEN_SAMPLE_C
    if FROZEN_C_STATUS != "frozen":
        pytest.skip("동결 전 — 산출물 대조는 frozen 전용")
    path = "data/backtest/sample_c_draw_20260721.json"
    if not os.path.exists(path):
        pytest.skip(f"산출물 없음: {path}")
    d = json.load(open(path))
    assert FROZEN_SAMPLE_C == d["sample_c"]


def test_sample_c_pending_rejected():
    """미동결 표본 C 는 SystemExit — 조용히 빈 표본으로 진행되면 안 됨."""
    import kr_pipeline.backtest.frozen_sample_c as fc
    from kr_pipeline.backtest.profitability_cli import _sample
    if fc.FROZEN_C_STATUS != "pending_draw":
        pytest.skip("표본 C 가 이미 동결됨 — pending 가드는 동결 전 전용")
    with pytest.raises(SystemExit):
        _sample(None, "c")


def test_sample_c_frozen_returns_list(monkeypatch):
    """동결(비어있지 않음) 시 a/b 와 동일하게 목록 반환."""
    import kr_pipeline.backtest.frozen_sample_c as fc
    from kr_pipeline.backtest.profitability_cli import _sample
    frozen = [f"{i:06d}" for i in range(100)]
    monkeypatch.setattr(fc, "FROZEN_SAMPLE_C", frozen)
    monkeypatch.setattr(fc, "FROZEN_C_STATUS", "frozen")
    assert _sample(None, "c") == frozen


def test_backfill_sample_c_requires_explicit_window(monkeypatch):
    """--sample=c backfill 은 --start/--end 명시 없이는 DB 연결 전에 거부.

    기본값(2021 윈도)으로 독립 구간이 아닌 기간을 분류·적재하는 오발사 방지.
    """
    import kr_pipeline.backtest.profitability_cli as cli
    monkeypatch.setattr(
        cli, "connect",
        lambda *a, **k: pytest.fail("guard did not short-circuit before connect"))
    monkeypatch.setattr(cli.sys, "argv", ["prog", "backfill", "--sample=c"])
    with pytest.raises(SystemExit):
        cli.main()
    # 한쪽만 명시해도 거부
    monkeypatch.setattr(cli.sys, "argv",
                        ["prog", "backfill", "--sample=c", "--start=2017-07-01"])
    with pytest.raises(SystemExit):
        cli.main()


def test_backfill_sample_c_with_window_passes_guard(monkeypatch):
    """기간을 양쪽 명시하면 가드를 통과해 connect 까지 도달한다(동결 여부는 별도 가드)."""
    import kr_pipeline.backtest.profitability_cli as cli

    class _Reached(Exception):
        pass

    def _connect(*a, **k):
        raise _Reached

    monkeypatch.setattr(cli, "connect", _connect)
    monkeypatch.setattr(
        cli.sys, "argv",
        ["prog", "backfill", "--sample=c", "--start=2017-07-01", "--end=2020-12-31"])
    with pytest.raises(_Reached):
        cli.main()


def test_analyze_sample_c_requires_explicit_windows(monkeypatch):
    """analyze --sample=c 는 watch/px 윈도 4개 전부 명시해야 한다(대칭 가드)."""
    import kr_pipeline.backtest.profitability_cli as cli
    monkeypatch.setattr(
        cli, "connect",
        lambda *a, **k: pytest.fail("guard did not short-circuit before connect"))
    monkeypatch.setattr(cli.sys, "argv", ["prog", "analyze", "--sample=c"])
    with pytest.raises(SystemExit):
        cli.main()
    monkeypatch.setattr(cli.sys, "argv", [
        "prog", "analyze", "--sample=c",
        "--watch-start=2017-07-01", "--watch-end=2020-12-31",
        "--px-start=2017-01-01"])   # px-end 누락
    with pytest.raises(SystemExit):
        cli.main()


def test_analyze_sample_c_with_windows_passes_guard(monkeypatch):
    import kr_pipeline.backtest.profitability_cli as cli

    class _Reached(Exception):
        pass

    monkeypatch.setattr(cli, "connect",
                        lambda *a, **k: (_ for _ in ()).throw(_Reached()))
    monkeypatch.setattr(cli.sys, "argv", [
        "prog", "analyze", "--sample=c",
        "--watch-start=2017-07-01", "--watch-end=2020-12-31",
        "--px-start=2017-01-01", "--px-end=2021-06-30"])
    with pytest.raises(_Reached):
        cli.main()


def test_analyze_sample_a_default_reaches_connect(monkeypatch):
    """기존 기본 실행(analyze, 표본 A)은 어떤 신규 가드에도 걸리지 않는다(회귀 방지)."""
    import kr_pipeline.backtest.profitability_cli as cli

    class _Reached(Exception):
        pass

    monkeypatch.setattr(cli, "connect",
                        lambda *a, **k: (_ for _ in ()).throw(_Reached()))
    monkeypatch.setattr(cli.sys, "argv", ["prog", "analyze"])
    with pytest.raises(_Reached):
        cli.main()
