from datetime import date, timedelta
from datetime import date as date_cls
from freezegun import freeze_time
import pandas as pd
import pytest

from kr_pipeline.ohlcv.modes import compute_date_range, Mode


@freeze_time("2026-05-15")
def test_backfill_range_for_2_years():
    start, end = compute_date_range(Mode.BACKFILL, years=2)
    assert start == date(2024, 5, 15)
    assert end == date(2026, 5, 14)


@freeze_time("2026-05-15")
def test_incremental_range_for_30_days():
    start, end = compute_date_range(Mode.INCREMENTAL, window_days=30)
    assert start == date(2026, 4, 15)
    assert end == date(2026, 5, 15)


@freeze_time("2026-05-15")
def test_incremental_default_includes_today():
    """기본값: end=today (마감 후 cron 정확성 보존)."""
    _, end = compute_date_range(Mode.INCREMENTAL, window_days=30)
    assert end == date(2026, 5, 15)


@freeze_time("2026-05-15")
def test_incremental_exclude_today_ends_yesterday():
    """opt-in: exclude_today=True → end=어제 (장중 수동 실행 시 부분봉 회피). start 는 불변."""
    start, end = compute_date_range(Mode.INCREMENTAL, window_days=30, exclude_today=True)
    assert start == date(2026, 4, 15)
    assert end == date(2026, 5, 14)


@freeze_time("2026-05-15")
def test_exclude_today_noop_for_backfill():
    """BACKFILL/FULL 은 이미 end=어제 → exclude_today 가 영향 없음."""
    _, end_default = compute_date_range(Mode.BACKFILL, years=2)
    _, end_excl = compute_date_range(Mode.BACKFILL, years=2, exclude_today=True)
    assert end_default == end_excl == date(2026, 5, 14)


def test_full_refresh_range_uses_db_min(monkeypatch):
    from kr_pipeline.ohlcv import modes
    monkeypatch.setattr(modes, "_get_db_min_date", lambda conn: date(2024, 1, 2))

    with freeze_time("2026-05-15"):
        start, end = compute_date_range(Mode.FULL_REFRESH, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 14)


def test_sanity_checks_coverage_warning(db):
    """활성 종목 100개 중 50개만 최근 일봉 들어왔으면 경고."""
    from kr_pipeline.ohlcv.modes import _run_sanity_checks, Mode

    # 커버리지 계산은 전체 활성 종목/전체 MAX(date) 기반 — 다른 테스트가 commit 하고
    # 남긴 잔존 종목·일봉이 분모/기준일을 흔들지 않게 트랜잭션 안에서 중립화.
    # commit 하지 않으므로 픽스처 rollback 으로 전부 원복 (finally 정리 불필요).
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_prices")
        cur.execute("UPDATE stocks SET delisted_at = '2020-01-01' WHERE delisted_at IS NULL")
        # Seed: 100 active stocks
        for i in range(100):
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') "
                "ON CONFLICT (ticker) DO UPDATE SET delisted_at = NULL",
                (f"{i:06d}", f"종목{i}"),
            )
        # 50 stocks with daily_prices for 2026-05-14
        for i in range(50):
            cur.execute("""
                INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                VALUES (%s, '2026-05-14', 100, 100, 100, 100, 100, 100, 100)
                ON CONFLICT DO NOTHING
            """, (f"{i:06d}",))

    warnings = _run_sanity_checks(db, Mode.INCREMENTAL)
    coverage_warnings = [w for w in warnings if w.startswith("coverage_low")]
    assert len(coverage_warnings) == 1
    assert "50/100" in coverage_warnings[0]


