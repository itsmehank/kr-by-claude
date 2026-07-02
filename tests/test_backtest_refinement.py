"""prereg 2026-07-02 §2 결정론 보정 — 순수 함수 단위."""
from datetime import date


def test_cost_pct_by_exit_year():
    """§2.2: 매도연도 증권거래세 + 왕복 수수료 0.03%p."""
    from kr_pipeline.backtest.refinement import cost_pct
    assert cost_pct(date(2021, 5, 3)) == 0.23 + 0.03
    assert cost_pct(date(2022, 12, 30)) == 0.23 + 0.03
    assert cost_pct(date(2023, 1, 2)) == 0.20 + 0.03
    assert cost_pct(date(2024, 6, 1)) == 0.18 + 0.03
    assert cost_pct(date(2025, 6, 30)) == 0.15 + 0.03


def test_aggregate_refined_payoff_and_mdd():
    """§2.6: payoff ratio(평균이익/|평균손실|) + MDD 평균, excess_net 기준."""
    from kr_pipeline.backtest.refinement import aggregate_refined
    trades = [
        {"phase": "correction", "excess_net": 10.0, "excess_net_hi": 12.0,
         "pnl_net": 9.0, "mdd_pct": -3.0},
        {"phase": "correction", "excess_net": -5.0, "excess_net_hi": -4.0,
         "pnl_net": -6.0, "mdd_pct": -8.0},
        {"phase": "correction", "excess_net": -5.0, "excess_net_hi": -4.0,
         "pnl_net": -4.0, "mdd_pct": -7.0},
    ]
    agg = aggregate_refined(trades)["correction"]
    assert agg["n"] == 3
    assert agg["mean_excess_net"] == 0.0
    assert agg["mean_excess_net_hi"] == round((12 - 4 - 4) / 3, 3)
    assert agg["win_rate"] == round(1 / 3, 3)
    assert agg["payoff_ratio"] == round(10.0 / 5.0, 3)   # 평균이익 10 / |평균손실 -5|
    assert agg["mean_mdd_pct"] == -6.0


def test_cluster_bootstrap_deterministic_and_sane():
    """§2.5: 종목 클러스터 부트스트랩 — 시드 고정 재현 + CI가 표본평균 포함."""
    from kr_pipeline.backtest.refinement import cluster_bootstrap_ci
    trades = [
        {"ticker": "A", "excess_net": 1.0}, {"ticker": "A", "excess_net": 3.0},
        {"ticker": "B", "excess_net": -2.0}, {"ticker": "C", "excess_net": 2.0},
    ]
    lo1, hi1 = cluster_bootstrap_ci(trades, b=500, seed=20260702)
    lo2, hi2 = cluster_bootstrap_ci(trades, b=500, seed=20260702)
    assert (lo1, hi1) == (lo2, hi2)
    assert lo1 <= 1.0 <= hi1   # 표본평균 1.0
