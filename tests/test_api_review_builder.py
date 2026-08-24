from datetime import date, datetime, timezone, timedelta

import pytest

from api.services.review_builder import (
    fetch_analysis_rows, count_orphan_triggers, derive_status,
    first_breakout, first_promotion_d, BREAKOUT_TYPES,
)

KST = timezone(timedelta(hours=9))


@pytest.fixture
def seed(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'RVTEST%'")
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'RVTEST%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RVTEST%'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('RVTEST01','회고1','KOSPI','반도체','2020-01-01'),
                      ('RVTEST02','회고2','KOSDAQ','제약','2020-01-01')"""
        )
        # RVTEST01 — 스펙 §1 backdate 시나리오 (000430 실사례 재현):
        #  화 19:41 delta watch(pivot 4520) → 화 21:01 promotion 트리거
        #  → 수 02:53 weekend ignore 가 key_date 를 화요일로 소급.
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 ('RVTEST01','2026-06-02 19:41:48+09','KOSPI','watch','flat_base',
                  4520,'daily_delta','2026-06-02'),
                 ('RVTEST01','2026-06-03 02:53:06+09','KOSPI','ignore',NULL,
                  NULL,'weekend','2026-06-02'),
                 ('RVTEST02','2026-06-01 10:00:00+09','KOSDAQ','watch','cup_with_handle',
                  10000,'weekend','2026-05-30')"""
        )
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, reasoning, prior_classification_at, analyzed_for_date)
               VALUES
                 ('RVTEST01','2026-06-02 21:01:40+09','promotion',4400,100000,4520,
                  'wait','접근','2026-06-02 19:41:48+09','2026-06-02'),
                 -- 고아: prior 가 어떤 분류 행과도 불일치
                 ('RVTEST02','2026-06-04 21:00:00+09','promotion',9800,100000,10000,
                  'wait','고아','2026-01-01 00:00:00+09','2026-06-04')"""
        )
    db.commit()
    yield


def test_backdated_weekend_does_not_steal_trigger(db, seed):
    rows = fetch_analysis_rows(
        db, date_from=date(2026, 5, 25), date_to=date(2026, 6, 30),
        classification=None, source=None, pattern=None, ticker="RVTEST01",
        include_pivot_null=True, limit=100, offset=0,
    )
    # 회고 행은 delta watch 1건뿐 (ignore 는 회고 행 아님)
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "daily_delta"
    # 직접 조인: promotion 트리거가 delta watch 행에 귀속
    assert len(r["triggers"]) == 1
    assert r["triggers"][0]["trigger_type"] == "promotion"
    assert r["triggers"][0]["d"] == date(2026, 6, 2)


def test_next_key_date_uses_all_rows_including_ignore(db, seed):
    rows = fetch_analysis_rows(
        db, date_from=date(2026, 5, 25), date_to=date(2026, 6, 30),
        classification=None, source=None, pattern=None, ticker="RVTEST01",
        include_pivot_null=True, limit=100, offset=0,
    )
    # 다음 행이 ignore 여도 구간은 거기서 끝난다 (LEAD 는 필터 전 전체 행)
    assert rows[0]["next_key_date"] == date(2026, 6, 2)  # 소급된 ignore 의 key_date


def test_orphan_trigger_counted_not_dropped(db, seed):
    n = count_orphan_triggers(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
    assert n == 1  # RVTEST02 의 고아 1건
    rows = fetch_analysis_rows(
        db, date_from=date(2026, 5, 25), date_to=date(2026, 6, 30),
        classification=None, source=None, pattern=None, ticker="RVTEST02",
        include_pivot_null=True, limit=100, offset=0,
    )
    assert rows and rows[0]["triggers"] == []  # 고아는 행에 붙지 않음


def test_derive_status_table():
    promo = {"trigger_type": "promotion", "d": date(2026, 6, 2),
             "evaluated_at": datetime(2026, 6, 2, 21, 0, tzinfo=KST)}
    bfw = {"trigger_type": "breakout_from_watch", "d": date(2026, 6, 4),
           "evaluated_at": datetime(2026, 6, 4, 21, 0, tzinfo=KST)}
    inval = {"trigger_type": "invalidation", "d": date(2026, 6, 3),
             "evaluated_at": datetime(2026, 6, 3, 21, 0, tzinfo=KST)}
    assert derive_status([], None, None) == "미발동"
    assert derive_status([inval], None, None) == "미발동"        # invalidation-only
    assert derive_status([promo, inval], None, None) == "staging"  # 공존해도 staging
    assert derive_status([promo, bfw], 0.02, None) == "돌파-진행중"  # T+20 미도래
    assert derive_status([promo, bfw], 0.02, 0.11) == "돌파-완료"
    assert first_breakout([promo, bfw])["trigger_type"] == "breakout_from_watch"
    assert first_promotion_d([promo, bfw]) == date(2026, 6, 2)
