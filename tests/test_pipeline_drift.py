"""tests/test_pipeline_drift.py — 드리프트 감지/재적재."""
from datetime import date


def test_is_drift_identical_returns_false():
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0, date(2024, 1, 3): 50500.0}
    krx = {date(2024, 1, 2): 50000.0, date(2024, 1, 3): 50500.0}
    assert is_drift(db, krx, rel_tol=0.01) is False


def test_is_drift_split_ratio_returns_true():
    """분할 후 adj_close 가 배수로 바뀌면 겹치는 날에서 상대차 큼 → True."""
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0, date(2024, 1, 3): 50500.0}
    krx = {date(2024, 1, 2): 10000.0, date(2024, 1, 3): 10100.0}
    assert is_drift(db, krx, rel_tol=0.01) is True


def test_is_drift_tiny_float_noise_returns_false():
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0}
    krx = {date(2024, 1, 2): 50000.4}
    assert is_drift(db, krx, rel_tol=0.01) is False


def test_is_drift_no_overlap_returns_false():
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0}
    krx = {date(2024, 2, 2): 50000.0}
    assert is_drift(db, krx, rel_tol=0.01) is False


def test_detect_drifted_tickers_flags_split(mocker):
    """한 종목은 분할(불일치), 한 종목은 동일 → 분할 종목만 반환."""
    import kr_pipeline.pipeline.drift as d

    mocker.patch.object(d, "_active_tickers", return_value=["AAA", "BBB"])
    mocker.patch.object(d, "_db_adj_close", side_effect=lambda conn, t, s, e: {
        "AAA": {date(2024, 1, 2): 50000.0},
        "BBB": {date(2024, 1, 2): 30000.0},
    }[t])
    mocker.patch.object(d, "_krx_adj_close", side_effect=lambda t, s, e: {
        "AAA": {date(2024, 1, 2): 10000.0},
        "BBB": {date(2024, 1, 2): 30000.0},
    }[t])

    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10), rel_tol=0.01)
    assert out == ["AAA"]


def test_detect_drifted_tickers_widens_on_no_overlap(mocker):
    """30일 겹침 0 → 365일 재조회 후 판정."""
    import kr_pipeline.pipeline.drift as d

    mocker.patch.object(d, "_active_tickers", return_value=["AAA"])
    db_calls = {30: {}, 365: {date(2023, 6, 1): 50000.0}}
    krx_calls = {30: {date(2024, 1, 2): 9000.0}, 365: {date(2023, 6, 1): 10000.0}}

    def fake_db(conn, t, s, e):
        return db_calls[(date(2024, 1, 10) - s).days]
    def fake_krx(t, s, e):
        return krx_calls[(date(2024, 1, 10) - s).days]

    mocker.patch.object(d, "_db_adj_close", side_effect=fake_db)
    mocker.patch.object(d, "_krx_adj_close", side_effect=fake_krx)

    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10),
                                   rel_tol=0.01, recent_days=30, wide_days=365)
    assert out == ["AAA"]


def test_detect_drifted_tickers_skips_fetch_error(mocker):
    """KRX fetch 실패 종목은 로그+skip(드리프트 아님 취급)."""
    import kr_pipeline.pipeline.drift as d

    mocker.patch.object(d, "_active_tickers", return_value=["AAA", "BBB"])
    mocker.patch.object(d, "_db_adj_close", return_value={date(2024, 1, 2): 50000.0})

    def fake_krx(t, s, e):
        if t == "AAA":
            raise RuntimeError("KRX timeout")
        return {date(2024, 1, 2): 50000.0}

    mocker.patch.object(d, "_krx_adj_close", side_effect=fake_krx)
    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10), rel_tol=0.01)
    assert out == []
