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


# DB 원문 그대로(개행 포함) 고정 — 리뷰 R1 ④·R2 ①②⑥
_CR_EXCLUDED = [
    "(주)디에이치오토리드 대상으로 2025년 2월 3일 채권변제 출자전환된 보통주 21,154,625주에 대하여 9:1 병합\n-주식 병합시 발생하는 1주 미만의 단주는 회생계획에 따라 무상 소각",
    "채권단 보유주식 및 자사주에 대하여 \n2:1 주식병합(무상감자)",
    "- 최대주주 한국공작기계(주) 보유주식 4,028,000주, 특수관계자인 일흥금속(주) 보유주식 285,587주, 대표이사 류흥목 보유주식 12,386주에 대해 각 각 액면가 500원의 보통주 3주를 액면가 500원의 보통주 1주로 병합\n\n- 일반주주는 감자 해당없음",
    "최대주주 및 채권단의 주식은 기명식 보통주 2주를 동일한 액면주식 1주로 무상병합. (소액주주[자사주 포함] 및 우선주는 감자대상에서 제외)",
    "출자전환으로 발행하는 신주에 대하여 5주를 1주로 병합",
    "1주의 액면금액 500원의 보통주식 2주를 동일 액면금액의 보통주식 1주로 무상 병합합니다. 단. 무상병합되는 주식대상은 대주주 지분 26,000,000주에 대해서만 무상 병합합니다.",
    "분할과 동시에 10주를 1주로 병합 — 주식수 변동 없음",
    "차등감자: 대주주 등은 10:1",
    "케이에스에프선박금융(주) 보유주식 1주를 제외한 투자자의 주식 전부 소각,소각대금 지급액은 1주당 5,000원",
    "주식병합\n(출자전환주식만 병합, 기존주주 제외)",          # 007280 (R3 ①)
    "자기주식 소각", "액면금액 감소(5,000원->500원)",
]
_CR_ALL_HOLDERS = [
    "제1차 자본감소 및 회생담보권과 회생채권의 출자전환 후, 잔여 주식 전체를 대상으로 액면가 500원의 보통주 4주를 액면가 500원의 보통주 1주로 병합합니다.",
    "기존주식 및 회생담보권, 회생채권의 출자전환으로 발행된 신주를 대상(미발생구상채권 등이 확정되어 출자전환 되는 경우도 병합 대상에 포함)으로 주식 병합을 실시합니다. 주식 병합비율은 기존주식 보통주 각 3주를 보통주 각 1주로 병합하고",
    "기명식 보통주 15주를 동일한 액면주식 1주로 무상병합",
    "10:1 주식병합\n(액면가액 500원의 기명식 보통주식 10주를 같은 액면주식 1주로 무상감자)",
    # 054220 — 단서 조항에 특수관계/최대주주가 나와도 '잔여 주식 전체'·'인가 전 발행 주식' 대상 = 전체 주주(R2 ①)
    "병합된 기존 주식 및 회생채권에서 출자전환된 신주 등 잔여 주식 전체를 대상(미발생구상채권 등이 확정되어 출자전환되는 경우도 재병합 대상에 포함)으로 액면가 500원의 보통주 35주를 액면가 500원의 보통주 1주로 재병합합니다.\n다만, 회생채권(특수관계인채권)의 출자전환된 주식은 액면가 500원의 보통주 350주를 액면가 500원의 보통주 1주로 병합합니",
    "회생계획안에 대한 인가 전에 발행한\n52,295,547주(액면가 500원)에 대하여는 액면가 500원의 보통주 2주를 액면가 500원의 보통주 1주로 병합합니다.\n최대주주인 (주)비츠로지에이치가 보유한 보통주 3,556,187주(액면가 500원)의 경우 보유주식 전체를 무상소각합니다.\n단, 주식의 병합 및 소각으로 인하여 발생하는 1주 미만의 단주는 관리인",
]
# 차등감자인데 기타주주도 병합 — 참조는 조정하지만 소액주주 비율은 미파싱 → 존재만 검사(R2 ②)
_CR_DIFFERENTIAL = [
    "주식병합방식의 차등감자\n(최대주주 특수관계인 오세영 주식은 보통주 2주를 1주로 병합, 그 외 주주 주식은 보통주 1.5주를 1주로 병합)",
    "차등감자\n(대주주 등은 100:1, 기타주주는 2:1)",
    "- 최대주주와 기타주주간에 차등감자\n- 최대주주 KC그린홀딩스 주식회사 소유주식 26,948,235 주 전부에 대하여는 임의/무상 소각하여 감자\n- 기타주주 보유주식 37,266,094주에 대하여 액면가 500 원의 기명식 보통주 2주를 액면가 500 원의 기명식 보통주 1주로 병합하여 감자 (2:1)",
    "액면가 500원의 보통주식에 대하여\n1. 최대주주가 감자전 보유하는 10,590,000주는 감자 후 353,000주로(감자비율 30:1)\n2. 그외 주주들이 보유하는 보통주식 48,581,967주는 감자 후 2,429,098주로(감자비율 20:1) 병합하는 차등무상감자.",
]


