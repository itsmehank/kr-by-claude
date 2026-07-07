# tests/test_market_context_modes.py
from datetime import date, timedelta
from freezegun import freeze_time

from kr_pipeline.market_context.modes import (
    Mode, compute_date_range, LOOKBACK_DAYS,
)


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.FULL_REFRESH.value == "full-refresh"


@freeze_time("2026-05-18")
def test_incremental_window_30():
    """load_start = today - 30 - LOOKBACK_DAYS, upsert_start = today - 30."""
    load_start, load_end, upsert_start = compute_date_range(Mode.INCREMENTAL, window_days=30)
    today = date(2026, 5, 18)
    assert load_end == today
    assert upsert_start == today - timedelta(days=30)
    assert load_start == today - timedelta(days=30 + LOOKBACK_DAYS)


@freeze_time("2026-07-08")
def test_incremental_load_end_is_today():
    """P1-4: incremental load_end 는 어제가 아니라 오늘이어야 한다.

    ohlcv 체인(평일 18:30)이 index_daily 에 당일 확정봉을 적재하므로,
    market_context(19:30)가 어제까지만 계산하면 20:00 LLM 이 stale status 를
    소비한다 (주말 경로는 T-2). 당일 행이 없으면 로드 결과에 그 날짜가
    없어 자연 skip 되므로 today 가 안전하다.
    """
    _, load_end, _ = compute_date_range(Mode.INCREMENTAL, window_days=30)
    assert load_end == date(2026, 7, 8)


def test_backfill_uses_db_min(monkeypatch):
    from kr_pipeline.market_context import modes
    monkeypatch.setattr(modes, "_get_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        load_start, load_end, upsert_start = compute_date_range(Mode.BACKFILL, conn=None)
    assert load_start == date(2024, 1, 2)
    assert upsert_start == date(2024, 1, 2)


def test_per_date_db_error_does_not_cascade(db, monkeypatch):
    """P2: 날짜 1건의 DB 예외가 rollback 없이 aborted 트랜잭션으로 남아
    잔여 날짜 전부를 InFailedSqlTransaction 연쇄 실패시키면 안 된다.

    (weekly/indicators 의 종목 루프는 except 에서 rollback — 여기만 비대칭)
    """
    from datetime import date as _date
    import pandas as pd
    from kr_pipeline.market_context import modes

    dates = [_date(2026, 6, 1), _date(2026, 6, 2), _date(2026, 6, 3)]
    df = pd.DataFrame({"date": dates})

    monkeypatch.setattr(
        modes, "compute_date_range",
        lambda mode, window_days=30, conn=None: (dates[0], dates[-1], dates[0]),
    )
    monkeypatch.setattr(
        modes, "load_index_daily_with_sma200",
        lambda conn, code, s, e: df if code == "1001" else pd.DataFrame(),
    )

    ok_calls: list = []

    def fake_process(conn, target_date, index_code, market, idx_df):
        if target_date == dates[0]:
            # 실제 DB 예외로 트랜잭션을 aborted 상태로 만든 뒤 전파
            with conn.cursor() as cur:
                cur.execute("SELECT 1/0")
            return None  # unreachable
        # rollback 이 됐다면 이 쿼리는 성공해야 한다
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        ok_calls.append(target_date)
        return None

    monkeypatch.setattr(modes, "_process_one_date", fake_process)

    stats = modes.run(db, modes.Mode.INCREMENTAL)

    assert len(ok_calls) == 2, f"잔여 날짜가 연쇄 실패 (처리 성공: {ok_calls})"
    assert len(stats.failures) == 1, f"1건만 실패해야 하는데: {stats.failures}"
