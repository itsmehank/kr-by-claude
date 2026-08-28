from datetime import date, datetime, timedelta, timezone

import pytest

from api.services.review_streaks import (
    REVIEW_COVERAGE_START, fetch_scoped_rows, find_period_symbols,
    segment_streaks, intersect_period, attach_triggers, derive_stage, compute_metrics,
    build_pivot_steps, build_stock_rows, chart_window_start,
)

KST = timezone(timedelta(hours=9))


def _row(symbol, kd, cls, source, pivot=None, hour=10):
    return {
        "symbol": symbol, "key_date": date.fromisoformat(kd),
        "classified_at": datetime(2026, 1, 1, hour, tzinfo=KST).replace(
            year=int(kd[:4]), month=int(kd[5:7]), day=int(kd[8:10])),
        "market": "KOSPI", "source": source, "classification": cls,
        "pattern": None, "pivot_price": pivot, "backfilled": source == "backfill",
    }


def test_segment_closes_on_ignore_and_disqualify_and_continues_over_gap():
    rows = [
        _row("A", "2026-06-05", "watch", "weekend", 100.0),
        _row("A", "2026-06-12", "watch", "weekend", 110.0),
        # 20일 공백(>10일) — 이어짐 + has_gap
        _row("A", "2026-07-02", "entry", "daily_delta", 120.0),
        _row("A", "2026-07-04", "ignore", "weekend"),          # 닫힘 1
        _row("A", "2026-07-11", "watch", "weekend", 130.0),     # 새 묶음
        _row("A", "2026-07-15", "disqualified", "system_disqualify"),  # 닫힘 2
    ]
    s = segment_streaks(rows)
    assert len(s) == 2
    assert s[0]["start"] == date(2026, 6, 5)
    assert s[0]["end"] == date(2026, 7, 4) and s[0]["closed_by"] == "ignore"
    assert s[0]["has_gap"] is True and len(s[0]["analyses"]) == 3
    assert s[1]["start"] == date(2026, 7, 11)
    assert s[1]["end"] == date(2026, 7, 15) and s[1]["closed_by"] == "disqualify"
    assert s[1]["has_gap"] is False


def test_segment_open_streak_and_censored_badge():
    early = REVIEW_COVERAGE_START.isoformat()
    rows = [_row("B", early, "watch", "weekend", 50.0)]
    s = segment_streaks(rows)
    assert s[0]["end"] is None and s[0]["closed_by"] is None
    assert s[0]["censored"] is True          # 시작 ≤ COVERAGE_START+7d
    late = [_row("B", "2026-08-01", "watch", "weekend", 50.0)]
    assert segment_streaks(late)[0]["censored"] is False


def test_intersect_period_rules():
    s_before = {"start": date(2026, 6, 1), "end": date(2026, 6, 20), "closed_by": "ignore"}
    s_spanning = {"start": date(2026, 6, 1), "end": None, "closed_by": None}
    s_after = {"start": date(2026, 9, 1), "end": None, "closed_by": None}
    got = intersect_period([s_before, s_spanning, s_after],
                           date(2026, 7, 1), date(2026, 8, 1))
    assert got == [s_spanning]   # before: end<from 제외 / after: start>to 제외


