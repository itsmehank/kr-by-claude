"""(전문가 판정 회신 6 — 판정 1) 유니버스 배제 종료 행은 disqualified 를 재사용하지 않는다.

원칙: 파이프라인 상태 값은 '판정해서 떨어짐'과 '판정 대상이 아님'을 같은 값으로 표현하지 않는다.
확인 (a): 기존 조회·집계 경로에서 신규 값의 취급 — 양성 목록(entry/watch) 소비처는 자동 제외,
음성 목록(<> 'disqualified') 소비처는 신규 값을 명시 포함.
"""
from datetime import date, datetime, timezone

from kr_pipeline.common import security_group as sg
from kr_pipeline.llm_runner.load import get_active_monitoring, get_classified_losing_minervini
from kr_pipeline.llm_runner.store import insert_classification, insert_universe_exclusion


def test_label_constants_do_not_contain_disqualify():
    assert sg.UNIVERSE_EXCLUSION_CLASSIFICATION == "excluded_by_universe"
    assert sg.UNIVERSE_EXCLUSION_SOURCE == "system_universe_gate"
    for v in (sg.UNIVERSE_EXCLUSION_CLASSIFICATION, sg.UNIVERSE_EXCLUSION_SOURCE):
        assert "disqualif" not in v and "강등" not in v and "이탈" not in v


def _seed_entry(db, symbol: str, when: datetime):
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol = %s", (symbol,))
        cur.execute("DELETE FROM stocks WHERE ticker = %s", (symbol,))
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group) VALUES (%s, 'X', 'KOSPI', '투자회사')", (symbol,))
    insert_classification(db, symbol=symbol, classified_at=when, market="KOSPI",
                          result={"classification": "entry", "pattern": "cup_with_handle", "confidence": 0.9,
                                  "reasoning": "r", "risk_flags": []},
                          source="weekend", llm_meta={"duration_s": 1, "input_tokens": 1, "output_tokens": 1, "model": "m"},
                          analyzed_for_date=when.date())


def test_insert_universe_exclusion_writes_new_label_and_reason(db):
    t0 = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
    _seed_entry(db, "UEX1", t0)
    reason = sg.excluded_reason_text("투자회사")
    insert_universe_exclusion(db, symbol="UEX1", classified_at=t0.replace(day=15), market="KOSPI",
                              reason=reason, analyzed_for_date=date(2026, 9, 15))
    with db.cursor() as cur:
        cur.execute("""SELECT classification, source, reasoning, excluded_reason, pattern, confidence
                         FROM weekly_classification WHERE symbol='UEX1' ORDER BY classified_at DESC LIMIT 1""")
        row = cur.fetchone()
    assert row[0] == "excluded_by_universe" and row[1] == "system_universe_gate"
    assert row[2] == reason and row[3] == reason
    assert row[4] is None and row[5] is None
    for banned in ("자격 상실", "추세", "강등", "이탈", "손절", "minervini_pass"):
        assert banned not in row[2]


def test_active_monitoring_and_losing_minervini_exclude_new_label(db):
    """양성 목록 소비처(entry/watch, entry/watch/ignore)는 신규 값을 자동 제외 — 트리거 평가·재강등 중단."""
    t0 = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)
    _seed_entry(db, "UEX2", t0)
    assert "UEX2" in {a["symbol"] for a in get_active_monitoring(db)}
    insert_universe_exclusion(db, symbol="UEX2", classified_at=t0.replace(day=15), market="KOSPI",
                              reason=sg.excluded_reason_text("투자회사"), analyzed_for_date=date(2026, 9, 15))
    assert "UEX2" not in {a["symbol"] for a in get_active_monitoring(db)}
    with db.cursor() as cur:  # minervini_pass=FALSE 행이 있어도 최신 분류가 신규 값이면 강등 후보 아님
        cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass) VALUES ('UEX2', '2026-09-16', 1, FALSE)")
    assert "UEX2" not in {r["symbol"] for r in get_classified_losing_minervini(db, date(2026, 9, 16))}


def test_review_streak_closer_kind_is_distinct_from_disqualify():
    from api.services.review_streaks import _closer_kind
    assert _closer_kind({"classification": "excluded_by_universe", "source": "system_universe_gate"}) == "universe_excluded"
    assert _closer_kind({"classification": "disqualified", "source": "system_disqualify"}) == "disqualify"
    assert _closer_kind({"classification": "entry", "source": "weekend"}) is None
