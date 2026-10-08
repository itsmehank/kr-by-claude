"""테스트 헬퍼 — evaluate_pivot 의 #109 entry 경로 시장 게이트를 '시장 정상(confirmed_uptrend, 당일 행)'으로 고정.
시장 게이트와 무관한 동작(extended·strict·가드·사용량 한도 등)을 검증하는 기존 테스트가 시장 데이터 부재로 market_gate_null
차단되지 않게 한다. 시장 게이트 자체는 tests/test_entry_market_gate*.py 가 검증."""


def allow_market(mocker, ev_module):
    return mocker.patch.object(
        ev_module, "build_market_context",
        side_effect=lambda conn, market, on_date: {
            "as_of_date": on_date.isoformat(), "current_status": "confirmed_uptrend",
            "distribution_day_count_last_25_sessions": 2, "last_follow_through_day": None,
            "days_since_follow_through": None, "pct_stocks_above_200d_ma": 50.0})