def test_sanity_checks_no_warning_when_coverage_high(db):
    """80% 이상 커버리지면 경고 없음."""
    from kr_pipeline.ohlcv.modes import _run_sanity_checks, Mode

    # 위 테스트와 동일 — 잔존행 중립화 후 무-commit (픽스처 rollback 원복)
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_prices")
        cur.execute("UPDATE stocks SET delisted_at = '2020-01-01' WHERE delisted_at IS NULL")
        for i in range(100):
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') "
                "ON CONFLICT (ticker) DO UPDATE SET delisted_at = NULL",
                (f"{i:06d}", f"종목{i}"),
            )
        for i in range(90):
            cur.execute("""
                INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                VALUES (%s, '2026-05-14', 100, 100, 100, 100, 100, 100, 100)
                ON CONFLICT DO NOTHING
            """, (f"{i:06d}",))

    warnings = _run_sanity_checks(db, Mode.INCREMENTAL)
    coverage_warnings = [w for w in warnings if w.startswith("coverage_low")]
    assert coverage_warnings == []


def test_sanity_checks_bad_prices_warning(db):
    """close 또는 adj_close 가 0 이하인 행이 있으면 경고."""
    from kr_pipeline.ohlcv.modes import _run_sanity_checks, Mode

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('005930', '삼성', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("""
            INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
            VALUES ('005930', '2026-05-14', 70000, 71000, 69000, 0, 0, 1000, 1000)
            ON CONFLICT DO NOTHING
        """)
    db.commit()

    try:
        warnings = _run_sanity_checks(db, Mode.INCREMENTAL)
        bad_warnings = [w for w in warnings if w.startswith("bad_prices")]
        assert len(bad_warnings) == 1
        assert "1" in bad_warnings[0]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker = '005930'")
            cur.execute("DELETE FROM stocks WHERE ticker = '005930'")
        db.commit()


def test_sanity_checks_skips_coverage_for_full_refresh(db):
    """full-refresh 는 커버리지 검증을 건너뜀."""
    from kr_pipeline.ohlcv.modes import _run_sanity_checks, Mode

    with db.cursor() as cur:
        for i in range(10):
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
                (f"{i:06d}", f"종목{i}"),
            )
        # 0 stocks with daily_prices → would be 0% coverage in incremental
    db.commit()

    try:
        warnings = _run_sanity_checks(db, Mode.FULL_REFRESH)
        coverage_warnings = [w for w in warnings if w.startswith("coverage_low")]
        assert coverage_warnings == []
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker ~ '^[0-9]{6}$'")
            cur.execute("DELETE FROM stocks WHERE ticker ~ '^[0-9]{6}$'")
        db.commit()


# ====== P1-5 Part B: 빈 응답 계정(accounting) ======

def test_run_upsert_accounts_empty_fetches(monkeypatch, db):
    """빈 응답 종목이 성공도 실패도 아닌 상태로 소멸하지 않고 warnings 에 집계.

    과거 사고: backfill 시 KRX throttling 빈 응답 → 과거 미적재인데 failures=0
    으로 보고돼 607종목 누락이 무경고 통과.
    """
    from kr_pipeline.ohlcv import modes

    empty = pd.DataFrame()
    monkeypatch.setattr(
        modes, "fetch_raw_datewise",
        lambda tickers, s, e: ({t: empty for t in tickers}, []),
    )
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])

    stats = modes._run_upsert(
        db, ["EMA", "EMB", "EMC"], date(2026, 7, 1), date(2026, 7, 7), 2, modes.Mode.INCREMENTAL
    )
    joined = " ".join(stats.warnings)
    assert "empty_fetch" in joined, f"빈 응답이 warnings 에 없음: {stats.warnings}"
    assert "3/3" in joined and "EMA" in joined
    # 100% > 1% 임계 초과 — 강한 경고 문구 포함
    assert "%" in joined
    # 지수 빈 응답도 집계
    assert "empty_index" in joined


