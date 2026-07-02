"""순수 집계 로직 단위 테스트 (DB 무관) — §7 사전등록 기준."""


def test_entry_rate_ratio_and_criteria():
    from kr_pipeline.backtest.profitability_run import evaluate_criteria
    entry_rates = {
        "confirmed_uptrend": {"entry": 20, "total": 100, "rate": 0.20},
        "downtrend": {"entry": 2, "total": 100, "rate": 0.02},
        "correction": {"entry": 3, "total": 100, "rate": 0.03},
    }
    # R_down = (2+3)/(100+100)=0.025, R_up=0.20 → ratio 0.125 ≤ 0.5 → PASS
    trade_aggs = {
        "downtrend": {"n": 12, "mean_excess": 1.5},
        "correction": {"n": 8, "mean_excess": -0.5},
        "confirmed_uptrend": {"n": 15, "mean_excess": 4.0},
    }
    out = evaluate_criteria(entry_rates, trade_aggs)
    assert out["gate_defense_71"]["r_down"] == 0.025
    assert out["gate_defense_71"]["r_up"] == 0.20
    assert out["gate_defense_71"]["ratio"] == 0.125
    assert out["gate_defense_71"]["pass"] is True
    # §7.5 검정력: correction n=8 < 10 → underpowered 표기
    assert out["power_guard"]["correction"] == "underpowered"
    assert out["power_guard"]["downtrend"] == "ok"


def test_aggregate_trades_basic():
    from kr_pipeline.backtest.profitability_run import aggregate_trades
    trades = [
        {"phase": "downtrend", "excess_pct": 2.0, "pnl_pct": 1.0},
        {"phase": "downtrend", "excess_pct": -1.0, "pnl_pct": -3.0},
        {"phase": "confirmed_uptrend", "excess_pct": 5.0, "pnl_pct": 6.0},
        {"phase": None, "excess_pct": 1.0, "pnl_pct": 1.0},   # 라벨 없으면 제외
    ]
    agg = aggregate_trades(trades)
    assert agg["downtrend"]["n"] == 2
    assert agg["downtrend"]["mean_excess"] == 0.5
    assert agg["downtrend"]["win_rate"] == 0.5
    assert "confirmed_uptrend" in agg
    assert None not in agg
