"""(#242) profitability_cli backfill --population=bt110 — 스냅샷 모집단 모드."""
from __future__ import annotations

import json
from datetime import date

import pytest

from kr_pipeline.backtest import profitability_cli as cli


def test_bt110_requires_snapshot(db, monkeypatch):
    monkeypatch.setattr(cli.bt110 if hasattr(cli, "bt110") else __import__("kr_pipeline.backtest.bt110", fromlist=["x"]),
                        "get_control", lambda conn: None)
    with pytest.raises(SystemExit, match="스냅샷 없음"):
        cli.cmd_backfill(db, True, "bt110", date(2021, 1, 1), date(2021, 1, 2))


def test_bt110_runs_each_slice_with_snapshot_candidates(db, monkeypatch, capsys):
    import kr_pipeline.backtest.bt110 as bt110
    ctl = {"slice": [["2021-01-02", "2021-01-09"], ["2024-01-06", "2024-01-13"]],
           "cells": [["T1", "2021-01-02", "KOSPI"], ["T2", "2024-01-13", "KOSDAQ"]]}
    monkeypatch.setattr(bt110, "get_control", lambda conn: ctl)
    calls = []

    def fake_run(conn, *, start, end, tickers, dry_run, candidates_by_date):
        calls.append((start, end, tickers, dry_run, sorted(candidates_by_date)))
        return {"weeks": 1, "processed": 2, "skipped_existing": 0, "failures": 1, "circuit_broken": False,
                "failed": [["X", str(start), "e"]]}
    monkeypatch.setattr(cli, "run_backtest_backfill", fake_run)
    rc = cli.cmd_backfill(db, True, "bt110", date(2000, 1, 1), date(2000, 1, 2))
    assert rc == 0
    assert [c[:2] for c in calls] == [(date(2021, 1, 2), date(2021, 1, 9)), (date(2024, 1, 6), date(2024, 1, 13))]
    assert all(c[2] == [] and c[3] is True for c in calls)           # MAX_SAMPLE 가드 비경유, dry_run 전달
    assert calls[0][4] == [date(2021, 1, 2), date(2024, 1, 13)]       # 스냅샷 전체 사전(창 필터는 run 쪽)
    last = capsys.readouterr().out.strip().splitlines()[-1]
    total = json.loads(last)
    assert total == {"processed": 4, "failures": 2, "skipped_existing": 0, "weeks": 2,
                     "circuit_broken": False, "ranges": 2}


def test_bt110_stops_remaining_ranges_on_circuit(db, monkeypatch, capsys):
    import kr_pipeline.backtest.bt110 as bt110
    monkeypatch.setattr(bt110, "get_control", lambda conn: {
        "slice": [["2021-01-02", "2021-01-09"], ["2024-01-06", "2024-01-13"]], "cells": [["T1", "2021-01-02", "KOSPI"]]})
    n = []
    monkeypatch.setattr(cli, "run_backtest_backfill", lambda conn, **kw: n.append(1) or {
        "weeks": 1, "processed": 0, "skipped_existing": 0, "failures": 3, "circuit_broken": True, "failed": []})
    cli.cmd_backfill(db, False, "bt110", date(2000, 1, 1), date(2000, 1, 2))
    assert len(n) == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["circuit_broken"] is True


def test_population_flag_selects_bt110(monkeypatch):
    monkeypatch.setattr(cli.sys, "argv", ["x", "backfill", "--population=bt110", "--dry-run"])
    seen = {}
    monkeypatch.setattr(cli, "connect", lambda: __import__("contextlib").nullcontext(object()))
    monkeypatch.setattr(cli, "cmd_backfill", lambda conn, dry, kind, s, e: seen.update(kind=kind, dry=dry) or 0)
    assert cli.main() == 0 and seen == {"kind": "bt110", "dry": True}