def test_run_upsert_no_empty_no_warning(monkeypatch, db):
    """빈 응답 0건이면 empty_fetch 경고 없음 (기존 동작 보존)."""
    from kr_pipeline.ohlcv import modes

    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tickers, s, e: ({}, []))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])

    stats = modes._run_upsert(db, [], date(2026, 7, 1), date(2026, 7, 7), 2, modes.Mode.INCREMENTAL)
    assert not any(w.startswith("empty_fetch") for w in stats.warnings)


def test_run_upsert_snapshot_gap_promoted_to_warning(monkeypatch, db):
    """스냅샷 결측 날짜(failures 의 snapshot:*)는 run warnings 로 승격 (#94 리뷰).

    창 중간 하루 차단이면 어떤 종목도 raw.empty 가 아니어서 empty_fetch 가
    못 잡는다 — P1-5(2026-06-10 조용한 누락)와 같은 계열이므로 경고 필수.
    """
    from kr_pipeline.ohlcv import modes

    monkeypatch.setattr(
        modes, "fetch_raw_datewise",
        lambda tickers, s, e: ({}, [("snapshot:2026-07-02", "blocked/empty response")]),
    )
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])

    stats = modes._run_upsert(
        db, [], date(2026, 7, 1), date(2026, 7, 7), 2, modes.Mode.INCREMENTAL)
    joined = " ".join(stats.warnings)
    assert "snapshot_gap" in joined and "2026-07-02" in joined


def test_run_upsert_datewise_halt_row_nullifies_adj(monkeypatch, db):
    """날짜별 수집 경로에서도 거래정지 행은 raw 0/종가 보존 + adj_* NULL (#94).

    스냅샷의 halt 계약(OHLV=0, close>0)이 merge_raw_and_adjusted →
    nullify_halt_adj chokepoint 를 그대로 통과하는지 DB 실물로 확인.
    """
    from kr_pipeline.ohlcv import modes

    raw = pd.DataFrame({
        "date": [date(2026, 7, 2)], "open": [0], "high": [0], "low": [0],
        "close": [5000], "volume": [0], "value": [0],
    })
    monkeypatch.setattr(
        modes, "fetch_raw_datewise",
        lambda tickers, s, e: ({"HLT": raw}, []),
    )
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('HLT', '정지주', 'KOSPI') "
            "ON CONFLICT (ticker) DO NOTHING")
        db.commit()

    modes._run_upsert(db, ["HLT"], date(2026, 7, 1), date(2026, 7, 7), 2, modes.Mode.INCREMENTAL)

    with db.cursor() as cur:
        cur.execute(
            "SELECT open, close, adj_close, adj_open, adj_volume FROM daily_prices "
            "WHERE ticker='HLT' AND date='2026-07-02'")
        row = cur.fetchone()
    assert row is not None
    o, c, adj_close, adj_open, adj_volume = row
    assert o == 0 and c == 5000            # raw halt 마커 보존
    assert adj_close is not None            # 종가는 유지
    assert adj_open is None and adj_volume is None  # OHLV → NULL


# ====== (#49) 수정 OHLC 봉 불변식 관측 (pykrx adjusted 반올림 유래, 관측 전용) ======