@pytest.mark.parametrize("method", _CR_EXCLUDED)
def test_cr_partial_or_non_price_consolidations_are_excluded(method):
    from kr_pipeline.ohlcv.adj_missing_audit import cr_class
    assert cr_class(method) is None


@pytest.mark.parametrize("method", _CR_ALL_HOLDERS)
def test_cr_all_shareholder_consolidations_are_included(method):
    from kr_pipeline.ohlcv.adj_missing_audit import cr_class
    assert cr_class(method) == "all"


@pytest.mark.parametrize("method", _CR_DIFFERENTIAL)
def test_cr_differential_with_minority_consolidation_is_presence_only(method):
    from kr_pipeline.ohlcv.adj_missing_audit import cr_class
    assert cr_class(method) == "diff"


def test_cr_differential_event_has_no_expected_ratio_and_checks_presence():
    dates = _dates(date(2024, 6, 1), 120)
    det = [{"endpoint": "crDecsn", "record_date": date(2024, 6, 26), "ratio": 0.705,
            "method": _CR_DIFFERENTIAL[1], "rcept_no": "x"}]
    (ex, r, kind, _), = expected_events(dates, det)
    assert kind == "cr_diff" and r is None and ex == date(2024, 6, 25)
    # 009410 실측: 2024-07-12 factor 2.0 → 존재만으로 matched, 소형 점프는 무시
    assert match_expected(ex, None, "cr_diff", [(date(2024, 7, 12), 2.0)]) == "matched"
    assert match_expected(ex, None, "cr_diff", [(date(2024, 7, 12), 1.02)]) == "missing"


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


# ---- positive_control_verdict ---------------------------------------------
# 양성 대조군(검출기가 반드시 찾아야 하는 기지 누락 3건)은 #122 재적재 후 matched 로 바뀐다.
# 재적재 기록(adj_factor_events)이 있으면 matched 로 *평가돼 있어야* 통과(평가 누락·비-matched 는 실패),
# 기록이 없으면 missing_confirmed 로 검출돼야 통과. 기록 없이 사라지면(검출기 결함 가능) 실패.

from kr_pipeline.ohlcv.adj_missing_audit import positive_control_verdict  # noqa: E402

_C = (("221800", "2023-02-23"), ("232830", "2020-09-04"), ("388610", "2023-07-24"))


def test_control_detected_as_missing_passes():
    v = positive_control_verdict(_C, confirmed_keys=set(_C), matched_keys=set(), repaired_keys=set())
    assert v["ok"] is True
    assert sorted(v["detected"]) == sorted(list(k) for k in _C)
    assert v["repaired"] == []


def test_control_repaired_and_matched_passes():
    v = positive_control_verdict(_C, confirmed_keys=set(), matched_keys=set(_C), repaired_keys=set(_C))
    assert v["ok"] is True
    assert v["detected"] == []
    assert sorted(v["repaired"]) == sorted(list(k) for k in _C)


def test_control_matched_without_repair_fails():
    repaired = set(_C) - {("388610", "2023-07-24")}
    v = positive_control_verdict(_C, confirmed_keys=set(), matched_keys=set(_C), repaired_keys=repaired)
    assert v["ok"] is False
    assert v["failed"] == [["388610", "2023-07-24"]]


def test_control_repaired_but_not_evaluated_fails():
    # 상폐·시세 없음·상세 없음·expected_events 회귀로 평가 자체가 빠진 경우 — 부재 검사로는 통과하던 구멍
    v = positive_control_verdict(_C, confirmed_keys=set(), matched_keys=set(), repaired_keys=set(_C))
    assert v["ok"] is False
    assert sorted(v["failed"]) == sorted(list(k) for k in _C)


def test_control_repaired_but_still_nonmatched_fails():
    bad = ("232830", "2020-09-04")
    v = positive_control_verdict(_C, confirmed_keys=set(), matched_keys=set(_C) - {bad},
                                 repaired_keys=set(_C))
    assert v["ok"] is False
    assert v["failed"] == [list(bad)]


def test_control_repaired_but_still_missing_confirmed_fails():
    # 기록은 있는데 여전히 missing_confirmed = DB 불일치(apply 실패 등) — 기록이 우선, 검출로 통과시키지 않음
    v = positive_control_verdict(_C, confirmed_keys=set(_C), matched_keys=set(), repaired_keys=set(_C))
    assert v["ok"] is False
    assert sorted(v["failed"]) == sorted(list(k) for k in _C)


