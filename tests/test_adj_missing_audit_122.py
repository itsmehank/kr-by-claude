"""#122 pykrx×DART 대조 — 순수 함수 테스트 (참조 adj 조정 누락 검출)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from kr_pipeline.ohlcv.adj_missing_audit import (
    contamination_window, expected_events, match_expected,
)


def _dates(start: date, n: int) -> list[date]:
    """월~금만 n개 — 거래일 근사."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _closes(dates: list[date], price: float = 100.0):
    return [(d, price) for d in dates]


# ---- expected_events -------------------------------------------------------

def test_fric_event_ex_date_is_trading_day_before_record_date():
    dates = _dates(date(2023, 2, 1), 40)
    # 221800 실제: 기준일 2023-02-24(금) → 권리락일 02-23(목), 1주당 3주 → 배율 0.25
    det = [{"endpoint": "fricDecsn", "record_date": date(2023, 2, 24),
            "ratio": 3.0, "method": None, "rcept_no": "20230209000353"}]
    ev = expected_events(dates, det)
    assert ev == [(date(2023, 2, 23), pytest.approx(0.25), "fric", "20230209000353")]


def test_piic_only_shareholder_allocation_and_marked_approx():
    dates = _dates(date(2024, 1, 1), 40)
    det = [
        {"endpoint": "piicDecsn", "record_date": date(2024, 1, 15), "ratio": 0.2,
         "method": "주주배정후 실권주 일반공모", "rcept_no": "a"},
        {"endpoint": "piicDecsn", "record_date": date(2024, 1, 22), "ratio": 0.2,
         "method": "제3자배정증자", "rcept_no": "b"},
    ]
    ev = expected_events(dates, det)
    assert [e[3] for e in ev] == ["a"]
    assert ev[0][2] == "piic"
    assert ev[0][1] is None            # 배율 미지(발행가 의존) — 존재만 검사


def test_cr_event_ratio_is_inverse_of_reduction():
    dates = _dates(date(2024, 3, 1), 40)
    det = [{"endpoint": "crDecsn", "record_date": date(2024, 3, 20),
            "ratio": 0.9, "method": "보통주 10주를 1주로 병합", "rcept_no": "c"}]
    (ex, r, kind, _), = expected_events(dates, det)
    assert kind == "cr" and ex == date(2024, 3, 19)
    assert r == pytest.approx(10.0)    # 1/(1-0.9)


def test_stkdp_year_end_record_date_uses_two_trading_days_before():
    dates = _dates(date(2023, 12, 1), 30)      # 12-29(금)이 마지막 거래일 가정
    dates = [d for d in dates if d <= date(2023, 12, 29)] + _dates(date(2024, 1, 2), 5)
    det = [{"endpoint": "stkdpDecsn", "record_date": date(2023, 12, 31),
            "ratio": 0.05, "method": None, "rcept_no": "20231101000001"}]
    (ex, r, kind, _), = expected_events(dates, det)
    assert kind == "stkdp"
    assert ex == date(2023, 12, 28)            # 폐장일(12-29) 직전 거래일
    assert r == pytest.approx(1 / 1.05)


def test_stkdp_filed_after_record_date_is_skipped():
    dates = _dates(date(2023, 12, 1), 30)
    det = [{"endpoint": "stkdpDecsn", "record_date": date(2023, 12, 15),
            "ratio": 0.05, "method": None, "rcept_no": "20240105000001"}]
    assert expected_events(dates, det) == []


def test_duplicate_record_dates_within_14_days_keep_latest_filing():
    dates = _dates(date(2024, 5, 1), 40)
    det = [
        {"endpoint": "fricDecsn", "record_date": date(2024, 5, 20), "ratio": 1.0,
         "method": None, "rcept_no": "20240501000001"},
        {"endpoint": "fricDecsn", "record_date": date(2024, 5, 27), "ratio": 1.0,
         "method": None, "rcept_no": "20240510000001"},   # 기준일 변경 정정
    ]
    ev = expected_events(dates, det)
    assert len(ev) == 1 and ev[0][3] == "20240510000001"


def test_record_date_outside_price_range_is_skipped():
    dates = _dates(date(2024, 5, 1), 10)
    det = [{"endpoint": "fricDecsn", "record_date": date(2020, 1, 10), "ratio": 1.0,
            "method": None, "rcept_no": "x"}]
    assert expected_events(dates, det) == []


# ---- match_expected ----------------------------------------------------------

