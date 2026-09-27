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
