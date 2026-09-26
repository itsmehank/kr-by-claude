"""#203 weekend 체인 7m 게이트 1주 지연 — 1c 직후 주봉 게이트를 daily 에 미러(Phase D 동일 SQL) + 후보 차분 기록.

결함: LLM 후보 SQL(load.get_qualifying_tickers)은 daily_indicators.rs_line_not_declining_7m(미러 컬럼)을
읽는데, 미러는 평일 daily 체인(Phase D)에만 있어 토요일 후보가 직전 주 게이트로 뽑혔다(09-19 실증 61 vs 66).
"""
from datetime import date, timedelta

from kr_pipeline.indicators import modes as indicators
from kr_pipeline.pipeline import chains

# 다른 테스트가 kr_test 에 커밋해 둔 daily_indicators 행과 겹치지 않는 먼 미래 금요일.
FRI = date(2031, 1, 3)
SAT = date(2031, 1, 4)


def _seed(db, ticker, *, daily_gate, weekly_gate, minervini=True, week_end=FRI):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group) VALUES (%s, 'WG', 'KOSPI', '주권') "
                    "ON CONFLICT (ticker) DO UPDATE SET delisted_at = NULL", (ticker,))
        cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass, rs_line_not_declining_7m) "
                    "VALUES (%s, %s, 100, %s, %s)", (ticker, FRI, minervini, daily_gate))
        cur.execute("INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, rs_line_not_declining_7m) "
                    "VALUES (%s, %s, 100, %s)", (ticker, week_end, weekly_gate))


def test_mirror_daily_rs_gate_copies_current_week_gate_into_daily(db):
    """당해 주 주봉 게이트 TRUE·daily 미러 FALSE(직전 주 값) → 미러 후 daily TRUE. 창(target−30일..as_of)에
    2031 행은 이것 하나뿐이라 rows == 1."""
    _seed(db, "WG1", daily_gate=False, weekly_gate=True)
    info = indicators.mirror_daily_rs_gate(db, as_of=SAT)
    with db.cursor() as cur:
        cur.execute("SELECT rs_line_not_declining_7m FROM daily_indicators WHERE ticker='WG1' AND date=%s", (FRI,))
        assert cur.fetchone()[0] is True
    assert info["rows"] == 1
    assert info["as_of"] == FRI.isoformat()                       # 창 라벨 = 실제 최신 daily 행(토요일 as_of 아님)
    assert info["window_start"] == (FRI - timedelta(days=30)).isoformat()
    assert info["stale_gate_count"] == 0


def test_mirror_daily_rs_gate_nulls_gate_without_current_week_weekly_row(db):
    """당해 주 weekly 행이 없는 종목(주봉 지표 실패분)은 직전 주 값을 복사하지 않고 NULL(판정하지 않음, 회신 13)
    → 후보 SQL(= TRUE)에서 그 주 제외. 표지·건수는 유지."""
    _seed(db, "WG1", daily_gate=False, weekly_gate=True)
    _seed(db, "WG4", daily_gate=False, weekly_gate=True, week_end=FRI - timedelta(days=7))   # 직전 주 행만(TRUE)
    info = indicators.mirror_daily_rs_gate(db, as_of=SAT)
    assert info["stale_gate_count"] == 1 and info["stale_gate_sample"] == ["WG4"]
    with db.cursor() as cur:
        cur.execute("SELECT ticker, rs_line_not_declining_7m FROM daily_indicators WHERE ticker IN ('WG1','WG4') AND date=%s ORDER BY 1", (FRI,))
        assert cur.fetchall() == [("WG1", True), ("WG4", None)]
    assert "WG4" not in {r["symbol"] for r in chains.llm_load.get_qualifying_tickers(db, as_of=SAT)}


def test_mirror_gate_with_diff_records_candidate_set_change(db):
    """구 게이트(미러 전) 대비 후보 집합 차분 — 수정 후 첫 주말 실행 기록용(#203). 유지 종목(WG3)은 양쪽 카운트에."""
    _seed(db, "WG1", daily_gate=False, weekly_gate=True)    # 이번 주 진입 → added
    _seed(db, "WG2", daily_gate=True, weekly_gate=False)    # 이번 주 이탈 → removed
    _seed(db, "WG3", daily_gate=True, weekly_gate=True)     # 유지
    info = chains._mirror_gate_with_diff(db, as_of=SAT)
    assert info["as_of"] == FRI.isoformat()
    assert info["added"] == ["WG1"] and info["removed"] == ["WG2"]
    assert info["candidates_before"] == 2 and info["candidates_after"] == 2   # {WG2,WG3} → {WG1,WG3}