@pytest.fixture
def seed(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'RVSTK%'")
        cur.execute("DELETE FROM classification_backfill WHERE symbol LIKE 'RVSTK%'")
        cur.execute("DELETE FROM daily_prices WHERE ticker LIKE 'RVSTK%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RVSTK%'")
        cur.execute("""INSERT INTO stocks (ticker, name, market, sector, listed_at)
                       VALUES ('RVSTK01','스톡1','KOSPI','반도체','2020-01-01')""")
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 -- 전역 하한 이전 라이브 행 → 제외되어야 함
                 ('RVSTK01','2026-05-10 10:00:00+09','KOSPI','watch',NULL,90,'weekend','2026-05-08'),
                 ('RVSTK01','2026-06-06 10:00:00+09','KOSPI','watch',NULL,100,'weekend','2026-06-05')""")
        cur.execute(
            """INSERT INTO classification_backfill
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 -- 하한 이전 백필 → 제외
                 ('RVSTK01','2026-08-01 10:00:00+09','KOSPI','watch',NULL,80,'backfill','2026-04-03'),
                 -- 하한 이후 백필, 라이브와 같은 key_date → 라이브 우선 dedup 제외
                 ('RVSTK01','2026-08-01 10:01:00+09','KOSPI','entry',NULL,999,'backfill','2026-06-05'),
                 -- 하한 이후 백필, 라이브 없음 → 유입 + backfilled=true
                 ('RVSTK01','2026-08-01 10:02:00+09','KOSPI','watch',NULL,105,'backfill','2026-06-19')""")
    db.commit()
    yield


def test_fetch_scoped_rows_global_floor_and_live_first_dedup(db, seed):
    rows = fetch_scoped_rows(db, symbols=["RVSTK01"])
    kds = [(r["key_date"].isoformat(), r["source"], r["backfilled"]) for r in rows]
    assert kds == [("2026-06-05", "weekend", False),      # 05-08 라이브 제외, 06-05 dedup 라이브 승
                   ("2026-06-19", "backfill", True)]      # 04-03 백필 제외
    assert rows[0]["pivot_price"] == 100.0                # 999(백필) 아님


@pytest.fixture
def week_seed(db):
    """PR #138 리뷰 — 주 단위 라이브 우선 dedup (공유 조각 MERGED_ROWS_CTES).
    백필 key_date=토요일 vs 라이브 주말 key_date=금요일: 정확 일치 dedup 은
    같은 주 이중 행을 못 막는다 → 같은 ISO 주 라이브 존재 시 백필 억제."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE symbol LIKE 'RVSWK%'")
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'RVSWK%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RVSWK%'")
        cur.execute("""INSERT INTO stocks (ticker, name, market, sector, listed_at)
                       VALUES ('RVSWK01','주스톡1','KOSPI','반도체','2020-01-01')""")
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES ('RVSWK01','2026-07-11 06:10:00+09','KOSPI','watch',NULL,
                       100,'weekend','2026-07-10')""")
        cur.execute(
            """INSERT INTO classification_backfill
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 -- 토 07-11: 라이브 07-10(금)과 같은 ISO 주 → 억제
                 ('RVSWK01','2026-08-30 12:00:00+09','KOSPI','watch',NULL,
                  101,'backfill','2026-07-11'),
                 -- 토 07-18: 라이브 없는 주 → 유지
                 ('RVSWK01','2026-08-30 12:00:00+09','KOSPI','watch',NULL,
                  102,'backfill','2026-07-18')""")
    db.commit()
    yield


def test_scoped_rows_week_dedup_live_friday_vs_backfill_saturday(db, week_seed):
    rows = fetch_scoped_rows(db, symbols=["RVSWK01"])
    kds = [(r["key_date"], r["backfilled"]) for r in rows]
    assert kds == [(date(2026, 7, 10), False),    # 라이브 유지, 07-11 백필 억제
                   (date(2026, 7, 18), True)]     # 라이브 없는 주 백필 유지


def test_find_period_symbols_filters(db, seed):
    assert find_period_symbols(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
                               source=None, ticker=None).count("RVSTK01") == 1
    assert "RVSTK01" not in find_period_symbols(
        db, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), source=None, ticker=None)
    assert "RVSTK01" not in find_period_symbols(
        db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
        source="daily_delta", ticker=None)


def _trig(d, ttype, close=None, pivot=None):
    return {"d": date.fromisoformat(d), "trigger_type": ttype, "decision": "wait",
            "close": close, "pivot_price": pivot, "reasoning": None,
            "evaluated_at": datetime(2026, 6, 1, 21, tzinfo=KST)}


def _streak(analyses, triggers_by_idx=None):
    for i, a in enumerate(analyses):
        a["triggers"] = (triggers_by_idx or {}).get(i, [])
    return {"symbol": "A", "start": analyses[0]["key_date"], "end": None,
            "closed_by": None, "censored": False, "backfilled": False,
            "has_gap": False, "analyses": analyses}


def test_derive_stage_four_buckets():
    a_pivot = _row("A", "2026-06-05", "watch", "weekend", 100.0)
    a_nopivot = _row("A", "2026-06-05", "watch", "weekend", None)
    assert derive_stage(_streak([dict(a_pivot)], {0: [_trig("2026-06-10", "breakout_from_watch", 102, 100)]})) == "breakout"
    assert derive_stage(_streak([dict(a_pivot)], {0: [_trig("2026-06-10", "promotion")]})) == "staging"
    assert derive_stage(_streak([dict(a_pivot)])) == "watching"
    assert derive_stage(_streak([dict(a_nopivot)])) == "base_forming"
    # invalidation만 있으면 staging 아님 → watching(pivot 있음)
    assert derive_stage(_streak([dict(a_pivot)], {0: [_trig("2026-06-10", "invalidation")]})) == "watching"


def test_compute_metrics_breakout_chain_and_watching_reach():
    series = [(date(2026, 6, 10), 100.0), (date(2026, 6, 11), 104.0),
              (date(2026, 6, 12), 108.0), (date(2026, 6, 15), 112.0),
              (date(2026, 6, 16), 116.0), (date(2026, 6, 17), 120.0)]
    a = _row("A", "2026-06-05", "watch", "weekend", 100.0)
    st = _streak([dict(a)], {0: [_trig("2026-06-10", "breakout_from_watch", close=102.0, pivot=100.0)]})
    m = compute_metrics(st, series, today=date(2026, 6, 30), corp_flagged=False)
    # pivot_delta=2%; T+5 = 1.02×120/100−1 = 0.224
    assert m["stage"] == "breakout" and abs(m["t5_pct"] - 0.224) < 1e-9
    assert m["t20_pct"] is None and m["first_breakout_at"] == date(2026, 6, 10)
    st2 = _streak([dict(a)])
    m2 = compute_metrics(st2, series, today=date(2026, 6, 30), corp_flagged=True)
    # watching: 마지막 pivot(100), 창 (06-05, 오늘] → max 120 → +20%
    assert m2["stage"] == "watching" and abs(m2["max_reach_pct"] - 0.20) < 1e-9
    assert m2["corp_action_flag"] is True and m2["t5_pct"] is None


@pytest.fixture
def seed_trigger(db, seed):
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'RVSTK%'")
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, reasoning, prior_classification_at, analyzed_for_date)
               VALUES ('RVSTK01','2026-06-08 21:00:00+09','promotion',98,1000,100,
                       'wait','접근','2026-06-06 10:00:00+09','2026-06-08')""")
    db.commit()
    yield


