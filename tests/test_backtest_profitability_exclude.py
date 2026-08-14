"""entry_rate_by_phase 의 exclude 파라미터 — #50 제외 셀이 분류점 집계에서 빠지는지."""
from datetime import date


def _seed_rows(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('BX1','BX1','KOSPI') ON CONFLICT DO NOTHING")
        for d, cls in [("2022-04-09", "entry"), ("2022-04-16", "watch")]:
            cur.execute(
                "INSERT INTO backtest_classification (symbol, analyzed_for_date, classified_at, market, classification, source) "
                "VALUES ('BX1', %s, now(), 'KOSPI', %s, 'backtest')", (d, cls))
    db.commit()


def test_exclude_removes_cell_from_counts(db, monkeypatch):
    import kr_pipeline.backtest.profitability_run as pr
    # 국면 라벨은 이 테스트의 관심사가 아님 — 전부 고정 국면으로 치환
    monkeypatch.setattr(pr.ph, "load_phase_map", lambda conn, code: [])
    monkeypatch.setattr(pr.ph, "phase_at", lambda pmap, d: "confirmed_uptrend")
    _seed_rows(db)
    base = pr.entry_rate_by_phase(db, ["BX1"])
    assert base["confirmed_uptrend"]["total"] == 2
    assert base["confirmed_uptrend"]["entry"] == 1
    excl = pr.entry_rate_by_phase(db, ["BX1"], exclude=frozenset({("BX1", date(2022, 4, 9))}))
    assert excl["confirmed_uptrend"]["total"] == 1
    assert excl["confirmed_uptrend"]["entry"] == 0


def test_excluded_cells_constant():
    from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_CELLS, FROZEN_SAMPLE_B
    assert EXCLUDED_CELLS == [("317870", "2022-04-09")]
    assert EXCLUDED_CELLS[0][0] in FROZEN_SAMPLE_B


def test_entry_rate_watch_window_excludes_out_of_range(db):
    """(#52) watch 윈도 지정 시 범위 밖 행(교차 표본 오염) 제외 — 미지정은 전 기간."""
    import kr_pipeline.backtest.profitability_run as pr
    from datetime import date

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('BX2','t','KOSPI') ON CONFLICT DO NOTHING")
        for afd in (date(2019, 5, 4), date(2022, 4, 9)):
            cur.execute(
                f"INSERT INTO {pr.BT_TABLE} (symbol, classified_at, market, classification, analyzed_for_date, source) "
                "VALUES ('BX2', now(), 'KOSPI', 'entry', %s, 'backtest') ON CONFLICT DO NOTHING",
                (afd,))
    db.commit()
    base = pr.entry_rate_by_phase(db, ["BX2"])
    windowed = pr.entry_rate_by_phase(db, ["BX2"], watch_start=date(2017, 7, 1),
                                      watch_end=date(2020, 12, 31))
    assert sum(v["total"] for v in base.values()) >= sum(
        v["total"] for v in windowed.values())
    # 윈도 밖(2022) 행이 windowed 에는 없어야 함 — 총량이 1 이하로 줄어든다
    assert sum(v["total"] for v in windowed.values()) <= 1
