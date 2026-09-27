"""#186 B — as-of (a): 유효 시점 = 접수일의 **다음 거래일**(접수 시각 부재 → 장후 접수 look-ahead 방지). 달력 = index_daily."""
from datetime import date

from kr_pipeline.financials import asof


def _seed_index(db, dates):
    with db.cursor() as cur:
        for d in dates:
            cur.execute("INSERT INTO index_daily (index_code, date, open, high, low, close) VALUES ('1001', %s, 1, 1, 1, 1) ON CONFLICT DO NOTHING", (d,))


def test_effective_from_is_next_trading_day_after_receipt(db):
    _seed_index(db, [date(2031, 4, 1), date(2031, 4, 2), date(2031, 4, 7)])   # 04-03(목)~04-06 휴장 가정
    assert asof.effective_from(db, date(2031, 4, 1)) == date(2031, 4, 2)
    assert asof.effective_from(db, date(2031, 4, 2)) == date(2031, 4, 7)      # 다음 거래일까지 건너뜀
    assert asof.effective_from(db, date(2031, 4, 4)) == date(2031, 4, 7)      # 휴일 접수 → 다음 거래일


def test_effective_from_none_when_calendar_has_no_later_day(db):
    assert asof.effective_from(db, date(2099, 1, 1)) is None


def test_rcept_dt_from_rcept_no():
    assert asof.rcept_dt_of("20250311001085") == date(2025, 3, 11)
    assert asof.rcept_dt_of(None) is None and asof.rcept_dt_of("bad") is None


def test_effective_from_cell_uses_response_rcept_dt_only(db):
    """[Q-3] A 채택: 유효 시점 입력 = 응답에 담긴 rcept_no(정정본) 접수일. 원공시 접수일(orig_rcept_dt)은 계산에 쓰지 않는다
    (용도 = 정정 기인 NULL 비율 측정·파리티 귀속만). 원공시일이 더 이르더라도 결과는 정정 접수일 다음 거래일."""
    _seed_index(db, [date(2031, 6, 2), date(2031, 6, 3), date(2036, 4, 3)])
    cell = {"rcept_dt": date(2036, 4, 2), "orig_rcept_dt": date(2031, 6, 2), "is_correction": True}
    assert asof.effective_from_cell(db, cell) == date(2036, 4, 3)
    assert asof.effective_from_cell(db, {"rcept_dt": None, "orig_rcept_dt": date(2031, 6, 2)}) is None   # 응답 접수일 없음 → 결측(보수)