def _insert_price_row(cur, ticker, d, *, adj_close, adj_high, adj_low):
    cur.execute(
        "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
        (ticker, ticker),
    )
    cur.execute(
        """
        INSERT INTO daily_prices (ticker, date, open, high, low, close, volume, value,
                                  adj_close, adj_high, adj_low)
        VALUES (%s, %s, 10000, 10450, 9900, 10450, 1000, 1000, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (ticker, d, adj_close, adj_high, adj_low),
    )


def test_sanity_checks_adj_invariant_warning(db):
    """adj_close > adj_high 또는 adj_close < adj_low 행이 있으면 관측 경고 1건."""
    from kr_pipeline.ohlcv.modes import _run_sanity_checks, Mode
    from datetime import date as _date

    with db.cursor() as cur:
        # 재현 실측(#49): 299900@2021-03-22 고가 2612 < 종가 2613 (환산계수 0.25 반올림)
        _insert_price_row(cur, "INV1", _date(2021, 3, 22),
                          adj_close=2613, adj_high=2612, adj_low=2551)
        _insert_price_row(cur, "INV2", _date(2021, 3, 23),
                          adj_close=2500, adj_high=2612, adj_low=2551)  # close < low
    db.commit()

    try:
        warnings = _run_sanity_checks(db, Mode.FULL_REFRESH)
        inv = [w for w in warnings if w.startswith("adj_ohlc_invariant")]
        assert len(inv) == 1, f"관측 경고 1건이어야 함: {warnings}"
        assert "close>high 1" in inv[0] and "close<low 1" in inv[0]
        assert "2021-03-23" in inv[0]  # 최근 위반일
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker IN ('INV1','INV2')")
            cur.execute("DELETE FROM stocks WHERE ticker IN ('INV1','INV2')")
        db.commit()


def test_sanity_checks_no_adj_invariant_warning_when_clean(db):
    """불변식 위반 0행이면 경고 없음."""
    from kr_pipeline.ohlcv.modes import _run_sanity_checks, Mode
    from datetime import date as _date

    with db.cursor() as cur:
        _insert_price_row(cur, "INVOK", _date(2021, 3, 22),
                          adj_close=2612, adj_high=2612, adj_low=2551)
    db.commit()

    try:
        warnings = _run_sanity_checks(db, Mode.FULL_REFRESH)
        assert not any(w.startswith("adj_ohlc_invariant") for w in warnings)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker = 'INVOK'")
            cur.execute("DELETE FROM stocks WHERE ticker = 'INVOK'")
        db.commit()


def test_sanity_checks_adj_invariant_baseline_emphasis(db, monkeypatch):
    """실측 기준(baseline) 초과 시에만 강조 문구 — 소스 동작 변화 신호."""
    from kr_pipeline.ohlcv import modes
    from datetime import date as _date

    with db.cursor() as cur:
        _insert_price_row(cur, "INVB", _date(2021, 3, 22),
                          adj_close=2613, adj_high=2612, adj_low=2551)
    db.commit()

    try:
        monkeypatch.setattr(modes, "_ADJ_INVARIANT_BASELINE", 0)
        over = [w for w in modes._run_sanity_checks(db, modes.Mode.FULL_REFRESH)
                if w.startswith("adj_ohlc_invariant")]
        assert len(over) == 1 and "기준" in over[0] and "초과" in over[0]

        monkeypatch.setattr(modes, "_ADJ_INVARIANT_BASELINE", 21_541)
        under = [w for w in modes._run_sanity_checks(db, modes.Mode.FULL_REFRESH)
                 if w.startswith("adj_ohlc_invariant")]
        assert len(under) == 1 and "초과" not in under[0]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker = 'INVB'")
            cur.execute("DELETE FROM stocks WHERE ticker = 'INVB'")
        db.commit()


def test_sanity_checks_adj_invariant_recent_emphasis(db, monkeypatch):
    """최근 30일 위반이 임계 초과면 강조 — 절대 기준의 드리프트 사각을 보완.

    절대 기준(21,541)은 주간 재정규화로 카운트가 하향 드리프트해 여유가 계속
    늘어나므로, 신규 적재 위반은 최근 윈도우로 별도 감지한다 (리뷰 지적).
    """
    from kr_pipeline.ohlcv import modes
    from datetime import date as _date, timedelta

    recent_d = _date.today() - timedelta(days=5)
    old_d = _date(2021, 3, 22)

    with db.cursor() as cur:
        _insert_price_row(cur, "INVR", recent_d,
                          adj_close=2613, adj_high=2612, adj_low=2551)
    db.commit()
    try:
        monkeypatch.setattr(modes, "_ADJ_INVARIANT_RECENT_WARN", 0)
        w = [x for x in modes._run_sanity_checks(db, modes.Mode.FULL_REFRESH)
             if x.startswith("adj_ohlc_invariant")]
        assert len(w) == 1 and "최근 30일" in w[0] and "소스 동작 변화" in w[0]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker = 'INVR'")
            cur.execute("DELETE FROM stocks WHERE ticker = 'INVR'")
        db.commit()

    # 같은 위반이라도 오래된 날짜면 recent 강조 없음
    with db.cursor() as cur:
        _insert_price_row(cur, "INVR2", old_d,
                          adj_close=2613, adj_high=2612, adj_low=2551)
    db.commit()
    try:
        monkeypatch.setattr(modes, "_ADJ_INVARIANT_RECENT_WARN", 0)
        w = [x for x in modes._run_sanity_checks(db, modes.Mode.FULL_REFRESH)
             if x.startswith("adj_ohlc_invariant")]
        assert len(w) == 1 and "최근 30일" not in w[0]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker = 'INVR2'")
            cur.execute("DELETE FROM stocks WHERE ticker = 'INVR2'")
        db.commit()


# (#207 A안) test_run_upsert_empty_adj_held_with_warning_others_proceed 삭제 — Naver adj 경로 자체가 제거돼
#   '빈 adj 보류' 동작이 존재하지 않는다(raw 만 수집, adj = raw × F). 보류 설계(#95)는 레거시 fetch_many_datewise 에만 남음.


def _seed_prices(db, ticker, rows):
    """rows = [(date, close, adj_close)] — raw=close, change_pct NULL(시임 이전 Naver 이력 흉내)."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, 'A', 'KOSPI') ON CONFLICT DO NOTHING", (ticker,))
        for d, c, a in rows:
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1000, 1000, 1)", (ticker, d, c, c, c, c, a, a, a, a))


