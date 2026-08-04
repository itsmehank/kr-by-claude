from datetime import date, datetime
import pandas as pd
import pytest

import kr_pipeline.common.trading_calendar as tc


def _patch_fetch(monkeypatch, days, *, raises=False):
    def fake(index_code, start, end):
        if raises:
            raise RuntimeError("KRX timeout")
        return pd.DataFrame({"date": list(days), "close": [1] * len(days)})
    monkeypatch.setattr(tc, "fetch_index", fake)


def test_eltd_today_after_buffer(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 8), date(2026, 6, 9), date(2026, 6, 10)])
    assert tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0)) == date(2026, 6, 10)


def test_eltd_today_before_buffer(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 8), date(2026, 6, 9), date(2026, 6, 10)])
    assert tc.expected_latest_trading_day(datetime(2026, 6, 10, 11, 0)) == date(2026, 6, 9)


def test_eltd_holiday(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 4), date(2026, 6, 5)])
    assert tc.expected_latest_trading_day(datetime(2026, 6, 6, 18, 0)) == date(2026, 6, 5)


def test_unavailable_on_empty(monkeypatch):
    monkeypatch.setattr(tc, "fetch_index", lambda *a, **k: pd.DataFrame())
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0))


def test_unavailable_on_exception(monkeypatch):
    _patch_fetch(monkeypatch, [], raises=True)
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0))


def test_assert_fresh_passes(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    tc.assert_data_fresh(date(2026, 6, 10), datetime(2026, 6, 10, 18, 0))


def test_assert_fresh_stale_raises(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    with pytest.raises(tc.StaleDataError):
        tc.assert_data_fresh(date(2026, 6, 9), datetime(2026, 6, 10, 18, 0))


def test_assert_fresh_calendar_unavailable_propagates(monkeypatch):
    _patch_fetch(monkeypatch, [], raises=True)
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.assert_data_fresh(date(2026, 6, 10), datetime(2026, 6, 10, 18, 0))


# ─── #92 ELTD 파일 캐시 ────────────────────────────────────────────

def test_cache_key_distinguishes_close_buffer():
    """17시 경계로 키가 갈린다 — CLOSE_BUFFER=17:00 때문에 답이 다르다."""
    assert tc.cache_key(datetime(2026, 6, 10, 16, 59)).endswith(":pre")
    assert tc.cache_key(datetime(2026, 6, 10, 17, 0)).endswith(":post")
    assert tc.cache_key(datetime(2026, 6, 10, 17, 0)).startswith("2026-06-10")


def test_expected_latest_writes_cache(monkeypatch):
    """라이브 조회 성공 시 캐시에 쓴다."""
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    now = datetime(2026, 6, 10, 18, 0)
    assert tc.expected_latest_trading_day(now) == date(2026, 6, 10)
    assert tc.cached_eltd(now) == date(2026, 6, 10)


def test_cached_eltd_never_calls_live(monkeypatch):
    """cached_eltd 는 캐시 미스여도 라이브를 부르지 않는다."""

    def boom(*a, **k):
        raise AssertionError("cached_eltd 가 라이브를 호출했다")

    monkeypatch.setattr(tc, "fetch_index", boom)
    assert tc.cached_eltd(datetime(2026, 6, 10, 18, 0)) is None


def test_failure_is_not_cached(monkeypatch):
    """실패는 캐시하지 않는다 — negative 캐시는 fail-closed 체인을 마비시킨다."""
    _patch_fetch(monkeypatch, [], raises=True)
    now = datetime(2026, 6, 10, 18, 0)
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.expected_latest_trading_day(now)
    assert tc.cached_eltd(now) is None
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    assert tc.expected_latest_trading_day(now) == date(2026, 6, 10)


def test_cache_io_failure_degrades_to_live(monkeypatch, tmp_path):
    """캐시 경로가 쓸 수 없어도 라이브 조회 결과를 정상 반환한다(fail-closed 보호).

    Path.mkdir 전역 패치로 하지 않는다 — 클래스 전역 패치라 같은 테스트 안의
    모든 mkdir 을 깨뜨리는 지뢰가 된다. 실제 권한 없는 디렉터리를 쓴다.
    """
    ro = tmp_path / "ro"
    ro.mkdir(mode=0o500)
    try:
        monkeypatch.setenv("ELTD_CACHE", str(ro / "sub" / "eltd.cache"))
        _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
        assert tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0)) == date(2026, 6, 10)
    finally:
        ro.chmod(0o700)