def test_match_exact_kind_requires_size_within_tolerance():
    ex = date(2023, 2, 23)
    jumps = [(date(2023, 2, 23), 0.25)]
    assert match_expected(ex, 0.25, "fric", jumps) == "matched"
    assert match_expected(ex, 0.25, "fric", [(ex, 0.5)]) == "size_mismatch"
    assert match_expected(ex, 0.25, "fric", []) == "missing"
    assert match_expected(ex, 0.25, "fric", [(ex + timedelta(days=30), 0.25)]) == "missing"


def test_match_tolerates_a_few_calendar_days_shift():
    ex = date(2023, 2, 23)
    assert match_expected(ex, 0.25, "fric", [(ex + timedelta(days=4), 0.25)]) == "matched"


def test_match_approx_kind_checks_presence_only():
    ex = date(2024, 1, 12)
    assert match_expected(ex, None, "piic", [(ex, 0.93)]) == "matched"
    assert match_expected(ex, None, "piic", []) == "missing"


# ---- contamination_window ----------------------------------------------------

def test_contamination_window_counts_pass_days_inside_380d_window():
    ex = date(2023, 2, 23)
    passes = {ex + timedelta(days=10): True, ex + timedelta(days=100): False,
              ex + timedelta(days=379): True, ex + timedelta(days=381): True,
              ex - timedelta(days=1): True}
    w = contamination_window(ex, passes)
    assert w == {"window_end": date(2024, 3, 9), "window_days": 3,
                 "window_pass_days": 2, "total_pass_days": 4}


# ---- 감자 지연 창 · raw 갭 확인 ---------------------------------------------

def test_match_cr_allows_delayed_jump_up_to_90_days():
    # 감자: 기준일 후 구주권 제출·정지 → 재개일에 조정(#114 9차 ④, p95 84일)
    ex = date(2024, 2, 23)
    assert match_expected(ex, 4.0, "cr", [(ex + timedelta(days=60), 4.0)]) == "matched"
    assert match_expected(ex, 4.0, "cr", [(ex + timedelta(days=100), 4.0)]) == "missing"
    assert match_expected(ex, 4.0, "cr", [(ex - timedelta(days=10), 4.0)]) == "missing"


def test_raw_gap_confirms_large_event_without_adj_jump():
    from kr_pipeline.ohlcv.adj_missing_audit import raw_gap_evidence
    dates = _dates(date(2023, 2, 1), 40)
    ex = date(2023, 2, 23)
    closes = [(d, 1000.0 if d < ex else 250.0) for d in dates]   # 1:3 무상 — raw 1/4
    ev = raw_gap_evidence(closes, ex, 0.25, "fric")
    assert ev == {"evidence": "raw_gap_confirmed", "gap_date": ex.isoformat(),
                  "raw_gap": pytest.approx(0.25)}


def test_raw_gap_absent_when_price_continuous():
    from kr_pipeline.ohlcv.adj_missing_audit import raw_gap_evidence
    dates = _dates(date(2023, 2, 1), 40)
    closes = _closes(dates)
    ev = raw_gap_evidence(closes, date(2023, 2, 23), 0.25, "fric")
    assert ev["evidence"] == "raw_gap_absent" and ev["gap_date"] is None


def test_raw_gap_not_applicable_for_small_or_approx_events():
    from kr_pipeline.ohlcv.adj_missing_audit import raw_gap_evidence
    dates = _dates(date(2023, 2, 1), 40)
    closes = _closes(dates)
    assert raw_gap_evidence(closes, date(2023, 2, 23), 0.98, "stkdp")["evidence"] == "n/a"
    assert raw_gap_evidence(closes, date(2023, 2, 23), None, "piic")["evidence"] == "n/a"


def test_raw_gap_for_cr_searches_delayed_window():
    from kr_pipeline.ohlcv.adj_missing_audit import raw_gap_evidence
    dates = _dates(date(2024, 1, 1), 120)
    ex = date(2024, 2, 23)
    jump_day = dates[dates.index(ex) + 30]
    closes = [(d, 100.0 if d < jump_day else 400.0) for d in dates]  # 4:1 병합형 감자
    ev = raw_gap_evidence(closes, ex, 4.0, "cr")
    assert ev["evidence"] == "raw_gap_confirmed" and ev["gap_date"] == jump_day.isoformat()


# ---- 감자 의미 한정(병합만) · 큰 점프만 · raw 갭 자체 크기 ------------------

