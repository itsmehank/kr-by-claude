# tests/test_corporate_actions_modes.py
from datetime import date, timedelta
from freezegun import freeze_time

from kr_pipeline.corporate_actions.modes import Mode, compute_date_range


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.REFRESH_MAPPING.value == "refresh-mapping"


@freeze_time("2026-05-17")
def test_backfill_5_years_range():
    start, end = compute_date_range(Mode.BACKFILL, years=5)
    assert end == date(2026, 5, 17)
    assert start == date(2021, 5, 18)   # today - 5y = today - 5*365 일


@freeze_time("2026-05-17")
def test_incremental_window_7_days():
    start, end = compute_date_range(Mode.INCREMENTAL, window_days=7)
    assert end == date(2026, 5, 17)
    assert start == date(2026, 5, 10)


@freeze_time("2026-05-17")
def test_refresh_mapping_mode():
    """refresh-mapping 은 날짜 범위 안 씀."""
    # compute_date_range 가 호출되지 않거나 None 반환
    # 우리 정의: refresh-mapping 일 때 (None, None) 반환
    start, end = compute_date_range(Mode.REFRESH_MAPPING)
    assert start is None and end is None


def test_date_chunks_splits_long_range():
    """일괄 조회의 페이지 폭주 방지 — 긴 기간을 90일 청크로 분할, 빈틈·중복 없음."""
    from kr_pipeline.corporate_actions.modes import _date_chunks

    chunks = list(_date_chunks(date(2024, 1, 1), date(2024, 12, 31), days=90))
    assert chunks[0][0] == date(2024, 1, 1)
    assert chunks[-1][1] == date(2024, 12, 31)
    # 연속성: 다음 청크 시작 = 직전 청크 끝 + 1일
    for (s1, e1), (s2, _e2) in zip(chunks, chunks[1:]):
        assert (e1 - s1).days <= 89
        assert s2 == e1 + timedelta(days=1)
    # 366일(윤년) / 90 → 5청크
    assert len(chunks) == 5


def test_date_chunks_short_range_single_chunk():
    """7일 창 → 청크 1개 (incremental 은 호출 1회)."""
    from kr_pipeline.corporate_actions.modes import _date_chunks

    chunks = list(_date_chunks(date(2026, 5, 10), date(2026, 5, 17), days=90))
    assert chunks == [(date(2026, 5, 10), date(2026, 5, 17))]
