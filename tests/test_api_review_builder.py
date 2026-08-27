from datetime import date, datetime, timezone, timedelta

import pytest

from api.services.review_builder import (
    fetch_analysis_rows, count_orphan_triggers, derive_status,
    first_breakout, first_promotion_d, BREAKOUT_TYPES,
)
from api.services.review_builder import (
    fetch_price_series, chain_tn, max_reach, build_spark, corp_action_flags,
)

KST = timezone(timedelta(hours=9))


@pytest.fixture
def seed(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'RVTEST%'")
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'RVTEST%'")
        # #132 이후 _ROWS_SQL 이 classification_backfill 도 읽는다 — 잔여 행 격리
        cur.execute("DELETE FROM classification_backfill WHERE symbol LIKE 'RVTEST%'")
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


# 시리즈는 (date, adj_close) 튜플 리스트 — DB 불필요한 순수 계산 테스트
def _series(*pairs):
    return [(date.fromisoformat(d), float(v)) for d, v in pairs]


def test_chain_tn_renormalization_invariant():
    # 돌파일 D=6/4, pivot_delta=+2% (스냅샷). T+2 종가가 D 대비 +10% 라면
    # T+2 = 1.02 × 1.10 − 1 = +12.2%
    s = _series(("2026-06-04", 100), ("2026-06-05", 104), ("2026-06-08", 110))
    t2 = chain_tn(s, date(2026, 6, 4), 0.02, 2)
    assert abs(t2 - 0.122) < 1e-9
    # 기업행위 재정규화: 전체 시리즈가 1/5 로 rescale 돼도 값 불변 (스펙 §1 체인식)
    s5 = [(d, v / 5) for d, v in s]
    assert abs(chain_tn(s5, date(2026, 6, 4), 0.02, 2) - t2) < 1e-9


def test_chain_tn_none_when_not_arrived():
    s = _series(("2026-06-04", 100), ("2026-06-05", 104))
    assert chain_tn(s, date(2026, 6, 4), 0.02, 5) is None


def test_trading_day_counting_skips_calendar_holidays():
    # 6/5(금) 다음 거래일 행이 6/9(화)라면 — 6/8(월, 대체공휴일 가정)은 행이 없어
    # 자동 배제되고, 6/9 가 D+2 거래일이다.
    s = _series(("2026-06-04", 100), ("2026-06-05", 102), ("2026-06-09", 108))
    assert abs(chain_tn(s, date(2026, 6, 4), 0.0, 2) - 0.08) < 1e-9


def test_max_reach_excludes_day_zero():
    # key_date 당일(6/2, 120 — 분석의 입력)은 제외. 창 내 최고 110 → +10%
    s = _series(("2026-06-02", 120), ("2026-06-03", 105), ("2026-06-04", 110))
    r = max_reach(s, date(2026, 6, 2), None, 100.0, today=date(2026, 6, 30))
    assert abs(r - 0.10) < 1e-9


def test_max_reach_window_ends_at_next_key_date():
    # t'=6/4 → 6/4 이후(포함) 가격 130 은 계상 금지 (연장 없음)
    s = _series(("2026-06-02", 100), ("2026-06-03", 105), ("2026-06-04", 130))
    r = max_reach(s, date(2026, 6, 2), date(2026, 6, 4), 100.0, today=date(2026, 6, 30))
    assert abs(r - 0.05) < 1e-9


def test_max_reach_zero_length_window_is_none():
    s = _series(("2026-06-02", 100))
    assert max_reach(s, date(2026, 6, 2), date(2026, 6, 2), 100.0,
                     today=date(2026, 6, 30)) is None


def test_build_spark_downsample_preserves_extremes():
    vals = list(range(100))          # 0..99 오름차순
    vals[37] = 500                   # 최고점
    vals[71] = -500                  # 최저점
    s = [(date(2026, 1, 1), 0.0)] * 0
    s = [(date.fromordinal(738000 + i), float(v)) for i, v in enumerate(vals)]
    spark = build_spark(s, s[0][0], s[-1][0], cap=60)
    assert len(spark) <= 60
    assert 500.0 in spark and -500.0 in spark
    assert spark[-1] == vals[-1]  # 마지막 인덱스(최신 가격) 보존 — 리뷰 지적 회귀 가드


@pytest.fixture
def corp_action_seed(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM corporate_actions WHERE ticker LIKE 'RVCA%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RVCA%'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('RVCA01','회고CA1','KOSPI','반도체','2020-01-01'),
                      ('RVCA02','회고CA2','KOSPI','반도체','2020-01-01'),
                      ('RVCA03','회고CA3','KOSPI','반도체','2020-01-01'),
                      ('RVCA04','회고CA4','KOSPI','반도체','2020-01-01')"""
        )
        cur.execute(
            """INSERT INTO corporate_actions (ticker, event_date, event_type)
               VALUES
                 ('RVCA01','2026-06-05','capital_reduction'),
                 ('RVCA02','2026-07-15','capital_reduction'),
                 ('RVCA03','2026-05-20','capital_reduction')"""
        )
        # RVCA04: 이벤트 없음
    db.commit()
    yield


def test_corp_action_flags_four_cases(db, corp_action_seed):
    """스펙 §1: event_date ∈ [key_date, 오늘] 이면 flag. 상한이 '오늘'이므로
    성과 창(next_key_date)이 이미 끝난 뒤 발생한 이벤트도 flag 돼야 한다(연장된
    rescale 영향권)."""
    key_date = date(2026, 6, 2)
    today = date(2026, 8, 1)
    pairs = [
        ("RVCA01", key_date),  # (a) key_date~오늘 창 안
        ("RVCA02", key_date),  # (b) 성과 창(~6/30 상당) 종료 후·오늘 이전 — 그래도 flag
        ("RVCA03", key_date),  # (c) key_date 이전(창 밖) — 미flag
        ("RVCA04", key_date),  # (d) 이벤트 없음 — 미flag
    ]
    flags = corp_action_flags(db, pairs, today=today)
    assert ("RVCA01", key_date) in flags
    assert ("RVCA02", key_date) in flags
    assert ("RVCA03", key_date) not in flags
    assert ("RVCA04", key_date) not in flags


@pytest.fixture
def catchup_seed(db):
    """캐치업 시나리오: 트리거 평가 배치가 토요일 새벽(KST)에 도는데, 그 배치가
    실제로 평가한 거래일(analyzed_for_date)은 금요일이다. D 는 evaluated_at 의
    날짜부분(토요일, 시장 미개장)이 아니라 analyzed_for_date(금요일)이어야 한다
    (COALESCE 규칙, review_builder.py _TRIGGERS_SQL)."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'RVCU%'")
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'RVCU%'")
        cur.execute("DELETE FROM daily_prices WHERE ticker LIKE 'RVCU%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RVCU%'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('RVCU01','캐치업','KOSPI','반도체','2020-01-01')"""
        )
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 ('RVCU01','2026-06-05 19:41:48+09','KOSPI','watch','flat_base',
                  10000,'daily_delta','2026-06-05')"""
        )
        # evaluated_at = 토요일(6/6) 새벽 03:15 KST 캐치업 배치, 그러나
        # analyzed_for_date = 금요일(6/5) — 실제 평가 대상 거래일.
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, reasoning, prior_classification_at, analyzed_for_date)
               VALUES
                 ('RVCU01','2026-06-06 03:15:00+09','breakout_from_watch',10500,
                  100000,10000,'wait','캐치업 돌파',
                  '2026-06-05 19:41:48+09','2026-06-05')"""
        )
        cur.execute(
            """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                                         adj_close, volume, value)
               SELECT 'RVCU01', d::date, 1,1,1,1, v, 1000, 1000
                 FROM (VALUES ('2026-06-05',10500.0),('2026-06-08',10600.0),
                              ('2026-06-09',10700.0),('2026-06-10',10800.0),
                              ('2026-06-11',10900.0),('2026-06-12',11550.0)
                      ) AS t(d, v)"""
        )
    db.commit()
    yield