# ---- (#122 후속) 병합 감자 + 액면분할 상쇄 — 2단 규칙 -----------------------------
# 1단: 분할 동반 증거(감자 method 문구 / 같은 기간 주식분할 공시). 2단: 창 안 raw 갭이 1.0 근방이면
# 상쇄, 큰 갭이 남으면 비율 상이(예 병합 10:1 + 분할 1:5 = 순 ×2) → 미확정으로 남긴다.

def test_split_evidence_from_cr_method_text():
    from kr_pipeline.ohlcv.adj_missing_audit import split_evidence
    ex = date(2026, 5, 2)
    m = "1) 액면금액 5,000원의 보통주식 1주를 액면금액 500원의 보통주식 10주로 주식분할 함.\n2) 주식분할과 동시에 10주를 1주로 무상병합 함."
    assert split_evidence(m, [], ex) == "method_text"
    assert split_evidence("보통주식 5주를 병합하여 같은 액면주식 1주로 병합", [], ex) is None
    assert split_evidence(None, [], ex) is None


def test_split_evidence_from_split_disclosures_in_window():
    from kr_pipeline.ohlcv.adj_missing_audit import split_evidence
    ex = date(2019, 10, 18)
    assert split_evidence("5주를 1주로 병합", [date(2019, 8, 23)], ex) == "disclosure"      # −56일
    assert split_evidence("5주를 1주로 병합", [date(2019, 12, 20)], ex) == "disclosure"     # +63일 ≤ 90
    assert split_evidence("5주를 1주로 병합", [date(2018, 1, 1)], ex) is None               # 창 밖
    assert split_evidence("5주를 1주로 병합", [date(2020, 2, 1)], ex, extra_days=30) == "disclosure"  # +106 ≤ 90+30


def test_max_abs_gap_in_cr_window():
    from kr_pipeline.ohlcv.adj_missing_audit import max_abs_gap
    dates = _dates(date(2019, 10, 1), 80)
    ex = dates[13]
    closes = [(d, 1000.0) for d in dates]
    assert max_abs_gap(closes, ex) is None or max_abs_gap(closes, ex)[1] == 1.0
    k = 16
    closes = [(d, 1000.0 if i < k else 5000.0) for i, d in enumerate(dates)]   # ex+3거래일 ×5
    d, g = max_abs_gap(closes, ex)
    assert d == dates[k] and abs(g - 5.0) < 1e-9
    assert max_abs_gap(closes, dates[60]) is None or max_abs_gap(closes, dates[60])[1] == 1.0  # 창 밖 점프 비포함


def test_split_offset_status_two_stage():
    from kr_pipeline.ohlcv.adj_missing_audit import split_offset_status
    g_small, g_big = (date(2019, 10, 21), 1.03), (date(2019, 10, 21), 2.0)
    assert split_offset_status("missing_unconfirmed", None, g_small) == "missing_unconfirmed"
    assert split_offset_status("missing_unconfirmed", "method_text", None) == "offset_by_split"
    assert split_offset_status("missing_unconfirmed", "disclosure", g_small) == "offset_by_split"
    assert split_offset_status("missing_unconfirmed", "disclosure", g_big) == "split_accompanied_unconfirmed"
    assert split_offset_status("size_mismatch", "disclosure", g_big) == "split_accompanied_unconfirmed"
    assert split_offset_status("matched", "disclosure", g_big) == "matched"          # 참조가 이미 조정 — 불변
    assert split_offset_status("missing_confirmed", "disclosure", g_big) == "missing_confirmed"  # raw 갭 확정은 불변


def test_apply_manual_verdicts_marks_registered_rows_only():
    from kr_pipeline.ohlcv.adj_missing_audit import apply_manual_verdicts
    rows = [{"ticker": "005420", "ex_date": "2019-10-18", "status": "missing_unconfirmed"},
            {"ticker": "999999", "ex_date": "2020-01-01", "status": "missing_unconfirmed"},
            {"ticker": "005420", "ex_date": "2021-01-01", "status": "missing_unconfirmed"}]
    reg = {"rows": [{"ticker": "005420", "ex_date": "2019-10-18", "verdict": "offset_by_split",
                     "evidence": "주식분할결정 동시 공시"}]}
    assert apply_manual_verdicts(rows, reg) == 1
    assert rows[0]["status"] == "offset_by_split_manual" and rows[0]["manual_verdict"] == "offset_by_split"
    assert rows[1]["status"] == "missing_unconfirmed" and "manual_verdict" not in rows[1]
    assert rows[2]["status"] == "missing_unconfirmed"
