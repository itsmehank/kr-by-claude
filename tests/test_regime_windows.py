"""#207 회신 21 Q-5c 2 — 판정 창(일봉 50/주봉 W+1/앵커~평가) 날짜로 volume_regime_flag 유도."""
from datetime import date, timedelta

from kr_pipeline.common.data_regimes import FLAG_MIXED, VOLUME_REGIME_BOUNDARY as B
from kr_pipeline.common.regime_windows import (
    DAILY_WINDOW_MAX_CAL_DAYS, WEEKLY_WINDOW_MAX_CAL_DAYS, classification_flag, daily_window_flag, entry_window_flag,
    range_flag_from_week_ends, weekly_window_flag,
)


def _seed_daily(db, ticker, dates):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) VALUES (%s,%s,1,1,1,1,1,1,1)",
                        [(ticker, d) for d in dates])


def _seed_weekly(db, ticker, week_ends, zero_bar_weeks=()):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days) "
                        "VALUES (%s,%s,%s,%s,%s,1,1,%s,1,5)",
                        [(ticker, d, 0 if d in zero_bar_weeks else 1, 0 if d in zero_bar_weeks else 1, 0 if d in zero_bar_weeks else 1,
                          0 if d in zero_bar_weeks else 1) for d in week_ends])


def _weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_daily_window_flag_mixed_only_while_window_straddles_boundary(db):
    days = _weekdays(B - timedelta(days=120), 140)          # 경계 전후 넉넉히
    _seed_daily(db, "RWD1", days)
    before = [d for d in days if d < B]
    after = [d for d in days if d >= B]
    assert daily_window_flag(db, "RWD1", before[-1]) is None                  # 경계 전: clean(DB 0)
    assert daily_window_flag(db, "RWD1", after[0]) == "mixed"                 # 경계 당일: 49 regular + 1 extended
    assert daily_window_flag(db, "RWD1", after[48]) == "mixed"                # 50번째 봉 직전까지 mixed
    assert daily_window_flag(db, "RWD1", after[49]) is None                   # 경계 + 50봉: 전부 extended → new → NULL(자연 만료)


def test_daily_window_flag_with_fewer_bars_than_window(db):
    days = _weekdays(B - timedelta(days=5), 6)                                # 봉 6개뿐(신규 상장)
    _seed_daily(db, "RWD2", days)
    assert daily_window_flag(db, "RWD2", days[-1]) == "mixed"
    assert daily_window_flag(db, "RWD2", days[0]) is None


def test_weekly_window_flag_and_zero_bar_weeks_excluded(db):
    fridays = [date(2025, 10, 3) + timedelta(weeks=i) for i in range(60)]     # 금요일 60주(2025-10 ~ 2026-11)
    last_before = max(f for f in fridays if f < B)
    first_after = min(f for f in fridays if f >= B)
    _seed_weekly(db, "RWW1", fridays)
    assert weekly_window_flag(db, "RWW1", last_before) is None
    assert weekly_window_flag(db, "RWW1", first_after) == "mixed"
    # zero-bar(거래정지) 주는 산술(_fetch_weekly_full)과 같이 제외 — 창 51주가 할트 주로 채워져도 경계 전 실제 주를 본다
    post = [f for f in fridays if f >= B]
    _seed_weekly(db, "RWW2", fridays, zero_bar_weeks=set(post[1:]))
    assert weekly_window_flag(db, "RWW2", post[-1], n=2) == "mixed"            # 비할트 최근 2주 = (경계 전 주, 경계 첫 주)
    _seed_weekly(db, "RWW3", fridays)
    assert weekly_window_flag(db, "RWW3", post[-1], n=2) is None               # 할트 없으면 최근 2주 모두 extended


def test_range_flag_from_week_ends_is_pure():
    fridays = [date(2026, 8, 7) + timedelta(weeks=i) for i in range(12)]      # 08-07 ~ 10-23
    after = [f for f in fridays if f >= B]
    assert range_flag_from_week_ends(fridays, None) is None                    # 앵커 없음
    assert range_flag_from_week_ends([f.isoformat() for f in fridays], "2026-08-21") == "mixed"
    assert range_flag_from_week_ends(fridays, after[0]) is None                # 앵커 = 경계 첫 주 → 전부 extended
    assert range_flag_from_week_ends([], "2026-08-21") is None                 # 창 비어 있음