def test_run_upsert_derives_adj_from_events_and_records_new_event(monkeypatch, db):
    """증분 배치(raw+change_pct)에서 조정일(×8) 검출 → 배치 행 adj = raw×F, 이전 이력 소급 ×8, 이벤트 기록,
    stats.adjusted_tickers 에 종목. Naver 호출 없음."""
    from kr_pipeline.ohlcv import modes
    _seed_prices(db, "EVT", [(date(2026, 9, 21), 10000, 10000.0)])
    raw = pd.DataFrame({
        "date": [date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)],
        "open": [10100, 80000, 81000], "high": [10200, 81000, 82000], "low": [10000, 79000, 80000],
        "close": [10200, 80800, 81600], "volume": [1000, 100, 120], "value": [1, 1, 1],
        "change_pct": [2.0, 0.0, 0.99],   # 09-23: 10,200→80,800 with r=0 → 기준가 80,800 ≠ 10,200 → coef 7.9216
    })
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tickers, s, e: ({"EVT": raw}, []))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    stats = modes._run_upsert(db, ["EVT"], date(2026, 9, 22), date(2026, 9, 24), 2, modes.Mode.INCREMENTAL)
    assert stats.adjusted_tickers == ["EVT"]
    with db.cursor() as cur:
        cur.execute("SELECT date, close, adj_close, adj_volume FROM daily_prices WHERE ticker='EVT' ORDER BY 1")
        rows = [(d, float(c), round(float(a), 1), round(float(v), 2)) for d, c, a, v in cur.fetchall()]
    coef = 80800 / 10200
    assert rows == [(date(2026, 9, 21), 10000.0, round(10000 * coef, 1), round(1000 / coef, 2)),   # 이력 소급
                    (date(2026, 9, 22), 10200.0, round(10200 * coef, 1), round(1000 / coef, 2)),   # 배치, 조정일 전
                    (date(2026, 9, 23), 80800.0, 80800.0, 100.0), (date(2026, 9, 24), 81600.0, 81600.0, 120.0)]
    with db.cursor() as cur:
        cur.execute("SELECT date, coef FROM adj_factor_events WHERE ticker='EVT'")
        (d, c), = cur.fetchall(); assert d == date(2026, 9, 23) and float(c) == pytest.approx(coef, rel=1e-6)


