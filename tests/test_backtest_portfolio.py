"""포트폴리오 엔진 — prereg 2026-07-02 portfolio-sim 핵심 규칙 단위 테스트 (DB-free)."""
from datetime import date, timedelta

from kr_pipeline.backtest.trigger_sim import DayBar, WatchRow


def _bars(start: date, seq):
    """seq: (close, volume, sma_50) — 주말 건너뛰는 연속 거래일, avgvol=100."""
    out, prev = [], None
    d = start
    for close, vol, sma in seq:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(DayBar(d=d, close=close, volume=vol, sma_50=sma,
                          avg_volume_50d=100.0, prev_close=prev))
        prev = close
        d += timedelta(days=1)
    return out


def _tdata(bars, pivot=100.0, base_low=90.0, sat=None, rs=80):
    from kr_pipeline.backtest.portfolio import TickerData
    sat = sat or (bars[0].d - timedelta(days=2))
    wr = [WatchRow(ticker="T", sat=sat, pivot_price=pivot, base_low=base_low,
                   watch_reason="valid_base_awaiting_breakout")]
    return TickerData(market="KOSPI", bars=bars, watch_rows=wr,
                      rs_by_date={b.d: rs for b in bars}, phase_by_date={})


def _run(data, **over):
    from kr_pipeline.backtest.portfolio import PortfolioConfig, run_portfolio
    return run_portfolio(data, PortfolioConfig(**over))


def test_sizing_fixed_risk_over_8pct_stop():
    """v2: stop 8% 고정 → 포지션 일률 1.25%/8% = 15.625%. wide-stop 스킵 없음."""
    start = date(2024, 1, 8)
    b1 = _bars(start, [(98, 200, 96), (104, 200, 97.76)])
    r = _run({"A": _tdata(b1)})
    assert abs(r["stats"]["entry_amounts"][0] - 0.15625 * 100_000_000) < 1.0
    # v1 에서 스킵되던 wide-stop 케이스도 v2 에선 진입 (구조적 스톱 미사용)
    b2 = _bars(start, [(98, 200, 90), (104, 200, 89.44)])
    r2 = _run({"A": _tdata(b2)})
    assert r2["stats"]["n_entries"] == 1


def test_breakeven_floor_arms_at_20pct_then_exits():
    """v2: armed = min(3R, +20%) = avg×1.20 도달 후, 평균매입가 하회 → floor 청산."""
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (105, 200, 99.75),
                         (127, 200, 100),   # ≥ 126 (=105×1.20) → armed
                         (104, 200, 100)])  # < avg 105 → floor
    r = _run({"A": _tdata(bars)})
    assert r["stats"]["exit_reasons"] == {"floor": 1}
    # +20% 미달(121 < 126)이면 미장전 → 104 에서도 보유 유지(8% 스톱 96.6 위)
    bars2 = _bars(start, [(98, 200, 96), (105, 200, 99.75),
                          (121, 200, 100), (104, 200, 100)])
    r2 = _run({"A": _tdata(bars2)})
    assert r2["stats"]["exit_reasons"] == {}


def test_initial_8pct_stop_exit():
    """v2: 종가 < 평균매입가×0.92 → stop8 청산."""
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (105, 200, 99.75),
                         (96, 200, 95)])    # 96 < 96.6 → stop8
    r = _run({"A": _tdata(bars)})
    assert r["stats"]["exit_reasons"] == {"stop8": 1}


def test_sma50_trailing_only_after_breakeven():
    """v2: sma50 < 평균매입가인 동안 sma50 이탈은 무시(v1 과 차이),
    sma50 ≥ 평균매입가가 된 뒤의 이탈만 sma50_trail 청산."""
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 96), (105, 200, 99.75),
                         (98, 200, 99),     # 종가 < sma50(99) but sma50 < avg → 보유
                         (108, 200, 105.5),
                         (105.4, 200, 106)])  # sma50 106 ≥ avg 105, 종가 < 106 → trail
    r = _run({"A": _tdata(bars)})
    assert r["stats"]["exit_reasons"] == {"sma50_trail": 1}