def test_flags_short_circuit_without_db_before_boundary_and_after_cap(db, monkeypatch):
    """as_of < 경계(전부 regular) 또는 경계 + 상한 초과(전부 extended)면 DB 를 읽지 않는다."""
    import kr_pipeline.common.regime_windows as rw
    monkeypatch.setattr(rw, "price_source", lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB 접근 금지")))
    d = B - timedelta(days=1)
    assert daily_window_flag(db, "ANY", d) is None and weekly_window_flag(db, "ANY", d) is None
    assert classification_flag(db, "ANY", d, anchor_week="2026-08-07") is None and entry_window_flag(db, "ANY", d) is None
    far = B + timedelta(days=WEEKLY_WINDOW_MAX_CAL_DAYS + 1)
    assert daily_window_flag(db, "ANY", B + timedelta(days=DAILY_WINDOW_MAX_CAL_DAYS + 1)) is None
    assert weekly_window_flag(db, "ANY", far) is None
    assert classification_flag(db, "ANY", far, anchor_week=far.isoformat()) is None   # 앵커 ≥ 경계·앵커 끝 C3 창도 상한 초과 → 조회 불요
    # 앵커 기준 창은 상한 없음(리뷰 #222 3차): 경계 전 앵커면 상한을 아무리 넘겨도 순수 유도로 mixed(DB 0)
    assert classification_flag(db, "ANY", far, anchor_week="2026-08-07") == FLAG_MIXED


def test_flags_fail_soft_conservative_mixed_and_keep_transaction_usable(db, monkeypatch, caplog):
    """서버측 SQL 오류(psycopg.Error)가 본 INSERT 를 막으면 안 된다(store #39) — SAVEPOINT 격리. 값은 보수 'mixed'(오류 ≠ 깨끗함).
    프로그래밍 오류(TypeError 등)는 삼키지 않고 전파(리뷰 #222 3차)."""
    import logging
    import pytest
    import kr_pipeline.common.regime_windows as rw
    from kr_pipeline.common.price_source import PriceSource
    monkeypatch.setattr(rw, "price_source", lambda *a, **k: PriceSource("no_such_table_x", "no_such_table_y", "", "", False))
    with caplog.at_level(logging.WARNING, logger="kr_pipeline.common.regime_windows"):
        assert daily_window_flag(db, "RWX1", B) == FLAG_MIXED
        assert classification_flag(db, "RWX1", B) == FLAG_MIXED
    assert "regime_window_flag_failed" in caplog.text
    with db.cursor() as cur:                                   # 트랜잭션 오염 없음
        cur.execute("SELECT 1"); assert cur.fetchone()[0] == 1
    monkeypatch.setattr(rw, "price_source", lambda *a, **k: (_ for _ in ()).throw(TypeError("programming error")))
    with pytest.raises(TypeError):
        daily_window_flag(db, "RWX1", B)


def test_classification_flag_combines_daily_weekly_and_anchor_range(db):
    days = _weekdays(B - timedelta(days=10), 52)                               # 일간 창(마지막 50봉): 경계 걸침
    _seed_daily(db, "RWJ1", days)
    fridays = [B + timedelta(days=4) + timedelta(weeks=i) for i in range(3)]   # 주간 창: 전부 extended
    _seed_weekly(db, "RWJ1", fridays)
    as_of = days[-1]
    assert classification_flag(db, "RWJ1", as_of) == "mixed"
    assert weekly_window_flag(db, "RWJ1", as_of) is None
    # 앵커 구간: 일간·주간 창이 만료돼도 앵커가 경계 전이면 T2/P2 입력이 혼재 → mixed(리뷰 #222 2차)
    days2 = _weekdays(B - timedelta(days=200), 240)
    _seed_daily(db, "RWJ2", days2)
    fridays2 = [date(2025, 10, 3) + timedelta(weeks=i) for i in range(110)]     # ~2027-11
    _seed_weekly(db, "RWJ2", fridays2)
    late = max(f for f in fridays2 if f <= B + timedelta(days=200))              # 경계 + ~200일(일간 창 만료, 주간 51주는 아직 걸침)
    assert daily_window_flag(db, "RWJ2", late) is None
    assert classification_flag(db, "RWJ2", late, anchor_week=None) == "mixed"    # 주간 51주 창은 아직 mixed
    far = max(f for f in fridays2 if f <= B + timedelta(days=370))               # ~2027-10: 일간·주간 고정 창 모두 만료
    assert weekly_window_flag(db, "RWJ2", far) is None
    assert classification_flag(db, "RWJ2", far, anchor_week=None) is None
    assert classification_flag(db, "RWJ2", far, anchor_week="2026-08-07") == "mixed"      # 앵커~평가 주(경계 전 앵커)
    # 앵커에서 끝나는 C3 창(앵커 적격 판정 분모): 앵커 2026-12-04(extended) 의 51주 창은 2025-12~ → 경계 걸침(리뷰 #222 3차)
    assert classification_flag(db, "RWJ2", far, anchor_week="2026-12-04") == "mixed"
    late_anchor = max(f for f in fridays2 if f <= B + timedelta(days=365))        # 2027-09: 51주 창이 경계 이후로만 → NULL
    assert classification_flag(db, "RWJ2", far, anchor_week=late_anchor.isoformat()) is None


def test_classification_anchor_range_uses_last_weekly_bar_not_as_of(db):
    """앵커~평가 창의 우측 끝 = 집계의 MAX(week_end_date)(find_anchor 가 본 마지막 주). as_of 가 수요일 09-30 이고 주봉이 09-25 까지만
    있으면 T2/P2 는 regular 주만 봤으므로 NULL — as_of 달력 주(extended)로 판정하면 오표지(리뷰 #222 4차)."""
    days = _weekdays(B - timedelta(days=120), 80)                                # 일봉: 전부 경계 전
    days = [d for d in days if d < B]
    _seed_daily(db, "RWA1", days)
    fridays = [date(2025, 10, 3) + timedelta(weeks=i) for i in range(52) if date(2025, 10, 3) + timedelta(weeks=i) < B]   # ≤ 09-25
    _seed_weekly(db, "RWA1", fridays)
    as_of = B + timedelta(days=2)                                                 # 수요일 09-30
    assert classification_flag(db, "RWA1", as_of, anchor_week="2026-08-07") is None


def test_guarded_returns_conservative_when_connection_already_in_error(db, caplog):
    """선행 문 실패로 연결이 INERROR 면 SAVEPOINT 를 열지 않고 보수값 — psycopg 트랜잭션 카운터 누수 없이 호출자 rollback 이 동작(4차)."""
    import logging, psycopg
    with db.cursor() as cur:
        try:
            cur.execute("SELECT 1/0")
        except psycopg.Error:
            pass
    assert db.info.transaction_status == psycopg.pq.TransactionStatus.INERROR
    with caplog.at_level(logging.WARNING, logger="kr_pipeline.common.regime_windows"):
        assert daily_window_flag(db, "ANY", B) == FLAG_MIXED
    assert "INERROR" in caplog.text
    db.rollback()                                                                 # 카운터 누수 시 ProgrammingError
    with db.cursor() as cur:
        cur.execute("SELECT 1"); assert cur.fetchone()[0] == 1


def test_entry_window_flag_covers_pocket_pivot_lookback(db):
    """진입 창: pocket_pivot 분기는 관측 비율이 PP 일(최근 5세션 중 최신)에서 끝나는 50봉 창 — as_of 창 + 4봉을 더 보아 보수적(mixed 쪽)."""
    days = _weekdays(B - timedelta(days=200), 240)
    _seed_daily(db, "RWE1", days)
    after = [d for d in days if d >= B]
    assert daily_window_flag(db, "RWE1", after[49]) is None                    # as_of 50봉 창은 만료
    assert entry_window_flag(db, "RWE1", after[49]) == "mixed"                 # PP 일이 4봉 전이면 그 창은 아직 걸침
    assert entry_window_flag(db, "RWE1", after[53]) == "mixed"                 # 할트 여유(10행)까지 보수적으로 유지
    assert entry_window_flag(db, "RWE1", after[63]) is None                    # +4봉 +10행 뒤 만료
