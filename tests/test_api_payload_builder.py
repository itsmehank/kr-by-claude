from datetime import date
from api.services.payload_builder import build_payload


def _seed_full(db, ticker="PLD1"):
    """payload 빌더에 필요한 모든 테이블에 시드."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, sector) VALUES (%s, 'P', 'KOSPI', '전기·전자') ON CONFLICT DO NOTHING", (ticker,))
        cur.execute("""
            INSERT INTO daily_indicators
              (ticker, date, adj_close, volume, sma_50, sma_150, sma_200, w52_high, w52_low,
               rs_rating, minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5,
               minervini_c6, minervini_c7, minervini_c8, minervini_pass,
               avg_volume_50d, volume_ratio_50d)
            VALUES (%s, '2026-05-17', 80000, 12000000, 75000, 70000, 65000, 95000, 50000,
                    95, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, 11000000, 1.09)
            ON CONFLICT DO NOTHING
        """, (ticker,))
        cur.execute("""
            INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
            VALUES (%s, '2026-05-17', 79500, 80500, 79000, 80000, 80000, 12000000, 960000000000)
            ON CONFLICT DO NOTHING
        """, (ticker,))
    db.commit()


def test_build_payload_basic_structure(db):
    _seed_full(db)
    payload = build_payload(db, "PLD1", on_date=date(2026, 5, 17))

    assert payload["symbol"] == "PLD1"
    assert payload["market"] == "KOSPI"
    assert payload["date"] == "2026-05-17"

    assert "conditions_met" in payload
    assert "conditions_detail" in payload
    assert payload["rs_rating"] == 95

    assert payload["current_metrics"]["close"] == 80000.0
    assert payload["current_metrics"]["w52_high"] == 95000.0

    assert "market_context" in payload
    assert "price_data_notes" in payload
    # (#23) 정량 선계산 — §2 마진 카운트·§3.5 시장 하드룰 입력
    assert "conditions_summary" in payload
    assert "market_direction_gate" in payload
    # 시드: 8조건 pass 이나 c3 margin 은 sma_200 이력 1행뿐이라 미산출(None)
    # → 카운트 미확정(null) 의미론 (#38 리뷰) — 확정 int 로 위장하지 않음
    assert payload["conditions_summary"]["marginal_count"] is None


# --- (#23) §2 marginal 카운트 선계산 (순수 함수) ---

def _detail(margins=None, passed=None):
    margins = margins or {}
    passed = passed or {}
    return {
        f"c{i}": {
            "passed": passed.get(f"c{i}", True),
            "margin_pct": margins.get(f"c{i}", 10.0),
        }
        for i in range(1, 9)
    }


def test_conditions_summary_counts_marginal_pass_only():
    """marginal = PASS ∧ margin<3% 만 계수 — 탈락 조건(음수 margin 포함) 미계수."""
    from api.services.payload_builder import _conditions_summary
    detail = _detail(
        margins={"c1": 1.2, "c2": 2.9, "c4": -4.0},
        passed={"c4": False},
    )
    s = _conditions_summary(detail)
    assert s["marginal_count"] == 2
    assert sorted(s["marginal_conditions"]) == ["c1", "c2"]
    assert s["demotion_trigger"] is False


def test_conditions_summary_null_when_pass_margin_missing():
    """PASS 인데 margin 미산출(None) → 카운트 미확정(null) — 확정 숫자로 내보내면
    재계수 금지 규약이 LLM 의 결측 감지를 제거 (#38 리뷰)."""
    from api.services.payload_builder import _conditions_summary
    s = _conditions_summary(_detail(margins={"c1": 1.2, "c3": None}))
    assert s["marginal_count"] is None
    assert s["demotion_trigger"] is None


def test_conditions_summary_demotion_at_three():
    from api.services.payload_builder import _conditions_summary
    s = _conditions_summary(_detail(margins={"c1": 0.5, "c2": 1.0, "c3": 2.0}))
    assert s["marginal_count"] == 3
    assert s["demotion_trigger"] is True


def test_conditions_summary_null_when_passed_unknown():
    """지표 미산출(passed None)이 섞이면 카운트 미확정 — 0 으로 단정하지 않는다."""
    from api.services.payload_builder import _conditions_summary
    s = _conditions_summary(_detail(passed={"c3": None}))
    assert s["marginal_count"] is None
    assert s["demotion_trigger"] is None


# --- (#23) §3.5 시장 하드룰 입력 선계산 (순수 함수) ---

def test_market_direction_gate_force_watch_states():
    from api.services.payload_builder import _market_direction_gate
    for status in ("downtrend", "correction", "rally_attempt"):
        g = _market_direction_gate(
            {"current_status": status, "distribution_day_count_last_25_sessions": 0}
        )
        assert g["force_watch"] is True, status
        assert g["normal_range"] is False


def test_market_direction_gate_rally_attempt_with_recent_ftd_not_forced():
    """§3.5 둘째 룰의 'without a follow-through day' 한정어 보존 — rally_attempt 인데
    **최근**(경과일 ≤ STATUS_FTD_RECENT_DAYS) FTD 가 존재하면 강제 강등 비대상."""
    from api.services.payload_builder import _market_direction_gate
    g = _market_direction_gate(
        {"current_status": "rally_attempt",
         "distribution_day_count_last_25_sessions": 6,
         "last_follow_through_day": "2026-07-08",
         "days_since_follow_through": 5}
    )
    assert g["force_watch"] is False
    assert g["confidence_penalty"] is True  # dist>=5 감점은 별도 룰로 여전히 적용


def test_market_direction_gate_rally_attempt_stale_ftd_forced():
    """만료 FTD(경과일 > 90)는 'without FTD' 취급 — 강등 필수 (#38 재리뷰).

    status.py 는 FTD 만료 때문에 rally_attempt 를 반환하므로 이 경로에서는 만료
    FTD 기록이 항상 잔존 — 'FTD 기록 존재'만 보면 §3.5 하드룰이 상시 우회된다."""
    from api.services.payload_builder import _market_direction_gate
    g = _market_direction_gate(
        {"current_status": "rally_attempt",
         "distribution_day_count_last_25_sessions": 2,
         "last_follow_through_day": "2026-03-01",
         "days_since_follow_through": 134}
    )
    assert g["force_watch"] is True


def test_market_direction_gate_rally_attempt_ftd_age_unknown_forced():
    """FTD 날짜는 있는데 경과일 미산출(None) → 최근임을 확인 불가 = 보수(강등)."""
    from api.services.payload_builder import _market_direction_gate
    g = _market_direction_gate(
        {"current_status": "rally_attempt",
         "distribution_day_count_last_25_sessions": 2,
         "last_follow_through_day": "2026-07-08",
         "days_since_follow_through": None}
    )
    assert g["force_watch"] is True


def test_market_direction_gate_non_uptrend_normal_range_false_even_without_dist():
    """status 가 confirmed_uptrend 가 아니면 넷째 룰 전제 자체가 거짓 — 분배일 결측이어도
    normal_range 는 null 이 아니라 False 확정 (#38 재리뷰: null 승격은 정보 손실이며,
    rally_attempt+최근 FTD+dist 결측 조합에서 조문에 없는 전면 entry 금지를 유발)."""
    from api.services.payload_builder import _market_direction_gate
    g = _market_direction_gate(
        {"current_status": "rally_attempt",
         "distribution_day_count_last_25_sessions": None,
         "last_follow_through_day": "2026-07-08",
         "days_since_follow_through": 5}
    )
    assert g["normal_range"] is False     # 확정 False (null 아님)
    assert g["force_watch"] is False      # 최근 FTD — 강등 비대상
    assert g["confidence_penalty"] is None  # dist 결측 — 이건 미확정이 맞음


def test_market_direction_gate_unknown_status_is_null():
    """미지의 status 값 → 통과(False)로 단정하지 않고 null (보수: null=entry 금지)."""
    from api.services.payload_builder import _market_direction_gate
    g = _market_direction_gate(
        {"current_status": "sideways_chop",
         "distribution_day_count_last_25_sessions": 1}
    )
    assert g["force_watch"] is None
    assert g["normal_range"] is None


def test_market_direction_gate_confirmed_uptrend_bands():
    from api.services.payload_builder import _market_direction_gate

    def g(dist):
        return _market_direction_gate(
            {"current_status": "confirmed_uptrend",
             "distribution_day_count_last_25_sessions": dist}
        )

    assert g(2) == {"status": "confirmed_uptrend", "dist_count": 2,
                    "last_follow_through_day": None,
                    "force_watch": False, "confidence_penalty": False,
                    "normal_range": True}
    # dist 4: 프롬프트가 원래 미규정인 구간 — 갭 보존 (전부 False)
    g4 = g(4)
    assert (g4["force_watch"], g4["confidence_penalty"], g4["normal_range"]) == (
        False, False, False)
    g5 = g(5)
    assert g5["confidence_penalty"] is True
    assert g5["normal_range"] is False


def test_market_direction_gate_null_propagation():
    from api.services.payload_builder import _market_direction_gate
    g = _market_direction_gate(
        {"current_status": None, "distribution_day_count_last_25_sessions": None}
    )
    assert g["force_watch"] is None
    assert g["confidence_penalty"] is None
    assert g["normal_range"] is None


def test_build_payload_unknown_ticker(db):
    """존재 안 하는 종목 → ValueError."""
    import pytest
    with pytest.raises(ValueError, match="not found"):
        build_payload(db, "NOEXIST", on_date=date(2026, 5, 17))


def test_fetch_daily_ohlcv_uses_adjusted(db):
    from api.services.payload_builder import _fetch_daily_ohlcv
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ADJD','t','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("""INSERT INTO daily_prices
            (ticker,date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value)
            VALUES ('ADJD',%s,10000,10500,9800,10000,2000,2000,2100,1960,500.0,1000,10000000)
            ON CONFLICT DO NOTHING""", (date(2026,1,2),))
    db.commit()
    out = _fetch_daily_ohlcv(db, "ADJD", date(2026,1,31), days=60)
    assert len(out) == 1
    bar = out[0]
    assert bar["open"] == 2000.0 and bar["high"] == 2100.0
    assert bar["low"] == 1960.0 and bar["close"] == 2000.0
    assert bar["volume"] == 500   # adj_volume


def test_fetch_weekly_ohlcv_uses_adjusted(db):
    from api.services.payload_builder import _fetch_weekly_ohlcv
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ADJW','t','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("""INSERT INTO weekly_prices
            (ticker,week_end_date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value,trading_days)
            VALUES ('ADJW',%s,10000,10500,9800,10000,2000,2000,2100,1960,500.0,1000,10000000,5)
            ON CONFLICT DO NOTHING""", (date(2026,1,2),))
    db.commit()
    out = _fetch_weekly_ohlcv(db, "ADJW", date(2026,1,31), weeks=104)
    assert out[0]["open"] == 2000.0 and out[0]["high"] == 2100.0
    assert out[0]["low"] == 1960.0 and out[0]["close"] == 2000.0
    assert out[0]["volume"] == 500   # adj_volume (int(round(float)))


def test_fetch_indicators_recent_uses_adjusted_volume(db):
    """indicators_recent.volume 은 adj(daily_indicators.volume) — raw(daily_prices.volume) 아님.
    daily_ohlcv(adj)·avg_volume_50d/volume_ratio(adj)와 같은 도메인으로 통일."""
    from api.services.payload_builder import _fetch_indicators_recent
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ADJI','t','KOSPI') ON CONFLICT DO NOTHING")
        # raw volume=1000, 그러나 adj(daily_indicators.volume)=500
        cur.execute("""INSERT INTO daily_prices
            (ticker,date,open,high,low,close,adj_close,adj_volume,volume,value)
            VALUES ('ADJI',%s,10000,10500,9800,10000,2000,500.0,1000,10000000)
            ON CONFLICT DO NOTHING""", (date(2026,1,2),))
        cur.execute("""INSERT INTO daily_indicators
            (ticker,date,adj_close,volume,avg_volume_50d,volume_ratio_50d)
            VALUES ('ADJI',%s,2000,500,480,1.04)
            ON CONFLICT DO NOTHING""", (date(2026,1,2),))
    db.commit()
    out = _fetch_indicators_recent(db, "ADJI", date(2026,1,31), days=60)
    assert len(out) == 1
    assert out[0]["volume"] == 500   # i.volume(adj), raw=1000 이면 실패
