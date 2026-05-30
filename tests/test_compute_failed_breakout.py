"""2-F failed_breakout — K=5 + 지속성 (spec §5)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from kr_pipeline.llm_runner.compute.failed_breakout import compute_failed_breakout


def _seed_close(db, ticker, start: date, closes: list[float]):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
            (ticker, ticker),
        )
        d = start
        for c in closes:
            cur.execute(
                """
                INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                """,
                (ticker, d, c, c, c, c, c, 1000, 1000 * c),
            )
            d += timedelta(days=1)


def test_p1_consecutive_below_fires(db):
    """D0 돌파 후 연속 2일 pivot 아래 → P1 발화."""
    start = date(2026, 1, 5)
    pivot = 100.0
    # D0=101(돌파), D1=98, D2=97 (연속 2일 아래), D3=102, D4=103, D5=104
    _seed_close(db, "FBP1", start, [101, 98, 97, 102, 103, 104])
    r = compute_failed_breakout(db, "FBP1", datetime(2026, 1, 15, tzinfo=timezone.utc), pivot, start)
    assert r is not None and r["fired"]
    assert r["trigger"] in ("P1", "both")
    assert r["consecutive_below"] >= 2


def test_p2_never_recovers_fires(db):
    """D0 돌파 후 D1~D5 한 번도 pivot 회복 못 함 → P2 발화."""
    start = date(2026, 2, 2)
    pivot = 100.0
    # D0=101, 이후 5일 모두 pivot 아래지만 연속성은 P1 도 충족 → both
    _seed_close(db, "FBP2", start, [101, 99, 98, 99, 98, 99])
    r = compute_failed_breakout(db, "FBP2", datetime(2026, 2, 12, tzinfo=timezone.utc), pivot, start)
    assert r is not None and r["fired"]
    assert r["trigger"] in ("P2", "both")


def test_throwback_single_day_not_fired(db):
    """D1 하루만 아래 후 회복 → throwback, 미발화."""
    start = date(2026, 3, 2)
    pivot = 100.0
    # D0=101, D1=99 (하루만 아래), D2=102, D3=103, D4=104, D5=105
    _seed_close(db, "FBTHROW", start, [101, 99, 102, 103, 104, 105])
    r = compute_failed_breakout(db, "FBTHROW", datetime(2026, 3, 12, tzinfo=timezone.utc), pivot, start)
    assert r is None, "단일일 throwback 은 미발화"


def test_no_breakout_returns_none(db):
    """돌파 자체가 없으면 None."""
    start = date(2026, 4, 1)
    pivot = 100.0
    _seed_close(db, "FBNONE", start, [90, 91, 92, 93, 94, 95])
    r = compute_failed_breakout(db, "FBNONE", datetime(2026, 4, 11, tzinfo=timezone.utc), pivot, start)
    assert r is None


def test_d0_limited_to_base_start_window(db):
    """과거(base_start 이전) 의 돌파+실패는 무시 — 이번 base 의 D0 만 평가.

    버그 회귀: 전체 역사에서 D0 를 찾으면 과거의 무관한 돌파를 잡는다.
    """
    # 과거 구간: D0'=101 후 연속 하락 (이게 잡히면 버그). 그 뒤 가격이 한참 횡보.
    # 이번 base: base_start 부터는 돌파가 *없음* (모두 pivot 아래) → None 이어야.
    early = date(2026, 5, 1)
    # 과거 6봉 (5/1~5/6): 돌파 후 실패 패턴 (이게 잡히면 버그).
    past = [101, 98, 97, 96, 95, 94]
    # 이번 base 6봉 (5/7~5/12): 전부 pivot(100) 아래 → 돌파 없음.
    recent = [90, 91, 92, 93, 94, 95]
    _seed_close(db, "FBPAST", early, past + recent)
    base_start = early + timedelta(days=len(past))      # 5/7 = recent[0]
    classified = datetime(2026, 5, 13, tzinfo=timezone.utc)  # 12봉 모두 이전
    r = compute_failed_breakout(db, "FBPAST", classified, 100.0, base_start)
    assert r is None, "base_start 이후 돌파 없음 → 과거 돌파 무시하고 None"


def test_base_start_none_returns_none(db):
    """base_start_date NULL → 범위 한정 불가 → None."""
    start = date(2026, 6, 1)
    _seed_close(db, "FBNOBASE", start, [101, 98, 97, 102, 103, 104])
    r = compute_failed_breakout(db, "FBNOBASE", datetime(2026, 6, 15, tzinfo=timezone.utc), 100.0, None)
    assert r is None
