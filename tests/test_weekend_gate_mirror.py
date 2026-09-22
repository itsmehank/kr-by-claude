"""#203 weekend 체인 7m 게이트 1주 지연 — 1c 직후 주봉 게이트를 daily 에 미러(Phase D 동일 SQL) + 후보 차분 기록.

결함: LLM 후보 SQL(load.get_qualifying_tickers)은 daily_indicators.rs_line_not_declining_7m(미러 컬럼)을
읽는데, 미러는 평일 daily 체인(Phase D)에만 있어 토요일 후보가 직전 주 게이트로 뽑혔다(09-19 실증 61 vs 66).
"""
from datetime import date

from kr_pipeline.indicators import modes as indicators

# 다른 테스트가 kr_test 에 커밋해 둔 daily_indicators 행과 겹치지 않는 먼 미래 금요일.
FRI = date(2031, 1, 3)
SAT = date(2031, 1, 4)


def _seed(db, ticker, *, daily_gate, weekly_gate, minervini=True):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group) VALUES (%s, 'WG', 'KOSPI', '주권') "
                    "ON CONFLICT (ticker) DO UPDATE SET delisted_at = NULL", (ticker,))
        cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass, rs_line_not_declining_7m) "
                    "VALUES (%s, %s, 100, %s, %s)", (ticker, FRI, minervini, daily_gate))
        cur.execute("INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, rs_line_not_declining_7m) "
                    "VALUES (%s, %s, 100, %s)", (ticker, FRI, weekly_gate))


def test_mirror_daily_rs_gate_copies_current_week_gate_into_daily(db):
    """당해 주 주봉 게이트 TRUE·daily 미러 FALSE(직전 주 값) → 미러 후 daily TRUE."""
    _seed(db, "WG1", daily_gate=False, weekly_gate=True)
    info = indicators.mirror_daily_rs_gate(db, as_of=SAT)
    with db.cursor() as cur:
        cur.execute("SELECT rs_line_not_declining_7m FROM daily_indicators WHERE ticker='WG1' AND date=%s", (FRI,))
        assert cur.fetchone()[0] is True
    assert info["rows"] >= 1


def test_mirror_daily_rs_gate_records_candidate_set_diff(db):
    """구 게이트(미러 전) 대비 후보 집합 차분을 반환 — 수정 후 첫 주말 실행 기록용(#203)."""
    _seed(db, "WG1", daily_gate=False, weekly_gate=True)    # 이번 주 진입 → added
    _seed(db, "WG2", daily_gate=True, weekly_gate=False)    # 이번 주 이탈 → removed
    _seed(db, "WG3", daily_gate=True, weekly_gate=True)     # 유지
    info = indicators.mirror_daily_rs_gate(db, as_of=SAT)
    assert info["as_of"] == FRI.isoformat()
    assert info["added"] == ["WG1"] and info["removed"] == ["WG2"]
    assert info["candidates_after"] - info["candidates_before"] == 0   # +1 −1
