"""#242 — #110 확장 백필 제어(backfill_control)·셀 스냅샷·진행·트립와이어 (kr_test)."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from kr_pipeline.backtest import bt110
from kr_pipeline.llm_runner.store import insert_backfill_classification

SAT = date(2021, 3, 6)      # 토요일
FRI = date(2021, 3, 5)
RANGES = [["2021-03-01", "2021-03-06"]]   # 평일 start → 첫 토요일 03-06 로 스냅, 토요일 1개


def _seed(db, ticker: str, *, market="KOSPI", group="주권", delisted=None, pass_=True, halted=False):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market,security_group,delisted_at) VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT (ticker) DO UPDATE SET security_group=EXCLUDED.security_group, delisted_at=EXCLUDED.delisted_at",
                    (ticker, ticker, market, group, delisted))
        cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value,adj_low) "
                    "VALUES (%s,%s,1,1,1,1,1,1,1,%s) ON CONFLICT (ticker,date) DO UPDATE SET adj_low=EXCLUDED.adj_low",
                    (ticker, FRI, None if halted else 1))
        cur.execute("INSERT INTO daily_indicators (ticker,date,adj_close,minervini_pass,rs_line_not_declining_7m) "
                    "VALUES (%s,%s,1,%s,TRUE) ON CONFLICT (ticker,date) DO UPDATE SET minervini_pass=EXCLUDED.minervini_pass",
                    (ticker, FRI, pass_))


def _bt_row(db, ticker: str, sat: date, model="claude-sonnet-5-5"):
    insert_backfill_classification(
        db, symbol=ticker, classified_at=datetime(2026, 11, 2, tzinfo=timezone.utc), market="KOSPI",
        result={"classification": "watch", "pattern": "flat_base", "pivot_price": 1.0, "pivot_basis": "range_high",
                "base_high": 1.0, "base_low": 0.9, "base_depth_pct": 8.0, "base_start_date": "2021-02-01",
                "risk_flags": [], "confidence": 0.7, "reasoning": "t", "watch_reason": "base_forming"},
        llm_meta={"duration_s": 1.0, "model": model}, analyzed_for_date=sat, source="backtest",
        table="backtest_classification")


@pytest.fixture
def seeded(db):
    _seed(db, "T1")                                   # 자격
    _seed(db, "T2", group="투자회사")                  # 증권구분 비자격
    _seed(db, "T3", delisted=date(2023, 1, 1))        # 현재 상폐
    _seed(db, "T4", pass_=False)                      # 미통과
    _seed(db, "T5", halted=True)                      # 거래정지
    _seed(db, "T6")                                   # 자격이지만 이미 저장됨
    _bt_row(db, "T6", SAT)
    return db


def test_enumerate_cells_applies_all_filters(seeded):
    cells = bt110.enumerate_cells(seeded, RANGES)
    assert cells == [["T1", "2021-03-06", "KOSPI"]]


def test_set_switch_on_snapshots_cells_and_baseline_once(seeded):
    c = bt110.set_switch(seeded, True, slice_=RANGES)
    assert c["enabled"] is True and c["cells"] == [["T1", "2021-03-06", "KOSPI"]]
    assert c["baseline"]["slice_rows"] == 1 and c["baseline"]["total_rows"] >= 1
    # off → on 반복해도 스냅샷·기준선 유지(멱등 재개)
    _seed(seeded, "T7")
    bt110.set_switch(seeded, False)
    c2 = bt110.set_switch(seeded, True)
    assert c2["cells"] == [["T1", "2021-03-06", "KOSPI"]] and c2["baseline"] == c["baseline"]
    assert bt110.get_control(seeded)["enabled"] is True


def test_set_switch_off_without_row_creates_disabled_row(db):
    c = bt110.set_switch(db, False)
    assert c["enabled"] is False and c["cells"] is None


def test_candidates_by_date_groups_snapshot(seeded):
    c = bt110.set_switch(seeded, True, slice_=RANGES)
    cbd = bt110.candidates_by_date(c)
    assert cbd == {SAT: [{"symbol": "T1", "market": "KOSPI"}]}


def test_progress_counts_done_and_models(seeded):
    c = bt110.set_switch(seeded, True, slice_=RANGES)
    p0 = bt110.progress(seeded, c)
    assert p0["target"] == 1 and p0["done"] == 0 and p0["remaining"] == 1
    _bt_row(seeded, "T1", SAT, model="claude-sonnet-5-5")
    p1 = bt110.progress(seeded, bt110.get_control(seeded))
    assert p1["done"] == 1 and p1["remaining"] == 0 and p1["complete"] is True
    assert p1["models_in_slice"] == {"claude-sonnet-5-5": 1}   # baseline 행(T6, 모델 동일)은 제외 — 신규만


def test_tripwire_flags_rows_outside_snapshot(seeded):
    c = bt110.set_switch(seeded, True, slice_=RANGES)
    assert bt110.tripwire(seeded, c) == []
    _bt_row(seeded, "T1", SAT)                      # 스냅샷 내 — 정상
    assert bt110.tripwire(seeded, bt110.get_control(seeded)) == []
    _seed(seeded, "T7")
    _bt_row(seeded, "T7", SAT)                      # 스냅샷 밖·슬라이스 내 신규 행(외부 적재 의심)
    v = bt110.tripwire(seeded, bt110.get_control(seeded))
    assert any("outside_snapshot" in x for x in v)


def test_pin_commit_first_pass_then_compare(seeded):
    c = bt110.set_switch(seeded, True, slice_=RANGES)
    assert c["pinned_commit"] is None
    assert bt110.check_or_pin_commit(seeded, "abc123") == "pinned"
    assert bt110.check_or_pin_commit(seeded, "abc123") == "ok"
    assert bt110.check_or_pin_commit(seeded, "def456") == "mismatch:abc123"


def test_pin_without_control_row_reports_no_row(db):
    assert bt110.check_or_pin_commit(db, "abc") == "no_row"


def test_set_switch_slice_change_resnapshots(seeded):
    c = bt110.set_switch(seeded, True, slice_=RANGES)
    assert c["cells"] == [["T1", "2021-03-06", "KOSPI"]]
    _bt_row(seeded, "T1", SAT)                                      # 1차 조각 완료
    c2 = bt110.set_switch(seeded, True, slice_=[["2021-03-07", "2021-03-13"]])   # 2차 조각
    assert c2["slice"] == [["2021-03-07", "2021-03-13"]]
    assert c2["cells"] == [["T1", "2021-03-13", "KOSPI"], ["T6", "2021-03-13", "KOSPI"]]   # 재스냅샷
    assert c2["baseline"]["slice_rows"] == 0 and bt110.tripwire(seeded, c2) == []  # 구 쌍으로 오탐 없음


def test_tripwire_rows_over_and_symbols_over(seeded):
    c = bt110.set_switch(seeded, True, slice_=RANGES)       # 기준선: 행 1(T6)·종목 1, 스냅샷: T1 1셀
    _bt_row(seeded, "T1", SAT)                               # 스냅샷 적재 — 정상
    assert bt110.tripwire(seeded, bt110.get_control(seeded)) == []
    _seed(seeded, "T8")
    _bt_row(seeded, "T8", date(2020, 1, 4))                  # 슬라이스 밖 외부 적재: 총량 +2 > 스냅샷 1, 종목 3 > 1+1
    v = bt110.tripwire(seeded, bt110.get_control(seeded))
    assert any(x.startswith("rows_over_snapshot") for x in v) and any(x.startswith("symbols_over") for x in v)
    assert not any(x.startswith("outside_snapshot") for x in v)   # 슬라이스 밖이라 outside 는 아님


def test_status_omits_slice_pairs(seeded):
    bt110.set_switch(seeded, True, slice_=RANGES)
    st = bt110.status(seeded)
    assert "slice_pairs" not in st["baseline"] and st["baseline"]["slice_rows"] == 1


def test_cli_status_kv_and_pin(seeded, monkeypatch, capsys):
    from kr_pipeline.backtest import bt110_cli
    import contextlib
    bt110.set_switch(seeded, True, slice_=RANGES)
    monkeypatch.setattr(bt110_cli, "connect", lambda: contextlib.nullcontext(seeded))
    assert bt110_cli.main(["status", "--kv"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("enabled=1 complete=0 target=1 done=0 tripwire=0 models=0 pinned=-")
    assert bt110_cli.main(["pin", "--head", "abc"]) == 0
    assert '"pin": "pinned"' in capsys.readouterr().out
    bt110_cli.main(["status"])
    assert '"pinned_commit": "abc"' in capsys.readouterr().out