def test_catchup_trigger_d_uses_analyzed_for_date(db, catchup_seed):
    rows = fetch_analysis_rows(
        db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
        classification=None, source=None, pattern=None, ticker="RVCU01",
        include_pivot_null=True, limit=100, offset=0,
    )
    assert len(rows) == 1
    fb = first_breakout(rows[0]["triggers"])
    assert fb is not None
    # D = analyzed_for_date(금요일 6/5) — evaluated_at 의 날짜부분(토요일 6/6) 아님
    assert fb["d"] == date(2026, 6, 5)
    assert fb["evaluated_at"].date() == date(2026, 6, 6)

    # 체인 항등식이 그 D(금요일) 기준으로 성립하는지 확인: 토요일 앵커였다면
    # series 에 6/6 행이 없어 chain_tn 이 None 을 반환했을 것이다.
    series = fetch_price_series(db, "RVCU01", fb["d"], date(2026, 6, 30))
    pivot_delta = (fb["close"] - fb["pivot_price"]) / fb["pivot_price"]
    t5 = chain_tn(series, fb["d"], pivot_delta, 5)
    assert t5 is not None
    # pivot_delta=0.05, D+5(6/12) adj=11550, D(6/5) adj=10500 → 11550/10500=1.10
    # t5 = 1.05 × 1.10 − 1 = 0.155
    assert abs(t5 - 0.155) < 1e-9