def test_attach_triggers_nested_by_prior(db, seed_trigger):
    rows = fetch_scoped_rows(db, symbols=["RVSTK01"])
    streaks = segment_streaks(rows)
    attach_triggers(db, streaks)
    a0 = streaks[0]["analyses"][0]           # 06-05 라이브 분석
    assert len(a0["triggers"]) == 1
    assert a0["triggers"][0]["trigger_type"] == "promotion"
    assert a0["triggers"][0]["d"] == date(2026, 6, 8)
    # 백필 분석(06-19)에는 트리거 없음
    assert streaks[0]["analyses"][1]["triggers"] == []


def test_build_pivot_steps_cuts_at_streak_close():
    a1 = _row("A", "2026-06-05", "watch", "weekend", 100.0)
    a2 = _row("A", "2026-06-12", "watch", "weekend", 110.0)
    a3 = _row("A", "2026-07-11", "watch", "weekend", None)     # pivot 없음
    a4 = _row("A", "2026-07-18", "watch", "weekend", 130.0)
    s1 = _streak([a1, a2]); s1["end"] = date(2026, 6, 20); s1["closed_by"] = "ignore"
    s2 = _streak([a3, a4])
    steps = build_pivot_steps([s1, s2])
    assert steps == [
        (date(2026, 6, 5), date(2026, 6, 12), 100.0),
        (date(2026, 6, 12), date(2026, 6, 20), 110.0),   # 닫는 행에서 끊김 (07-11 아님)
        (date(2026, 7, 18), None, 130.0),                 # 진행중 → to_kd None
    ]