def test_run_upsert_preserves_pre_seam_adj(monkeypatch, db):
    """ADJ_SELF_START(2026-09-14) 이전 행은 Naver 구정의 이력이 정본 — 재적재가 raw 컬럼만 갱신하고 adj_* 보존."""
    from kr_pipeline.ohlcv import modes
    from kr_pipeline.ohlcv.adjust import ADJ_SELF_START
    _seed_prices(db, "SEAM", [(date(2026, 9, 11), 1000, 500.0)])          # Naver 이력: adj 500(후행 분할 반영)
    raw = pd.DataFrame({"date": [date(2026, 9, 11), ADJ_SELF_START], "open": [1000, 1010], "high": [1000, 1010],
                        "low": [1000, 1010], "close": [1001, 1010], "volume": [1000, 1000], "value": [1, 1],
                        "change_pct": [0.1, 0.9]})
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tickers, s, e: ({"SEAM": raw}, []))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    stats = modes._run_upsert(db, ["SEAM"], date(2026, 9, 11), ADJ_SELF_START, 2, modes.Mode.INCREMENTAL)
    assert stats.adjusted_tickers == []
    with db.cursor() as cur:
        cur.execute("SELECT date, close, adj_close FROM daily_prices WHERE ticker='SEAM' ORDER BY 1")
        assert [(d, float(c), float(a)) for d, c, a in cur.fetchall()] == [
            (date(2026, 9, 11), 1001.0, 500.0),      # raw 갱신·adj 보존
            (ADJ_SELF_START, 1010.0, 1010.0)]        # 시임 이후 신규: adj = raw × F(=1)


# ---------- #207 A안: full-refresh = 시임 이후 행 raw × F 재유도(접촉 0) ----------

def test_full_refresh_rederives_post_seam_rows_from_raw_and_events(monkeypatch, db):
    """시임(ADJ_SELF_START) 이후 행: adj_* = raw × F(이벤트) 로 재유도. 시임 이전 행(Naver 이력) 불변. fetch 호출 0."""
    from kr_pipeline.ohlcv import modes, adjust
    import kr_pipeline.ohlcv.fetch as fetch_mod
    _seed_prices(db, "FR1", [(date(2026, 9, 11), 1000, 500.0), (date(2026, 9, 14), 1000, 999.0), (date(2026, 9, 15), 8000, 999.0)])
    with db.cursor() as cur:
        cur.execute("UPDATE daily_prices SET change_pct = 0.0 WHERE ticker='FR1'")
    adjust.record_events(db, "FR1", [(date(2026, 9, 15), 8.0)])
    assert not hasattr(fetch_mod, "fetch_adj_only")   # Naver 호출 가능 경로 자체가 없다
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    stats = modes._run_full_refresh(db, ["FR1"], date(2026, 1, 1), date(2026, 9, 30), 1)
    assert stats.failures == [] and stats.rows_affected == 2
    with db.cursor() as cur:
        cur.execute("SELECT date, adj_close, adj_volume FROM daily_prices WHERE ticker='FR1' ORDER BY 1")
        assert [(d, float(a), float(v)) for d, a, v in cur.fetchall()] == [
            (date(2026, 9, 11), 500.0, 1000.0),      # 시임 이전 불변
            (date(2026, 9, 14), 8000.0, 125.0),      # 1000 × 8, volume / 8
            (date(2026, 9, 15), 8000.0, 1000.0)]


