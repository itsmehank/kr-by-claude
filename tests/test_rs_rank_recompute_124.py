"""#124 — 저장 수정종가로 전 종목 강도 점수를 즉석 계산해 RS 순위를 현재 빈티지로 다시 매기는 도구. 외부 접촉 0."""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from kr_pipeline.indicators import modes
from kr_pipeline.indicators import rs_rank_recompute as m
from kr_pipeline.indicators.modes import Target

# 격리 구간(다른 테스트와 겹치지 않는 과거 연도)
D0 = date(2009, 1, 5)   # 월요일
W0 = date(2009, 1, 9)   # 금요일


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _fridays(start: date, n: int) -> list[date]:
    return [start + timedelta(days=7 * i) for i in range(n)]


def _price(kind: str, i: int) -> float:
    if kind == "up":
        return 100.0 + i * 0.5
    if kind == "down":
        return 300.0 - i * 0.3
    if kind == "wave":
        return 200.0 + 20.0 * math.sin(i / 17.0)
    return 150.0 + (i % 7) * 0.1  # flat


def seed_daily(db, spec: dict[str, tuple[str, int]], *, delisted: set[str] = frozenset()) -> list[date]:
    """spec = {ticker: (price_kind, n_rows)} — stocks + daily_prices + index_daily(1001). 반환 = 전체 날짜(최대 n)."""
    n_max = max(n for _, n in spec.values())
    days = _weekdays(D0, n_max)
    with db.cursor() as cur:
        for t, (kind, n) in spec.items():
            cur.execute("INSERT INTO stocks (ticker, name, market, delisted_at) VALUES (%s,'T','KOSPI',%s) "
                        "ON CONFLICT (ticker) DO UPDATE SET delisted_at = EXCLUDED.delisted_at",
                        (t, days[-1] + timedelta(days=30) if t in delisted else None))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            for i, d in enumerate(days[n_max - n:]):   # 신규상장 모사: 뒤쪽 n 행만
                p = _price(kind, i)
                cur.execute(
                    """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                           adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1000.0,1000,1)""",
                    (t, d, p, p, p, p, p, p, p, p),
                )
        for i, d in enumerate(days):
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close)
                   VALUES ('1001', %s, 2000, 2000, 2000, %s) ON CONFLICT (index_code, date) DO NOTHING""",
                (d, 2000.0 + i),
            )
    db.commit()
    return days


def cleanup_daily(db, tickers, days):
    with db.cursor() as cur:
        for t in tickers:
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM index_daily WHERE index_code='1001' AND date BETWEEN %s AND %s", (days[0], days[-1]))
    db.commit()


def run_phase_ab_daily(db, tickers, days):
    modes._phase_b_cache.clear()
    for t in tickers:
        modes._process_ticker_daily(db, t, "KOSPI", days[0], days[-1], days[0])
    modes._run_phase_b_daily(db, days[0], days[-1])
    modes._phase_b_cache.clear()
    from kr_pipeline.indicators.store import update_daily_indicators_minervini_pass as _pc
    _pc(db, days[0], days[-1])   # Phase C 까지 저장(실제 저장 상태와 동형)
    db.commit()


def stored_rs(db, target: Target, tickers) -> list[tuple[str, date, int | None]]:
    tbl, col = ("daily_indicators", "date") if target == Target.DAILY else ("weekly_indicators", "week_end_date")
    with db.cursor() as cur:
        cur.execute(f"SELECT ticker, {col}, rs_rating FROM {tbl} WHERE ticker = ANY(%s) ORDER BY 1, 2", (list(tickers),))
        return cur.fetchall()


def assert_ranks_equal(got: pd.DataFrame, stored_rows):
    assert len(stored_rows) > 0
    for t, d, stored in stored_rows:
        v = got.at[d, t]
        assert (pd.isna(v) and stored is None) or (not pd.isna(v) and int(v) == stored), (t, d, stored, v)


DAILY_SPEC = {"RK124A": ("wave", 400), "RK124B": ("down", 400), "RK124C": ("wave", 150), "RK124D": ("flat", 400)}


def test_rank_table_equals_phase_b_daily(db):
    """저장 Phase B(캐시 경유) 와 즉석 계산(저장 adj_close 경유)이 모든 셀에서 같다 —
    신규상장(C, 150행 → SF NaN → NULL)·상폐됐지만 과거 행이 있는 종목(D) 포함."""
    tickers = list(DAILY_SPEC)
    days = seed_daily(db, DAILY_SPEC, delisted={"RK124D"})
    try:
        run_phase_ab_daily(db, tickers, days)
        stored = stored_rs(db, Target.DAILY, tickers)
        assert any(r[2] is not None for r in stored)
        assert all(r[2] is None for r in stored if r[0] == "RK124C")
        uni = [t for t in m.universe_tickers(db, Target.DAILY) if t in tickers]
        assert set(uni) == set(tickers), "상폐 종목도 지표 행이 있으면 유니버스에 포함"
        sf = m.strength_table(db, Target.DAILY, tickers=uni, end=days[-1])
        got = m.rank_table(sf, days)
        assert_ranks_equal(got, stored)
    finally:
        cleanup_daily(db, tickers, days)


def seed_weekly(db, spec: dict[str, tuple[str, int]]) -> list[date]:
    n_max = max(n for _, n in spec.values())
    weeks = _fridays(W0, n_max)
    with db.cursor() as cur:
        for t, (kind, n) in spec.items():
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
            for i, d in enumerate(weeks[n_max - n:]):
                p = _price(kind, i)
                cur.execute(
                    """INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close,
                           adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, trading_days)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1000.0,1000,1,5)""",
                    (t, d, p, p, p, p, p, p, p, p),
                )
        for i, d in enumerate(weeks):
            cur.execute(
                """INSERT INTO weekly_index (index_code, week_end_date, open, high, low, close, trading_days)
                   VALUES ('1001', %s, 2000, 2000, 2000, %s, 5) ON CONFLICT (index_code, week_end_date) DO NOTHING""",
                (d, 2000.0 + i),
            )
    db.commit()
    return weeks


def cleanup_weekly(db, tickers, weeks):
    with db.cursor() as cur:
        for t in tickers:
            cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM weekly_index WHERE index_code='1001' AND week_end_date BETWEEN %s AND %s",
                    (weeks[0], weeks[-1]))
    db.commit()


WEEKLY_SPEC = {"RK124W1": ("up", 60), "RK124W2": ("down", 60), "RK124W3": ("wave", 30)}


def test_rank_table_equals_phase_b_weekly(db):
    tickers = list(WEEKLY_SPEC)
    weeks = seed_weekly(db, WEEKLY_SPEC)
    try:
        modes._phase_b_cache.clear()
        for t in tickers:
            modes._process_ticker_weekly(db, t, "KOSPI", weeks[0], weeks[-1], weeks[0])
        modes._run_phase_b_weekly(db, weeks[0], weeks[-1])
        modes._phase_b_cache.clear()
        stored = stored_rs(db, Target.WEEKLY, tickers)
        assert any(r[2] is not None for r in stored)
        uni = [t for t in m.universe_tickers(db, Target.WEEKLY) if t in tickers]
        sf = m.strength_table(db, Target.WEEKLY, tickers=uni, end=weeks[-1])
        got = m.rank_table(sf, weeks)
        assert_ranks_equal(got, stored)
    finally:
        cleanup_weekly(db, tickers, weeks)


# ---------------------------------------------------------------- Task 2: 영향 구간


def _seed_prices_only(db, t, days):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        for d in days:
            cur.execute("""INSERT INTO daily_prices (ticker, date, open, high, low, close,
                               adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value)
                           VALUES (%s,%s,1,1,1,1,1,1,1,1,1,1,1)""", (t, d))
            cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close) VALUES (%s,%s,1)", (t, d))
    db.commit()


def _cleanup_prices_only(db, tickers):
    with db.cursor() as cur:
        for t in tickers:
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
    db.commit()


def test_window_is_252_rows_from_gap(db):
    t, days = "RK124WN", _weekdays(date(2008, 1, 7), 400)
    _seed_prices_only(db, t, days)
    try:
        [w] = m.event_windows(db, Target.DAILY, [(t, days[100])])
        assert (w.ticker, w.start, w.end) == (t, days[100], days[351])
    finally:
        _cleanup_prices_only(db, [t])


def test_window_truncates_to_last_row(db):
    t, days = "RK124WT", _weekdays(date(2008, 1, 7), 400)
    _seed_prices_only(db, t, days)
    try:
        [w] = m.event_windows(db, Target.DAILY, [(t, days[280])])   # 뒤에 120행뿐
        assert (w.start, w.end) == (days[280], days[-1])
        assert m.event_windows(db, Target.DAILY, [(t, days[-1] + timedelta(days=10))]) == []
    finally:
        _cleanup_prices_only(db, [t])


def test_gap_on_non_trading_day_starts_at_next_row(db):
    t, days = "RK124WG", _weekdays(date(2008, 1, 7), 300)
    _seed_prices_only(db, t, days)
    try:
        sat = days[10] + timedelta(days=(5 - days[10].weekday()))  # 그 주 토요일
        [w] = m.event_windows(db, Target.DAILY, [(t, sat)])
        assert w.start == min(d for d in days if d > sat)
    finally:
        _cleanup_prices_only(db, [t])


def test_windows_merge_overlapping_dates(db):
    t, days = "RK124WM", _weekdays(date(2008, 1, 7), 600)
    _seed_prices_only(db, t, days)
    try:
        ws = m.event_windows(db, Target.DAILY, [(t, days[50]), (t, days[50 + 209])])
        dates = m.affected_dates(db, Target.DAILY, ws)
        assert len(dates) == 252 + 209 and dates == sorted(set(dates))
        assert m.merged_ranges(dates, days) == [(days[50], days[50 + 209 + 251])]
        # 떨어진 두 창은 두 구간
        ws2 = m.event_windows(db, Target.DAILY, [(t, days[0]), (t, days[300])])
        d2 = m.affected_dates(db, Target.DAILY, ws2)
        assert m.merged_ranges(d2, days) == [(days[0], days[251]), (days[300], days[551])]
    finally:
        _cleanup_prices_only(db, [t])


def test_all_dates_lists_indicator_dates(db):
    t, days = "RK124WA", _weekdays(date(2008, 1, 7), 30)
    _seed_prices_only(db, t, days)
    try:
        got = m.all_dates(db, Target.DAILY)
        assert [d for d in got if days[0] <= d <= days[-1]] == days
    finally:
        _cleanup_prices_only(db, [t])


# ---------------------------------------------------------------- Task 3: Phase C 셀 한정 + 비교·적용·복원

from kr_pipeline.common.thresholds import C8_RS_RATING_MIN  # noqa: E402  (테스트는 읽기만)
from kr_pipeline.indicators.store import (  # noqa: E402
    update_daily_indicators_minervini_pass, update_weekly_indicators_minervini_pass,
)


def _seed_ind_rows(db, rows):
    """rows = [(ticker, date, rs_rating)] — c1..c7 TRUE 행."""
    with db.cursor() as cur:
        for t, d, rs in rows:
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s AND date=%s", (t, d))
            cur.execute("""INSERT INTO daily_indicators (ticker, date, adj_close, rs_rating,
                               minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5, minervini_c6, minervini_c7,
                               updated_at)
                           VALUES (%s,%s,1,%s,TRUE,TRUE,TRUE,TRUE,TRUE,TRUE,TRUE, '2000-01-01')""", (t, d, rs))
    db.commit()


def test_minervini_pass_cells_filter(db):
    d1, d2 = date(2007, 3, 5), date(2007, 3, 6)
    rows = [("RK124P1", d1, 99), ("RK124P1", d2, 99), ("RK124P2", d1, 99), ("RK124P2", d2, 99)]
    _seed_ind_rows(db, rows)
    try:
        n = update_daily_indicators_minervini_pass(db, d1, d2, cells=[("RK124P1", d1)])
        db.commit()
        assert n == 1
        with db.cursor() as cur:
            cur.execute("SELECT ticker, date, minervini_c8, minervini_pass, updated_at::date FROM daily_indicators "
                        "WHERE ticker IN ('RK124P1','RK124P2') ORDER BY 1,2")
            got = cur.fetchall()
        assert got[0][2:] == (True, True, date.today())
        assert all(r[2] is None and r[3] is None and r[4] == date(2000, 1, 1) for r in got[1:])
        # 기본(cells=None) 은 구간 전체
        assert update_daily_indicators_minervini_pass(db, d1, d2) == 4
        db.commit()
    finally:
        _cleanup_prices_only(db, ["RK124P1", "RK124P2"])


def test_minervini_pass_cells_filter_weekly(db):
    w1 = date(2007, 3, 9)
    with db.cursor() as cur:
        for t in ("RK124Q1", "RK124Q2"):
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
            cur.execute("""INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, rs_rating,
                               minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5, minervini_c6, minervini_c7)
                           VALUES (%s,%s,1,99,TRUE,TRUE,TRUE,TRUE,TRUE,TRUE,TRUE)""", (t, w1))
    db.commit()
    try:
        assert update_weekly_indicators_minervini_pass(db, w1, w1, cells=[("RK124Q2", w1)]) == 1
        db.commit()
        with db.cursor() as cur:
            cur.execute("SELECT ticker, minervini_pass FROM weekly_indicators WHERE ticker IN ('RK124Q1','RK124Q2') ORDER BY 1")
            assert cur.fetchall() == [("RK124Q1", None), ("RK124Q2", True)]
    finally:
        with db.cursor() as cur:
            for t in ("RK124Q1", "RK124Q2"):
                cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
                cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
        db.commit()


def _drift_seed(db):
    """Task 1 시드 + Phase A/B 저장 후, A 의 gap 이전 adj_close 를 ×2 (재적재 모사; Phase B 는 다시 안 돌림)."""
    tickers = list(DAILY_SPEC)
    days = seed_daily(db, DAILY_SPEC, delisted={"RK124D"})
    run_phase_ab_daily(db, tickers, days)
    gap = days[60]   # 창 [60, 311] — 패리티 창(최근 30일 ≈ 마지막 22행, 378~399)과 겹치지 않게
    with db.cursor() as cur:   # gap 이전 ×0.1 = 권리락 ×10 소급(078860 형) → 252 항이 10배 → A 가 창 안에서 최상위로
        cur.execute("UPDATE daily_prices SET adj_close = adj_close * 0.1 WHERE ticker='RK124A' AND date < %s", (gap,))
    db.commit()
    return tickers, days, gap


def _plan(db, tickers, days, dates):
    uni = [t for t in m.universe_tickers(db, Target.DAILY) if t in tickers]
    sf = m.strength_table(db, Target.DAILY, tickers=uni, end=days[-1])
    return m.plan(db, Target.DAILY, dates, sf=sf, target_tickers={"RK124A"})


def test_diff_cells_only_changed(db):
    tickers, days, gap = _drift_seed(db)
    try:
        [w] = m.event_windows(db, Target.DAILY, [("RK124A", gap)])
        dates = m.affected_dates(db, Target.DAILY, [w])
        p = _plan(db, tickers, days, dates)
        cells = p["cells"]
        assert cells and all(c["old"] != c["new"] for c in cells)
        assert {c["date"] for c in cells} <= set(dates)
        assert all(c["ticker"] in tickers for c in cells)
        assert p["by_target_ticker"] + p["by_other"] == len(cells) and p["by_target_ticker"] > 0
        stored = {(t, d): rs for t, d, rs in stored_rs(db, Target.DAILY, tickers)}
        for c in cells:
            assert stored[(c["ticker"], c["date"])] == c["old"]
            assert c["old_c8"] == (c["old"] is not None and c["old"] >= C8_RS_RATING_MIN)
        # 창 밖(gap 이전·gap+252 이후)은 변경 0
        outside = [d for d in days if d not in set(dates)]
        p2 = _plan(db, tickers, days, outside)
        assert p2["cells"] == []
    finally:
        cleanup_daily(db, tickers, days)


def test_plan_aborts_when_parity_window_fails(db):
    tickers, days, gap = _drift_seed(db)
    try:
        uni = [t for t in m.universe_tickers(db, Target.DAILY) if t in tickers]
        sf = m.strength_table(db, Target.DAILY, tickers=uni, end=days[-1])
        ok = m.parity_window(db, Target.DAILY, sf, tickers=uni, days=30)
        assert ok["mismatch"] == 0 and ok["dates"] > 0
        with db.cursor() as cur:
            cur.execute("UPDATE daily_indicators SET rs_rating = rs_rating + 1 WHERE ticker='RK124B' AND date=%s", (days[-1],))
        db.commit()
        bad = m.parity_window(db, Target.DAILY, sf, tickers=uni, days=30)
        assert bad["mismatch"] == 1 and bad["sample"][0]["ticker"] == "RK124B"
        assert bad["n_by_date"][days[-1].isoformat()] == [3, 3]   # C 는 NaN → N 제외
    finally:
        cleanup_daily(db, tickers, days)


def test_apply_then_diff_is_empty(db):
    tickers, days, gap = _drift_seed(db)
    try:
        [w] = m.event_windows(db, Target.DAILY, [("RK124A", gap)])
        dates = m.affected_dates(db, Target.DAILY, [w])
        p = _plan(db, tickers, days, dates)
        with db.cursor() as cur:
            cur.execute("SELECT max(updated_at) FROM daily_indicators WHERE ticker = ANY(%s)", (tickers,))
            before = cur.fetchone()[0]
        r = m.apply(db, Target.DAILY, p["cells"])
        assert r["cells"] == len(p["cells"]) and r["pass_rows"] == len(p["cells"])
        assert _plan(db, tickers, days, dates)["cells"] == []
        keys = {(c["ticker"], c["date"]) for c in p["cells"]}
        with db.cursor() as cur:
            cur.execute("SELECT ticker, date, rs_rating, minervini_c8, updated_at FROM daily_indicators WHERE ticker = ANY(%s)", (tickers,))
            for t, d, rs, c8, up in cur.fetchall():
                if (t, d) in keys:
                    assert c8 == (rs is not None and rs >= C8_RS_RATING_MIN)
                else:
                    assert up <= before, "변경 셀 외 행이 갱신됨"
    finally:
        cleanup_daily(db, tickers, days)


def test_restore_returns_exact_old_values(db):
    tickers, days, gap = _drift_seed(db)
    try:
        [w] = m.event_windows(db, Target.DAILY, [("RK124A", gap)])
        dates = m.affected_dates(db, Target.DAILY, [w])
        cells = _plan(db, tickers, days, dates)["cells"]
        # 복원 검증용으로 한 셀의 pass 를 미리 비정상 값(NULL 아님)으로 둬 재유도가 아니라 원값 복원임을 확인
        with db.cursor() as cur:
            cur.execute("UPDATE daily_indicators SET minervini_pass = TRUE, minervini_c8 = FALSE WHERE ticker=%s AND date=%s",
                        (cells[0]["ticker"], cells[0]["date"]))
        db.commit()
        cells = _plan(db, tickers, days, dates)["cells"]
        snap = {(c["ticker"], c["date"]): (c["old"], c["old_c8"], c["old_pass"]) for c in cells}
        m.apply(db, Target.DAILY, cells)
        m.restore(db, Target.DAILY, cells)
        with db.cursor() as cur:
            cur.execute("SELECT ticker, date, rs_rating, minervini_c8, minervini_pass FROM daily_indicators WHERE ticker = ANY(%s)", (tickers,))
            for t, d, rs, c8, ps in cur.fetchall():
                if (t, d) in snap:
                    assert (rs, c8, ps) == snap[(t, d)]
        assert len(_plan(db, tickers, days, dates)["cells"]) == len(cells)
    finally:
        cleanup_daily(db, tickers, days)


# ---------------------------------------------------------------- Task 4: 일봉 rs 게이트 미러 종목 필터

from kr_pipeline.indicators.store import update_daily_rs_gate_from_weekly  # noqa: E402


def test_rs_gate_mirror_ticker_filter(db):
    d = date(2007, 5, 7)            # 월요일
    wk = date(2007, 5, 4)           # 직전 금요일 주봉
    ts = ("RK124G1", "RK124G2")
    with db.cursor() as cur:
        for t in ts:
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
            cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close, rs_line_not_declining_7m) VALUES (%s,%s,1,FALSE)", (t, d))
            cur.execute("INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, rs_line_not_declining_7m) VALUES (%s,%s,1,TRUE)", (t, wk))
    db.commit()
    try:
        assert update_daily_rs_gate_from_weekly(db, d, d, tickers=["RK124G1"]) == 1
        db.commit()
        with db.cursor() as cur:
            cur.execute("SELECT ticker, rs_line_not_declining_7m FROM daily_indicators WHERE ticker = ANY(%s) ORDER BY 1", (list(ts),))
            assert cur.fetchall() == [("RK124G1", True), ("RK124G2", False)]
        assert update_daily_rs_gate_from_weekly(db, d, d) >= 2   # 기본 = 구간 전체(다른 테스트 행 포함 가능)
        db.commit()
    finally:
        with db.cursor() as cur:
            for t in ts:
                cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
                cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
                cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
        db.commit()
