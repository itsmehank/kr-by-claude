"""prereg 2026-07-02 §2 결정론 보정 — 순수 함수 단위."""
from datetime import date


def test_cost_pct_pre2021_independent_window():
    """이슈 #52: 독립 구간(2017-H2~2020) 청산 비용 — 2019-06-03 증권거래세 인하 경계.

    인하 전(~2019-06-02) 총 0.30%, 인하 후(2019-06-03~2020) 0.25%. 2021+ 는 기존
    연도별 표 그대로(회귀 가드는 test_cost_pct_by_exit_year).
    """
    from datetime import date

    from kr_pipeline.backtest.refinement import cost_pct
    assert cost_pct(date(2017, 7, 3)) == 0.30 + 0.03
    assert cost_pct(date(2018, 12, 28)) == 0.30 + 0.03
    assert cost_pct(date(2019, 6, 2)) == 0.30 + 0.03
    assert cost_pct(date(2019, 6, 3)) == 0.25 + 0.03
    assert cost_pct(date(2020, 12, 30)) == 0.25 + 0.03


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


def test_run_refinement_threads_tickers_and_seed(db, monkeypatch):
    """tickers·seed 파라미터가 하위 호출로 전달되는지 (기본값 = A 동작 불변).

    run_refinement 는 내부에서 aggregate_refined·mean 계산·trades 직렬화를 하므로
    fake 트레이드는 실제 스키마(dict)로 1건 제공한다 (빈 리스트면 mean 이 0-division).
    """
    from datetime import date
    import kr_pipeline.backtest.refinement as rf
    calls = {"ci_seeds": []}
    fake_trade = {"ticker": "000001", "market": "KOSPI",
                  "entry_date": date(2021, 1, 4), "exit_date": date(2021, 2, 1),
                  "phase": "confirmed_uptrend", "excess_net": 1.0,
                  "excess_net_hi": 1.5, "pnl_net": 2.0, "mdd_pct": -3.0}

    def fake_build(conn, tickers=None, entry_mode="breakout"):
        calls["tickers"] = tickers
        return [dict(fake_trade)], 0

    def fake_ci(trades, **kw):
        calls["ci_seeds"].append(kw.get("seed"))
        return (0.0, 2.0)

    def fake_placebo(conn, trades, **kw):
        calls["pl_seed"] = kw.get("seed")
        return {"p": 1.0}

    monkeypatch.setattr(rf, "build_refined_trades", fake_build)
    monkeypatch.setattr(rf, "cluster_bootstrap_ci", fake_ci)
    monkeypatch.setattr(rf, "run_placebo", fake_placebo)
    out = rf.run_refinement(db, tickers=["000001"], seed=20260721)
    assert calls["tickers"] == ["000001"]
    assert set(calls["ci_seeds"]) == {20260721}      # 전체 CI + phase별 CI 전 호출
    assert calls["pl_seed"] == 20260721
    assert out["params"]["seed"] == 20260721          # 실코드 기록 위치 = params.seed


def test_run_refinement_threads_entry_mode(db, monkeypatch):
    """entry_mode 가 build 로 전달되고 params 에 기록된다 (기본 breakout 불변)."""
    from datetime import date
    import kr_pipeline.backtest.refinement as rf
    seen = {}
    fake_trade = {"ticker": "000001", "market": "KOSPI",
                  "entry_date": date(2021, 1, 4), "exit_date": date(2021, 2, 1),
                  "phase": "confirmed_uptrend", "excess_net": 1.0,
                  "excess_net_hi": 1.5, "pnl_net": 2.0, "mdd_pct": -3.0}

    def fake_build(conn, tickers=None, entry_mode="breakout"):
        seen["entry_mode"] = entry_mode
        return [dict(fake_trade)], 0

    monkeypatch.setattr(rf, "build_refined_trades", fake_build)
    monkeypatch.setattr(rf, "cluster_bootstrap_ci", lambda trades, **kw: (0.0, 2.0))
    monkeypatch.setattr(rf, "run_placebo", lambda conn, trades, **kw: {"p": 1.0})
    out = rf.run_refinement(db, entry_mode="pullback")
    assert seen["entry_mode"] == "pullback"
    assert out["params"]["entry_mode"] == "pullback"