@pytest.fixture
def seed_prices(db, seed_trigger):
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_prices WHERE ticker LIKE 'RVSTK%'")
        cur.execute(
            """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                                         adj_close, volume, value)
               SELECT 'RVSTK01', d::date, 1,1,1,1, 100 + row_number() OVER (), 1000, 1000
                 FROM generate_series('2026-05-20'::date, '2026-08-20', '1 day') d
                WHERE extract(isodow FROM d) < 6""")
    db.commit()
    yield
    # Clean up after test
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_prices WHERE ticker LIKE 'RVSTK%'")
    db.commit()


def test_chart_window_start_offset_and_clamp(db, seed_prices):
    # 06-05 직전 120거래일이 없으면(5/20 시작) 최초 행으로 클램프
    assert chart_window_start(db, "RVSTK01", date(2026, 6, 5)) == date(2026, 5, 20)
    assert chart_window_start(db, "NOROWS", date(2026, 6, 5)) == date(2026, 6, 5)


def test_build_stock_rows_end_to_end(db, seed_prices):
    got = build_stock_rows(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
                           source=None, ticker="RVSTK01", status=None,
                           limit=200, offset=0, today=date(2026, 8, 20))
    assert len(got["rows"]) == 1
    row = got["rows"][0]
    assert row["latest"]["stage"] == "staging"          # promotion 만 존재
    assert row["latest"]["streak_count"] == 1
    assert row["streaks"][0]["analyses"][1]["backfilled"] is True
    assert row["series"][0][0] == date(2026, 5, 20)     # 클램프된 창 시작
    assert row["pivot_steps"][0][2] == 100.0
    # (I1) 표시 클램프: 응답 series·analyses 는 to(06-30) 이하만
    assert row["series"][-1][0] <= date(2026, 6, 30)
    assert all(a["key_date"] <= date(2026, 6, 30)
               for s in row["streaks"] for a in s["analyses"])
    # (I2) metrics 는 오늘(08-20)까지의 데이터 사용 — 6월 말까지의 도달률(~+30%)로는
    # 불가능한 값이어야 함 (가격이 하루 +1 씩 8월까지 상승하는 픽스처)
    assert row["latest"]["max_reach_pct"] > 0.5
    # status 필터: open 만 → 포함 / closed → 제외
    assert build_stock_rows(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
                            source=None, ticker="RVSTK01", status="closed",
                            limit=200, offset=0, today=date(2026, 8, 20))["rows"] == []


def test_display_clamp_keeps_closed_by(db, seed_prices):
    # 닫는 행(ignore)을 to 이후(07-10)에 심으면: end 는 to 로 절단되되 status 는 closed
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES ('RVSTK01','2026-07-10 10:00:00+09','KOSPI','ignore',NULL,
                       NULL,'weekend','2026-07-10')""")
    db.commit()
    got = build_stock_rows(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
                           source=None, ticker="RVSTK01", status=None,
                           limit=200, offset=0, today=date(2026, 8, 20))
    row = got["rows"][0]
    assert row["latest"]["status"] == "closed"                      # 원본 기준
    assert row["streaks"][0]["closed_by"] == "ignore"               # 유지
    assert row["streaks"][0]["end"] == date(2026, 6, 30)            # 표시 절단