def test_replacement_swaps_weakest_but_not_same_day_entry():
    """만석 + 신규 신호 → 최약(≤0%) 교체. 당일 진입 포지션은 면제라 연쇄 순환 없음."""
    start = date(2024, 1, 8)
    data = {}
    for i, t in enumerate("ABCDE"):     # 전원 1/9 진입 → 만석
        seq = [(98, 200, 90), (104, 200, 95)]
        seq += [(102.9 if t == "A" else 106.1, 200, 95)] * 2   # A만 -1.06%
        data[t] = _tdata(_bars(start, seq), rs=90 - i)
    # F: 다음날 신호 → A 교체 기대
    data["F"] = _tdata(_bars(start, [(98, 200, 90), (99, 200, 95),
                                     (104, 200, 95), (104, 200, 95)]), rs=99)
    r = _run(data, max_positions=5)
    assert r["stats"]["n_replacements"] == 1
    assert ("A", "replaced") in [(e["ticker"], e["reason"]) for e in r["stats"]["exits"]]


def test_pyramid_tranche_chase_and_fill():
    """S2: T2 트리거일 종가가 pivot×1.05 초과면 소멸, 이내면 30% 체결."""
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 90), (101, 200, 95),
                         (106, 200, 95), (104, 200, 95)])   # 106 > 105 → chase 소멸
    r = _run({"A": _tdata(bars)}, pyramiding=True)
    assert r["stats"]["n_entries"] == 1
    assert r["stats"]["n_tranche_fills"] == 0
    assert r["stats"]["tranche_expiry"] == {"chase": 2}     # T2·T3 동시 소멸
    bars2 = _bars(start, [(98, 200, 90), (101, 200, 95), (103.5, 200, 95)])
    r2 = _run({"A": _tdata(bars2)}, pyramiding=True)
    assert r2["stats"]["n_tranche_fills"] == 1              # T2만


def test_sell_half_after_3weeks():
    """S3: +20% 최초 도달이 진입 21일 초과면 당일 종가 절반 매도."""
    start = date(2024, 1, 8)
    seq = [(98, 200, 90), (101, 200, 95)]
    seq += [(101, 200, 95)] * 18            # 3주 초과 경과
    seq += [(122, 200, 95)]                 # +20.8%
    r = _run({"A": _tdata(_bars(start, seq))}, pyramiding=True, sell_half=True)
    assert r["stats"]["n_half_sells"] == 1


def test_down_phase_exclusion_skips_entry():
    """excl 모드: 진입일 국면 downtrend/correction → T1 스킵."""
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 90), (104, 200, 95)])
    td = _tdata(bars)
    td.phase_by_date = {b.d: "correction" for b in bars}
    r = _run({"A": td}, exclude_down_phases=True)
    assert r["stats"]["n_entries"] == 0
    assert r["stats"]["n_skipped_down_phase"] == 1


def test_gate_mode_prod_blocks_by_watch_reason():
    """v3 Arm A: unfavorable_market watch 는 confirmed_uptrend 외 전부 차단,
    다른 사유(valid_base 등)는 rally_attempt 에서도 통과."""
    from kr_pipeline.backtest.portfolio import TickerData
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 90), (104, 200, 95)])
    sat = bars[0].d - timedelta(days=2)

    def td(reason, phase):
        wr = [WatchRow(ticker="T", sat=sat, pivot_price=100.0, base_low=90.0,
                       watch_reason=reason)]
        return TickerData(market="KOSPI", bars=bars, watch_rows=wr,
                          rs_by_date={b.d: 80 for b in bars},
                          phase_by_date={b.d: phase for b in bars})

    # unfavorable_market + rally_attempt → 차단 (기존 excl 은 허용했던 케이스)
    r = _run({"A": td("unfavorable_market", "rally_attempt")}, gate_mode="prod")
    assert r["stats"]["n_entries"] == 0
    # unfavorable_market + confirmed → 통과
    r2 = _run({"A": td("unfavorable_market", "confirmed_uptrend")}, gate_mode="prod")
    assert r2["stats"]["n_entries"] == 1
    # valid_base + rally_attempt → 통과 (사유별 분기)
    r3 = _run({"A": td("valid_base_awaiting_breakout", "rally_attempt")},
              gate_mode="prod")
    assert r3["stats"]["n_entries"] == 1