def test_corrupt_cache_self_heals(monkeypatch, tmp_path):
    """비-UTF8 로 손상된 캐시도 다음 쓰기에서 복구된다.

    _write_cache 가 기존 내용 읽기를 안쪽 try 로 감싸지 않으면 UnicodeDecodeError 가
    바깥 except 로 빠져 쓰기 자체가 실행되지 않고 캐시가 영구 손상 상태로 남는다.
    그러면 감시의 결측 판정이 죽는다.
    """
    p = tmp_path / "eltd.cache"
    p.write_bytes(b"\xff\xfe bad\n")
    monkeypatch.setenv("ELTD_CACHE", str(p))
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    now = datetime(2026, 6, 10, 18, 0)
    assert tc.expected_latest_trading_day(now) == date(2026, 6, 10)
    assert tc.cached_eltd(now) == date(2026, 6, 10), "손상 캐시가 자기치유되지 않았다"


def test_assert_fresh_uses_cache_without_live_call(monkeypatch):
    """캐시가 있으면 assert_data_fresh 가 라이브를 부르지 않는다(결정 1)."""
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    now = datetime(2026, 6, 10, 18, 0)
    tc.expected_latest_trading_day(now)          # 캐시 채우기(라이브 1회)

    def boom(*a, **k):
        raise AssertionError("assert_data_fresh 가 라이브를 호출했다")

    monkeypatch.setattr(tc, "fetch_index", boom)
    tc.assert_data_fresh(date(2026, 6, 10), now)              # 통과해야 함
    with pytest.raises(tc.StaleDataError):
        tc.assert_data_fresh(date(2026, 6, 9), now)           # 판정력 유지


def test_assert_fresh_falls_back_to_live_on_cache_miss(monkeypatch):
    """캐시가 없으면 라이브로 폴백한다 — fail-closed 유지."""
    _patch_fetch(monkeypatch, [], raises=True)
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.assert_data_fresh(date(2026, 6, 10), datetime(2026, 6, 10, 18, 0))


def test_write_cache_keeps_newest_entry_last(monkeypatch, tmp_path):
    """'마지막 줄 = 최신 항목' 계약 — 감시(bash)의 tail -1 이 이 계약에 의존한다.

    _write_cache 를 정렬/prepend 로 바꾸면 감시가 과거 날짜를 조용히 반환한다(3차 검토).
    """
    p = tmp_path / "eltd.cache"
    monkeypatch.setenv("ELTD_CACHE", str(p))
    tc._write_cache(datetime(2026, 6, 9, 18, 0), date(2026, 6, 9))
    tc._write_cache(datetime(2026, 6, 10, 18, 0), date(2026, 6, 10))
    lines = p.read_text().splitlines()
    assert lines[-1] == "2026-06-10:post|2026-06-10", f"마지막 줄이 최신이 아니다: {lines}"
    # 같은 키 재기록도 마지막 줄이 새 값이어야 한다
    tc._write_cache(datetime(2026, 6, 10, 18, 0), date(2026, 6, 11))
    lines = p.read_text().splitlines()
    assert lines[-1] == "2026-06-10:post|2026-06-11"
    assert len([ln for ln in lines if ln.startswith("2026-06-10:post|")]) == 1


def test_cached_eltd_skips_corrupt_line_and_uses_valid_one(monkeypatch, tmp_path):
    """같은 키의 손상 줄이 뒤에 있어도 앞의 유효 줄을 살린다(3차 검토 — 조기 abort 금지)."""
    p = tmp_path / "eltd.cache"
    p.write_text("2026-06-10:post|2026-06-10\n2026-06-10:post|NOTADATE\n")
    monkeypatch.setenv("ELTD_CACHE", str(p))
    assert tc.cached_eltd(datetime(2026, 6, 10, 18, 0)) == date(2026, 6, 10)