@pytest.fixture
def backfill_seed(db):
    """#132 — classification_backfill UNION 소비. streak 뷰(_SCOPED_SQL) 규약과 동일:
    backfilled 플래그·라이브 우선 dedup·전역 하한(REVIEW_COVERAGE_START)."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE symbol LIKE 'RVBF%'")
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'RVBF%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RVBF%'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('RVBF01','백필1','KOSPI','반도체','2020-01-01'),
                      ('RVBF02','백필2','KOSDAQ','제약','2020-01-01')"""
        )
        # RVBF01: 라이브 06-16 → (결손) → 라이브 08-07. 백필 06-20 이 사이를 채운다.
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 ('RVBF01','2026-06-17 06:10:00+09','KOSPI','watch','flat_base',
                  10000,'weekend','2026-06-16'),
                 ('RVBF01','2026-08-08 06:10:00+09','KOSPI','watch','flat_base',
                  11000,'weekend','2026-08-07'),
                 -- RVBF02: 라이브와 백필이 같은 key_date(06-20) — 라이브 우선
                 ('RVBF02','2026-06-20 19:41:00+09','KOSDAQ','watch','vcp',
                  5000,'daily_delta','2026-06-20')"""
        )
        cur.execute(
            """INSERT INTO classification_backfill
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 ('RVBF01','2026-08-30 12:00:00+09','KOSPI','watch','flat_base',
                  10500,'backfill','2026-06-20'),
                 -- 전역 하한 이전(2024) 백테스트 유래 합성 행 — /review 에 나오면 안 됨
                 ('RVBF01','2026-08-30 12:00:00+09','KOSPI','watch','cup_with_handle',
                  8000,'backfill','2024-06-01'),
                 -- RVBF02: 같은 key_date 에 라이브 존재 → dedup 으로 제외
                 ('RVBF02','2026-08-30 12:00:00+09','KOSDAQ','watch','vcp',
                  5100,'backfill','2026-06-20')"""
        )
    db.commit()
    yield


def _fetch_bf(db, ticker, **kw):
    args = dict(date_from=date(2024, 1, 1), date_to=date(2026, 12, 31),
                classification=None, source=None, pattern=None, ticker=ticker,
                include_pivot_null=True, limit=100, offset=0)
    args.update(kw)
    return fetch_analysis_rows(db, **args)


def test_backfill_row_included_with_flag(db, backfill_seed):
    rows = _fetch_bf(db, "RVBF01")
    by_kd = {r["key_date"]: r for r in rows}
    assert date(2026, 6, 20) in by_kd
    bf = by_kd[date(2026, 6, 20)]
    assert bf["backfilled"] is True
    assert bf["source"] == "backfill"
    assert bf["pivot_price"] == 10500.0
    # 라이브 행은 backfilled=False
    assert by_kd[date(2026, 6, 16)]["backfilled"] is False


def test_backfill_floor_excludes_pre_coverage_rows(db, backfill_seed):
    rows = _fetch_bf(db, "RVBF01")
    # 2024-06-01 백테스트 유래 행은 전역 하한(REVIEW_COVERAGE_START) 이전 — 제외
    assert date(2024, 6, 1) not in {r["key_date"] for r in rows}


def test_backfill_deduped_when_live_exists_same_key_date(db, backfill_seed):
    rows = _fetch_bf(db, "RVBF02")
    assert len(rows) == 1
    assert rows[0]["backfilled"] is False
    assert rows[0]["source"] == "daily_delta"
    assert rows[0]["pivot_price"] == 5000.0   # 라이브 값 (백필 5100 아님)


def test_lead_crosses_live_and_backfill(db, backfill_seed):
    rows = _fetch_bf(db, "RVBF01")
    by_kd = {r["key_date"]: r for r in rows}
    # 라이브 06-16 의 구간(t')은 백필 06-20 에서 끊긴다
    assert by_kd[date(2026, 6, 16)]["next_key_date"] == date(2026, 6, 20)
    # 백필 06-20 의 구간은 라이브 08-07 에서 끊긴다 (역방향)
    assert by_kd[date(2026, 6, 20)]["next_key_date"] == date(2026, 8, 7)


def test_source_filter_separates_live_and_backfill(db, backfill_seed):
    only_bf = _fetch_bf(db, "RVBF01", source="backfill")
    assert [r["key_date"] for r in only_bf] == [date(2026, 6, 20)]
    only_weekend = _fetch_bf(db, "RVBF01", source="weekend")
    assert all(r["backfilled"] is False for r in only_weekend)
    assert {r["key_date"] for r in only_weekend} == {date(2026, 6, 16), date(2026, 8, 7)}


def test_build_spark_downsample_preserves_latest_price_off_grid():
    # 극점·마지막 인덱스가 균등 스텝 그리드와 우연히 겹치지 않는 소수 길이(157) 입력.
    # 다운샘플이 스텝 그리드만 쓰면 최신 가격(마지막 인덱스)이 드롭될 수 있다 — 반드시
    # 강제 포함돼야 한다(리뷰 지적: 최신 가격점 보존 회귀).
    vals = list(range(157))
    vals[13] = 9999.0    # 최고점
    vals[101] = -9999.0  # 최저점
    s = [(date.fromordinal(738000 + i), float(v)) for i, v in enumerate(vals)]
    spark = build_spark(s, s[0][0], s[-1][0], cap=60)
    assert len(spark) <= 60
    assert 9999.0 in spark and -9999.0 in spark
    assert spark[-1] == vals[-1]
