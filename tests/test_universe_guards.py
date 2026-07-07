"""P1-5 Part A: universe 빈/부족 응답 가드 — 대량 오폐지 방어.

배경: KRX throttling 은 예외가 아니라 '빈 리스트' 로 나타날 수 있다(ohlcv 에서
기관찰). fetch_tickers 가 빈 리스트를 정상 반환하면 mark_delisted 가 그 시장
전 종목(~1,700개)을 일괄 폐지 처리하고, 월 1회 cron 까지 자가치유도 없다.
"""
from datetime import date

import pytest


# ---------- 가드 1: fetch_tickers 시장별 최소 종목 수 ----------

def test_fetch_tickers_raises_on_suspiciously_small_list(mocker):
    """빈/비정상적으로 적은 목록 → ValueError (with_retry 가 재시도 후 전파).

    가드를 fetch_tickers '내부' 에 두는 이유: @with_retry 는 모든 예외를
    백오프 재시도하므로, 일시적 throttle 빈 응답은 자동 회복 기회를 얻고
    지속 실패만 전파된다.
    """
    import kr_pipeline.universe.fetch as uf

    stock_mock = mocker.patch.object(uf, "stock")
    stock_mock.get_market_ticker_list.return_value = []

    with pytest.raises(ValueError, match="KOSDAQ"):
        uf.fetch_tickers("KOSDAQ", date(2026, 7, 7))
    # with_retry(attempts=3) — 재시도가 실제로 이뤄졌는지
    assert stock_mock.get_market_ticker_list.call_count == 3


def test_fetch_tickers_passes_on_normal_count(mocker):
    """정상 규모 목록은 그대로 반환."""
    import kr_pipeline.universe.fetch as uf

    tickers = [f"{i:06d}" for i in range(900)]  # KOSPI 하한(700) 이상
    stock_mock = mocker.patch.object(uf, "stock")
    stock_mock.get_market_ticker_list.return_value = tickers

    assert uf.fetch_tickers("KOSPI", date(2026, 7, 7)) == tickers
    assert stock_mock.get_market_ticker_list.call_count == 1


# ---------- 가드 2: mark_delisted 폐지 비율 상한 ----------

def _insert_active(cur, prefix, n):
    for i in range(n):
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') "
            "ON CONFLICT (ticker) DO UPDATE SET delisted_at = NULL",
            (f"{prefix}{i:03d}", "가드테스트"),
        )


def _active_tickers(cur):
    cur.execute("SELECT ticker FROM stocks WHERE delisted_at IS NULL")
    return {r[0] for r in cur.fetchall()}


def test_mark_delisted_aborts_on_mass_delist(db):
    """활성 종목의 2% 초과를 한 번에 폐지하려 하면 UPDATE 전에 abort.

    kr_test 잔존 데이터와 무관하게: 현재 활성 집합을 조회해 그중 10% 를
    '목록에서 누락' 시켜 구성 — 고정 숫자 baseline 에 의존하지 않는다.
    """
    from kr_pipeline.universe.store import mark_delisted

    with db.cursor() as cur:
        _insert_active(cur, "GRD", 60)  # 활성 최소 규모 보장
        active = _active_tickers(cur)
    db.commit()

    drop_n = max(int(len(active) * 0.10), 2)  # 10% 누락 → 상한(2%) 초과
    dropped = set(list(active)[:drop_n])
    current = active - dropped

    try:
        with pytest.raises(ValueError, match="delist"):
            mark_delisted(db, current_tickers=current, on_date=date(2026, 7, 7))
        db.rollback()
        with db.cursor() as cur:
            after = _active_tickers(cur)
        assert after == active, "abort 인데 일부가 폐지 처리됨 (fail-closed 깨짐)"
    finally:
        # 실패 경로(예: 가드 미구현 red 단계)에서 mass delist 가 실제 실행된 채
        # 정리 commit 에 묻어가는 것 방지 — 반드시 rollback 후 정리만 commit.
        db.rollback()
        with db.cursor() as cur:
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'GRD%' AND name='가드테스트'")
        db.commit()


def test_mark_delisted_normal_small_delist_still_works(db):
    """정상 소량 폐지(상한 이하)는 기존 동작 그대로."""
    from kr_pipeline.universe.store import mark_delisted

    with db.cursor() as cur:
        _insert_active(cur, "GRD", 60)
        active = _active_tickers(cur)
    db.commit()

    victim = "GRD000"
    current = active - {victim}  # 1건 폐지 — 활성 60+ 의 2% 미만

    try:
        n = mark_delisted(db, current_tickers=current, on_date=date(2026, 7, 7))
        db.commit()
        assert n == 1
        with db.cursor() as cur:
            cur.execute("SELECT delisted_at FROM stocks WHERE ticker = %s", (victim,))
            assert cur.fetchone()[0] is not None
    finally:
        # 실패 경로의 잔여 변경이 정리 commit 에 묻어가지 않게 rollback 선행
        db.rollback()
        with db.cursor() as cur:
            cur.execute("DELETE FROM stocks WHERE ticker LIKE 'GRD%' AND name='가드테스트'")
        db.commit()


def test_mark_delisted_empty_set_still_noop(db):
    """기존 가드 보존: current_tickers 완전 빈 집합 → no-op (0건)."""
    from kr_pipeline.universe.store import mark_delisted

    assert mark_delisted(db, current_tickers=set(), on_date=date(2026, 7, 7)) == 0