def test_full_refresh_ticker_failure_isolated(monkeypatch, db):
    """한 종목 예외는 failures 기록 + rollback 후 다음 종목 계속. (종목 실패 시 conn.rollback() 이 테스트 시드까지
    되돌리므로 시드는 commit 하고 finally 에서 정리 — 구 Naver 테스트와 같은 관례.)"""
    from kr_pipeline.ohlcv import modes, adjust
    _seed_prices(db, "FR2", [(date(2026, 9, 14), 100, 100.0)])
    _seed_prices(db, "FR3", [(date(2026, 9, 14), 100, 100.0)])
    db.commit()
    orig = adjust.load_events
    monkeypatch.setattr(adjust, "load_events", lambda conn, t: (_ for _ in ()).throw(RuntimeError("boom")) if t == "FR2" else orig(conn, t))
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    try:
        stats = modes._run_full_refresh(db, ["FR2", "FR3"], date(2026, 1, 1), date(2026, 9, 30), 1)
        assert [t for t, _ in stats.failures] == ["FR2"] and stats.rows_affected == 1
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker IN ('FR2','FR3')")
            cur.execute("DELETE FROM stocks WHERE ticker IN ('FR2','FR3')")
        db.commit()


def test_run_upsert_event_within_naver_history_records_only(monkeypatch, db):
    """리뷰 2(배포 순서): ADJ_NAVER_HISTORY_THROUGH 이전 조정일이 라이브 첫 실행에서 '신규'로 보여도 시임 이전 이력은
    이미 소급돼 있으므로 기록만 하고 소급하지 않는다(이중 소급 방지). 시임 이후 행은 raw×F."""
    from kr_pipeline.ohlcv import modes
    _seed_prices(db, "STR", [(date(2026, 9, 10), 1000, 8000.0), (date(2026, 9, 11), 1000, 8000.0)])   # Naver 이력(×8 반영)
    raw = pd.DataFrame({
        "date": [date(2026, 9, 11), date(2026, 9, 14), date(2026, 9, 15)],
        "open": [1000, 1000, 8000], "high": [1000, 1000, 8000], "low": [1000, 1000, 8000],
        "close": [1000, 1000, 8000], "volume": [1000, 1000, 100], "value": [1, 1, 1], "change_pct": [0.0, 0.0, 0.0],
    })
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tickers, s, e: ({"STR": raw}, []))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    stats = modes._run_upsert(db, ["STR"], date(2026, 9, 11), date(2026, 9, 15), 2, modes.Mode.INCREMENTAL)
    assert stats.adjusted_tickers == ["STR"]
    with db.cursor() as cur:
        cur.execute("SELECT date, adj_close FROM daily_prices WHERE ticker='STR' ORDER BY 1")
        assert [(d, float(a)) for d, a in cur.fetchall()] == [
            (date(2026, 9, 10), 8000.0), (date(2026, 9, 11), 8000.0),   # 불변(이중 소급 없음)
            (date(2026, 9, 14), 8000.0), (date(2026, 9, 15), 8000.0)]
        cur.execute("SELECT count(*) FROM adj_factor_events WHERE ticker='STR'"); assert cur.fetchone()[0] == 1


