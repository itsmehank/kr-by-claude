"""P4 premium bins — 구간 분할·stopout 률·소표본 가드 (prereg P4)."""
from kr_pipeline.backtest.premium_bins import premium_bins


def _exit(premium, reason, pnl):
    return {"premium_pct": premium, "reason": reason, "pnl_pct": pnl}


def test_bins_and_gap():
    exits = ([_exit(0.5, "stop8", -8.0)] * 3 + [_exit(0.5, "sma50", 10.0)] * 7
             + [_exit(2.0, "stop8", -8.0)] * 3 + [_exit(2.0, "armed_be", 5.0)] * 7
             + [_exit(4.0, "stop8", -8.0)] * 8)
    out = premium_bins(exits)
    assert out["bins"]["0-1"]["n"] == 10 and out["bins"]["1-3"]["n"] == 10
    assert out["bins"]["3-5"]["n"] == 8
    assert out["p4"]["low_stopout"] == 30.0     # (3+3)/20
    assert out["p4"]["high_stopout"] == 100.0
    assert out["p4"]["gap_pp"] == 70.0
    assert out["p4"]["verdict"] == "promote"


def test_insufficient_n_guard():
    exits = [_exit(4.0, "stop8", -8.0)] * 7 + [_exit(0.5, "sma50", 5.0)] * 10
    out = premium_bins(exits)
    assert out["p4"]["verdict"] == "insufficient_n"     # 3-5 구간 7 < 8


def test_out_of_range_premium_ignored():
    exits = [_exit(6.0, "stop8", -8.0)] + [_exit(0.5, "sma50", 5.0)]
    out = premium_bins(exits)
    assert sum(b["n"] for b in out["bins"].values()) == 1