def test_cr_only_share_consolidation_is_price_affecting():
    dates = _dates(date(2024, 1, 1), 200)
    # 기준일을 30일씩 띄워 ±14일 정정 클러스터 병합을 피한다
    mk = lambda i, m, rc: {"endpoint": "crDecsn", "ratio": 0.9, "method": m,  # noqa: E731
                           "record_date": date(2024, 1, 20) + timedelta(days=30 * i),
                           "rcept_no": rc}
    det = [mk(0, "자기주식 소각", "a"), mk(1, "액면금액 감소(5,000원->500원)", "b"),
           mk(2, "기명식 보통주 10주를 동일한 액면주식 1주로 무상병합", "c"),
           mk(3, "5:1 감자( 모든 주주 동일)", "d"), mk(4, "차등감자", "e")]
    assert sorted(e[3] for e in expected_events(dates, det)) == ["c", "d"]


def test_match_cr_ignores_small_jumps_and_uses_loose_size_tolerance():
    ex = date(2024, 2, 23)
    # 자사주 소각 등으로 생기는 1% 미만 점프는 감자 조정이 아님
    assert match_expected(ex, 10.0, "cr", [(ex + timedelta(days=20), 1.01)]) == "missing"
    # cr_rt_ostk 는 단주·차등 때문에 근사 — 1.5 배 안이면 matched
    assert match_expected(ex, 10.0, "cr", [(ex + timedelta(days=20), 7.0)]) == "matched"
    assert match_expected(ex, 10.0, "cr", [(ex + timedelta(days=20), 2.0)]) == "size_mismatch"


def test_raw_gap_itself_must_be_large():
    from kr_pipeline.ohlcv.adj_missing_audit import raw_gap_evidence
    dates = _dates(date(2024, 1, 1), 60)
    ex = date(2024, 2, 1)
    # 기대 1.27(27% 감소)인데 raw 는 +1.5% 일변동뿐 — 허용 오차 안이라도 갭 아님
    closes = [(d, 100.0 if d < ex else 101.5) for d in dates]
    assert raw_gap_evidence(closes, ex, 1.27, "cr")["evidence"] == "raw_gap_absent"


# ---- 거래정지 중 권리락: 재개일까지 창 연장 --------------------------------

def test_resume_offset_measures_flat_price_span_from_ex_date():
    from kr_pipeline.ohlcv.adj_missing_audit import resume_offset
    dates = _dates(date(2017, 11, 20), 40)
    ex = date(2017, 12, 5)
    resume = dates[dates.index(ex) + 10]
    closes = [(d, 7580.0 if d < resume else 17100.0) for d in dates]   # 정지: 종가 고정
    assert resume_offset(closes, ex) == (resume - ex).days
    moving = [(d, 100.0 + i) for i, d in enumerate(dates)]            # 정상 거래
    assert resume_offset(moving, ex) == 0
    assert resume_offset([], ex) == 0


def test_match_window_extends_by_extra_days_for_halts():
    ex = date(2017, 12, 5)
    jumps = [(ex + timedelta(days=14), 2.533)]   # 감자 5:1 × 무상 1:1 복합, 재개일 조정
    assert match_expected(ex, 0.5, "fric", jumps) == "missing"
    assert match_expected(ex, 0.5, "fric", jumps, extra_days=14) == "size_mismatch"


def test_raw_gap_window_extends_by_extra_days():
    from kr_pipeline.ohlcv.adj_missing_audit import raw_gap_evidence
    dates = _dates(date(2017, 11, 20), 40)
    ex = date(2017, 12, 5)
    resume = dates[dates.index(ex) + 10]
    closes = [(d, 1000.0 if d < resume else 500.0) for d in dates]
    assert raw_gap_evidence(closes, ex, 0.5, "fric")["evidence"] == "raw_gap_absent"
    ev = raw_gap_evidence(closes, ex, 0.5, "fric", extra_days=(resume - ex).days)
    assert ev["evidence"] == "raw_gap_confirmed" and ev["gap_date"] == resume.isoformat()


def test_cr_counts_jumps_of_ten_percent_or_more():
    ex = date(2024, 1, 19)
    # 043590 실측: 4주→3주 병합, 참조 점프 1.22 (기대 1.33) — 조정 있음
    assert match_expected(ex, 1.3333, "cr", [(ex, 1.22)]) == "matched"
    assert match_expected(ex, 1.3333, "cr", [(ex, 1.05)]) == "missing"


# ---- 리뷰 R1 반영: 휴장 vs 정지, 미래 기준일, 감자 부분 병합, 결측 필드 ---------