def test_run_upsert_post_naver_event_rescales_pre_seam_including_freshly_inserted_row(monkeypatch, db):
    """리뷰 3·5: Naver 종료 이후 조정일 — 창이 시임을 걸치면 배치 안 시임 이전 행(보존 행 + 이번에 새로 INSERT 된 행)은
    정확히 1회 소급(계수², 누락 모두 금지), 배치에 없던 시임 이후 DB 행도 재유도."""
    from kr_pipeline.ohlcv import modes, adjust
    late = adjust.ADJ_NAVER_HISTORY_THROUGH + timedelta(days=7)
    _seed_prices(db, "STR2", [(date(2026, 9, 10), 1000, 1000.0), (date(2026, 9, 16), 1000, 1000.0)])   # 09-16: 배치에 없는 시임 이후 행
    raw = pd.DataFrame({
        "date": [date(2026, 9, 11), date(2026, 9, 15), late],          # 09-11: DB 에 없던 시임 이전 행(신규 INSERT)
        "open": [1000, 1000, 8000], "high": [1000, 1000, 8000], "low": [1000, 1000, 8000],
        "close": [1000, 1000, 8000], "volume": [1000, 1000, 100], "value": [1, 1, 1], "change_pct": [0.0, 0.0, 0.0],
    })
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tickers, s, e: ({"STR2": raw}, []))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    modes._run_upsert(db, ["STR2"], date(2026, 9, 11), late, 2, modes.Mode.INCREMENTAL)
    with db.cursor() as cur:
        cur.execute("SELECT date, adj_close FROM daily_prices WHERE ticker='STR2' ORDER BY 1")
        assert [(d, float(a)) for d, a in cur.fetchall()] == [
            (date(2026, 9, 10), 8000.0), (date(2026, 9, 11), 8000.0),   # 보존 행·신규 INSERT 행 모두 ×8 정확히 1회
            (date(2026, 9, 15), 8000.0), (date(2026, 9, 16), 8000.0),   # 배치 행·배치에 없던 DB 행 모두 재유도
            (late, 8000.0)]


def test_run_upsert_skips_event_judgment_when_prior_day_snapshot_blocked(monkeypatch, db):
    """리뷰 1: 직전 거래일 스냅샷이 차단(failures 'snapshot:D')이면 그 다음 날 행의 조정일 판정을 보류 — 2일 수익률 오판 방지."""
    from kr_pipeline.ohlcv import modes
    _seed_prices(db, "BLK", [(date(2026, 9, 21), 10000, 10000.0)])
    raw = pd.DataFrame({"date": [date(2026, 9, 23)], "open": [10500], "high": [10500], "low": [10500], "close": [10500],
                        "volume": [1000], "value": [1], "change_pct": [1.94]})    # 09-22 결측(차단), r 은 09-22 대비
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tickers, s, e: ({"BLK": raw}, [("snapshot:2026-09-22", "blocked/empty response")]))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    stats = modes._run_upsert(db, ["BLK"], date(2026, 9, 22), date(2026, 9, 23), 2, modes.Mode.INCREMENTAL)
    assert stats.adjusted_tickers == []
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM adj_factor_events WHERE ticker='BLK'"); assert cur.fetchone()[0] == 0


def test_run_upsert_ignores_pre_seam_adjustment_days(monkeypatch, db):
    """창 안 시임 이전 조정일(예: 09-03 ×8)은 Naver 이력이 이미 소급 반영 → 신규 이벤트로 보면 이중 적용.
    시임 이전 날짜는 판정·기록·소급 대상이 아니다."""
    from kr_pipeline.ohlcv import modes
    _seed_prices(db, "PRE", [(date(2026, 9, 2), 1000, 8000.0)])   # Naver 이력: 09-03 ×8 이미 반영
    raw = pd.DataFrame({
        "date": [date(2026, 9, 3), date(2026, 9, 14)],
        "open": [8000, 8100], "high": [8000, 8100], "low": [8000, 8100], "close": [8000, 8100],
        "volume": [100, 100], "value": [1, 1], "change_pct": [0.0, 1.25],
    })
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tickers, s, e: ({"PRE": raw}, []))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    stats = modes._run_upsert(db, ["PRE"], date(2026, 9, 3), date(2026, 9, 14), 2, modes.Mode.INCREMENTAL)
    assert stats.adjusted_tickers == []
    with db.cursor() as cur:
        cur.execute("SELECT date, adj_close FROM daily_prices WHERE ticker='PRE' ORDER BY 1")
        assert [(d, float(a)) for d, a in cur.fetchall()] == [(date(2026, 9, 2), 8000.0), (date(2026, 9, 3), 8000.0), (date(2026, 9, 14), 8100.0)]
        cur.execute("SELECT count(*) FROM adj_factor_events WHERE ticker='PRE'")
        assert cur.fetchone()[0] == 0