def test_gate_mode_variant_uses_variant_phases():
    """v3 Arm B: 같은 게이트 의미론을 변형 사다리 국면으로 판정."""
    from kr_pipeline.backtest.portfolio import TickerData
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 90), (104, 200, 95)])
    sat = bars[0].d - timedelta(days=2)
    wr = [WatchRow(ticker="T", sat=sat, pivot_price=100.0, base_low=90.0,
                   watch_reason="unfavorable_market")]
    td = TickerData(market="KOSPI", bars=bars, watch_rows=wr,
                    rs_by_date={b.d: 80 for b in bars},
                    phase_by_date={b.d: "rally_attempt" for b in bars},
                    phase_variant_by_date={b.d: "confirmed_uptrend" for b in bars})
    assert _run({"A": td}, gate_mode="prod")["stats"]["n_entries"] == 0
    assert _run({"A": td}, gate_mode="variant")["stats"]["n_entries"] == 1


def _pilot_td(bars, phase="downtrend", bottoming=True, ftd=False, rs=80):
    from kr_pipeline.backtest.portfolio import TickerData
    sat = bars[0].d - timedelta(days=2)
    wr = [WatchRow(ticker="T", sat=sat, pivot_price=100.0, base_low=90.0,
                   watch_reason="unfavorable_market")]
    ep = bars[0].d - timedelta(days=5)
    return TickerData(
        market="KOSPI", bars=bars, watch_rows=wr,
        rs_by_date={b.d: rs for b in bars},
        phase_by_date={b.d: phase for b in bars},
        bottoming_by_date={b.d: ((True, ep) if bottoming else (False, None))
                           for b in bars},
        ftd_valid_by_date={b.d: ftd for b in bars})


def test_pilot_entry_size_and_6pct_stop():
    """v4.2: bottoming 창의 차단 신호 → 파일럿 진입(정상의 50%=7.8125%), 스톱 6%."""
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 90), (104, 200, 95),
                         (97.5, 200, 92)])   # 97.5 < 104×0.94=97.76 → stop 청산
    r = _run({"A": _pilot_td(bars)}, gate_mode="prod", pilot_mode=True)
    assert r["stats"]["n_pilot_entries"] == 1
    assert abs(r["stats"]["entry_amounts"][0] - 0.078125 * 100_000_000) < 1.0
    assert r["stats"]["exit_reasons"] == {"stop8": 1}   # 스톱 레이어(6%)로 청산
    # bottoming 아니면 기존대로 차단
    r2 = _run({"A": _pilot_td(bars, bottoming=False)}, gate_mode="prod",
              pilot_mode=True)
    assert r2["stats"]["n_entries"] == 0


def test_pilot_retry_cap_2_per_episode():
    """v4.2: 같은 (종목, 에피소드) 최대 2회 — 3번째 신호는 스킵."""
    start = date(2024, 1, 8)
    # 진입→스톱아웃 → 재진입→스톱아웃 → 3번째 fresh cross 는 캡으로 스킵
    seq = [(98, 200, 90), (104, 200, 95), (97, 200, 92),     # 1차 진입·스톱
           (99, 200, 92), (104, 200, 95), (97, 200, 92),     # 2차 진입·스톱
           (99, 200, 92), (104, 200, 95), (105, 200, 95)]    # 3번째 → 캡
    r = _run({"A": _pilot_td(_bars(start, seq))}, gate_mode="prod", pilot_mode=True)
    assert r["stats"]["n_pilot_entries"] == 2
    assert r["stats"]["n_skipped_retry_cap"] == 1


def test_scaleup_via_ftd_enters_normal_size():
    """v4.2 증액 (i): FTD 유효한 날의 파일럿 경로 신호는 정상 사이즈(15.625%)."""
    start = date(2024, 1, 8)
    bars = _bars(start, [(98, 200, 90), (104, 200, 95)])
    r = _run({"A": _pilot_td(bars, ftd=True)}, gate_mode="prod", pilot_mode=True)
    assert r["stats"]["n_scaled_entries"] == 1
    assert abs(r["stats"]["entry_amounts"][0] - 0.15625 * 100_000_000) < 1.0
    assert r["stats"]["scaleup_triggers"] == {"i_ftd": 1}