def test_holiday_gap_keeps_previous_trading_day_as_ex_date():
    # 049080 실측: 기준일 2017-10-08(일), 추석 휴장 09-30~10-09 → 권리락 09-29
    market = [d for d in _dates(date(2017, 9, 1), 60)
              if not (date(2017, 9, 30) <= d <= date(2017, 10, 9))]
    det = [{"endpoint": "fricDecsn", "record_date": date(2017, 10, 8), "ratio": 1.0,
            "method": None, "rcept_no": "x"}]
    (ex, *_), = expected_events(market, det, market_dates=market)
    assert ex == date(2017, 9, 29)


def test_trading_halt_moves_ex_date_to_resume_day_when_market_was_open():
    market = _dates(date(2024, 1, 1), 60)
    ex_expected = market[30]
    ticker_dates = market[:20] + market[30:]          # 10 거래일 결측 = 정지
    det = [{"endpoint": "fricDecsn", "record_date": market[25], "ratio": 1.0,
            "method": None, "rcept_no": "x"}]
    (ex, *_), = expected_events(ticker_dates, det, market_dates=market)
    assert ex == ex_expected


def test_record_date_after_last_price_is_skipped_as_pending():
    dates = _dates(date(2026, 9, 1), 40)
    det = [{"endpoint": "fricDecsn", "record_date": dates[-1] + timedelta(days=3),
            "ratio": 1.0, "method": None, "rcept_no": "x"}]
    assert expected_events(dates, det) == []


def test_is_pending_when_match_window_exceeds_last_price_date():
    from kr_pipeline.ohlcv.adj_missing_audit import is_pending
    last = date(2026, 10, 30)
    assert is_pending(date(2026, 10, 28), "fric", last) is True       # +5일 창 미완
    assert is_pending(date(2026, 10, 20), "fric", last) is False
    assert is_pending(date(2026, 9, 1), "cr", last) is True           # +90일 창 미완
    assert is_pending(date(2026, 10, 20), "fric", last, extra_days=30) is True


@pytest.mark.parametrize("method", [
    "(주)디에이치오토리드 대상으로 2025년 2월 3일 채권변제 출자전환된 보통주 21,154,625주에 대하여 9:1 병합",
    "채권단 보유주식 및 자사주에 대하여 2:1 주식병합(무상감자)",
    "최대주주 한국공작기계(주) 보유주식 4,028,000주에 대해 보통주 3주를 보통주 1주로 병합",
    "출자전환으로 발행하는 신주에 대하여 5주를 1주로 병합",
    "분할과 동시에 10주를 1주로 병합 — 주식수 변동 없음",
    "차등감자: 대주주 등은 10:1",
    "케이에스에프선박금융 보유 1주를 제외한 주식 1주당 액면 감액",
])
def test_cr_partial_or_non_price_consolidations_are_excluded(method):
    from kr_pipeline.ohlcv.adj_missing_audit import cr_is_consolidation
    assert cr_is_consolidation(method) is False


@pytest.mark.parametrize("method", [
    "제1차 자본감소 및 회생담보권과 회생채권의 출자전환 후, 잔여 주식 전체를 대상으로 보통주 4주를 1주로 병합",
    "기존주식 및 회생채권의 출자전환으로 발행된 신주를 대상으로 보통주 각 3주를 보통주 각 1주로 병합",
    "기명식 보통주 15주를 동일한 액면주식 1주로 무상병합",
    "10:1 주식병합\n(액면가액 500원의 기명식 보통주식 10주를 같은 액면주식 1주로 무상감자)",
])
def test_cr_all_shareholder_consolidations_are_included(method):
    from kr_pipeline.ohlcv.adj_missing_audit import cr_is_consolidation
    assert cr_is_consolidation(method) is True


def test_missing_or_invalid_fields_are_skipped_without_error():
    dates = _dates(date(2024, 1, 1), 60)
    rd = date(2024, 2, 1)
    det = [
        {"endpoint": "crDecsn", "record_date": rd, "ratio": None, "method": "5:1 병합", "rcept_no": "a"},
        {"endpoint": "crDecsn", "record_date": rd, "ratio": 1.2, "method": "5:1 병합", "rcept_no": "b"},
        {"endpoint": "piicDecsn", "record_date": rd, "ratio": 0.1, "method": None, "rcept_no": "c"},
        {"endpoint": "fricDecsn", "record_date": rd, "ratio": None, "method": None, "rcept_no": "d"},
        {"endpoint": "pifricDecsn", "record_date": rd, "ratio": None, "method": None, "rcept_no": "e"},
    ]
    assert expected_events(dates, det) == []
