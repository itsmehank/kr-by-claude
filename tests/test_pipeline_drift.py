"""tests/test_pipeline_drift.py — 드리프트 감지/재적재."""
from datetime import date


class _stats:
    rows_affected = 5
    failures = []


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


def test_reload_ticker_sequence(mocker):
    """단일종목: adj 재수신→update→daily Phase A 재계산→weekly 가격 재집계→weekly Phase A 재계산 순서."""
    import kr_pipeline.pipeline.drift as d
    import pandas as pd

    calls = []
    mocker.patch.object(d, "get_daily_min_date", return_value=date(2020, 1, 1))
    fake_df = pd.DataFrame(
        [{"date": date(2024, 1, 2), "open": 9.0, "high": 11.0, "low": 8.0,
          "close": 10.0, "volume": 100.0, "value": 1000.0}]
    )
    mocker.patch.object(d, "fetch_adj_only", side_effect=lambda t, s, e: calls.append("fetch") or fake_df)
    mocker.patch.object(d, "update_adj_prices", side_effect=lambda conn, rows: calls.append(("update", rows)) or len(rows))
    mocker.patch.object(d.indicators, "recompute_ticker_daily", side_effect=lambda conn, t: calls.append(("ind_daily", t)) or 5)
    mocker.patch.object(d.weekly, "run", side_effect=lambda *a, **k: calls.append(("weekly", k.get("only_tickers"))) or _stats())
    mocker.patch.object(d.indicators, "recompute_ticker_weekly", side_effect=lambda conn, t: calls.append(("ind_weekly", t)) or 3)

    out = d.reload_ticker(conn=None, ticker="AAA", as_of=date(2024, 1, 10))

    assert [c[0] if isinstance(c, tuple) else c for c in calls] == \
        ["fetch", "update", "ind_daily", "weekly", "ind_weekly"]
    assert calls[1][1] == [("AAA", date(2024, 1, 2), 10.0, 11.0, 8.0, 9.0, 100.0)]
    assert calls[2][1] == "AAA"
    assert calls[3][1] == ["AAA"]
    assert calls[4][1] == "AAA"
    assert out["ticker"] == "AAA" and out["adj_rows"] == 1


def test_detect_drifted_tickers_uses_given_tickers(mocker):
    """tickers 인자가 주어지면 _active_tickers 대신 그 목록만 검사."""
    import kr_pipeline.pipeline.drift as d

    active = mocker.patch.object(d, "_active_tickers")
    mocker.patch.object(d, "_db_adj_close", return_value={date(2024, 1, 2): 50000.0})
    mocker.patch.object(d, "_krx_adj_close", return_value={date(2024, 1, 2): 10000.0})

    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10),
                                   rel_tol=0.01, tickers=["AAA"])
    assert out == ["AAA"]
    active.assert_not_called()


def test_detect_drifted_tickers_empty_list_checks_nothing(mocker):
    """tickers=[] 는 '검사 0건' — _active_tickers/_krx 호출 없이 빈 리스트."""
    import kr_pipeline.pipeline.drift as d

    active = mocker.patch.object(d, "_active_tickers")
    krx = mocker.patch.object(d, "_krx_adj_close")

    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10),
                                   rel_tol=0.01, tickers=[])
    assert out == []
    active.assert_not_called()
    krx.assert_not_called()


def test_recent_corp_action_tickers_filters(db):
    """영향 이벤트·창 내·활성 종목만 distinct 반환. 비영향/창밖/상폐 제외.

    DB 의 다른(선존) 행에 영향받지 않도록 멤버십/카운트로 검증(전역 exact-match 회피).
    충돌 적은 고유 티커(CAD*) 사용.
    """
    from datetime import timedelta
    from kr_pipeline.pipeline.drift import recent_corp_action_tickers

    as_of = date(2026, 6, 1)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES "
            "('CAD1','a','KOSPI'),('CAD2','b','KOSPI'),('CAD3','d','KOSPI'),('CAD4','e','KOSPI')"
        )
        cur.execute("UPDATE stocks SET delisted_at=%s WHERE ticker='CAD3'", (as_of,))
        cur.execute(
            "INSERT INTO corporate_actions (ticker,event_date,event_type,dart_rcept_no) VALUES "
            "('CAD1',%s,'rights_offering','cad-r1'),"   # 창 내·영향 → 포함
            "('CAD1',%s,'bonus_issue','cad-r2'),"       # 창 내·영향(중복 종목) → distinct 로 1회
            "('CAD1',%s,'rights_offering','cad-r3'),"   # 창 밖(200일 전) → 제외
            "('CAD2',%s,'cash_dividend','cad-r4'),"     # 창 내지만 비영향 → 제외
            "('CAD3',%s,'bonus_issue','cad-r5'),"       # 창 내·영향이나 상폐 → 제외
            "('CAD4',%s,'rights_offering','cad-r6')",   # 미래(as_of+5) → 상한 밖 → 제외
            (as_of - timedelta(days=10), as_of - timedelta(days=20),
             as_of - timedelta(days=200), as_of - timedelta(days=5),
             as_of - timedelta(days=3), as_of + timedelta(days=5)),
        )
    out = recent_corp_action_tickers(db, as_of=as_of, lookback_days=90)
    assert "CAD1" in out            # 창 내 영향 이벤트
    assert out.count("CAD1") == 1   # distinct: 중복 이벤트여도 1회
    assert "CAD2" not in out        # 비영향(cash_dividend)
    assert "CAD3" not in out        # 상폐
    assert "CAD4" not in out        # 미래 event_date (상한 밖)
