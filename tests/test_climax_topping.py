# tests/test_climax_topping.py
"""(#44 D1) find_anchor — climax/topping anchor 전 이력 탐색 단위테스트.

가장 최근 Stage 1→2 전환 주를 anchor 로 잡는 순수 함수. 드리프트-다운 픽스처로
close<SMA 엄격 부등호가 항상 성립하도록 구성(정확 상수 평탄 구간은 부동소수/SMA
경계에서 부등호가 깨질 수 있음).
"""
from kr_pipeline.llm_runner.compute.climax_topping import (
    compute_climax_gates,
    compute_topping_gates,
    find_anchor,
)


def _mk_weeks(rows: list[tuple[float, int]], start="2018-01-05") -> list[dict]:
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [{"week_end": str(d0 + timedelta(weeks=i)), "open": p, "high": p * 1.02,
             "low": p * 0.98, "close": p, "volume": v} for i, (p, v) in enumerate(rows)]


def _mk_daily_updays(n: int, up: int, start="2020-01-06") -> list[dict]:
    """최근 n 거래일 합성 일봉. n-1 개의 전일比 비교 중 up 개가 상승(뒤쪽에 몰아
    trailing 윈도우가 up 비율을 온전히 볼 수 있게 구성) — 나머지는 하락."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    down = (n - 1) - up
    closes = [100.0]
    for _ in range(down):
        closes.append(closes[-1] - 1.0)
    for _ in range(up):
        closes.append(closes[-1] + 1.0)
    return [{"date": str(d0 + timedelta(days=i)), "open": c, "high": c + 0.5,
             "low": c - 0.5, "close": c, "volume": 100_000}
            for i, c in enumerate(closes)]


def _drift(n: int, top: float, bot: float, vol: int = 100_000) -> list[tuple[float, int]]:
    step = (top - bot) / max(n - 1, 1)
    return [(top - step * i, vol) for i in range(n)]


def _fixture_single_transition():
    # 65주 완만 하락(1000→980, close<SMA 상시 성립) + 돌파주(1100, 2.6×vol) + 19주 상승
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
         + [(1100.0 + 15 * i, 110_000) for i in range(1, 20)]
    return _mk_weeks(rows)


def test_anchor_finds_transition():
    wk = _fixture_single_transition()
    r = find_anchor(wk)
    assert r["left_censored"] is False and r["no_transition"] is False
    assert r["anchor_week"] == wk[65]["week_end"]
    assert r["weeks_since"] == 19


def test_anchor_resets_after_stage4():
    # 1차 상승 → Stage 4 급락 → 55주 하락 드리프트 → 2차 돌파: '가장 최근' 전환을 잡아야
    rows = ([(1000.0 + 30 * i, 100_000) for i in range(30)]        # 1차 상승
            + _drift(20, 1900.0, 700.0)                            # Stage 4
            + _drift(55, 700.0, 660.0)                             # Stage 1 재형성
            + [(800.0, 300_000)]                                   # 2차 전환 (idx 105)
            + [(800.0 + 20 * i, 110_000) for i in range(1, 6)])
    wk = _mk_weeks(rows)
    assert find_anchor(wk)["anchor_week"] == wk[105]["week_end"]


def test_anchor_left_censored_short_history():
    wk = _mk_weeks(_drift(40, 1000.0, 980.0))          # 이력 40주 ≤ 50주
    assert find_anchor(wk) == {"anchor_week": None, "left_censored": True,
                               "no_transition": False, "weeks_since": None}


def test_anchor_no_transition_long_stage2():
    # 80주 내내 완만 상승(전환 조건 부재, 이력 충분) → no_transition (P1 간주 모드)
    wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(80)])
    r = find_anchor(wk)
    assert r["left_censored"] is False and r["no_transition"] is True
    assert r["anchor_week"] is None


# ===== Task 3: compute_climax_gates =====

def _fixture_climax_run():
    # anchor(idx 65) + 상승 19주 + 클라이맥스 3주 = anchor 후 22주 (maturity 22 ≥ 18)
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
         + [(1100.0 + 15 * i, 110_000) for i in range(1, 20)] \
         + [(1500.0, 300_000), (1700.0, 350_000), (1950.0, 900_000)]
    return _mk_weeks(rows)


def test_climax_gates_fire_on_vertical_run():
    wk = _fixture_climax_run()
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), find_anchor(wk))
    assert g["baseline"] == "anchored" and g["maturity_weeks"] == 22
    assert g["maturity_ok"] is True
    # 3주 롤링: 1950/1385(k=3, idx 87/84) ≈ +40.8% ≥ 25%, 상승 전체 최급
    assert g["p2_accel_ok"] is True
    assert g["t2_max_volume_now"] is True and g["t4_ok"] is True
    assert g["scope_active"] is True


def test_climax_gates_scope_expires():
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
         + [(1100.0 + 40 * i, 110_000) for i in range(1, 20)] \
         + [(1850.0, 120_000), (1840.0, 100_000), (1830.0, 100_000)]  # 고점 후 3주 횡보
    wk = _mk_weeks(rows)
    assert compute_climax_gates(wk, _mk_daily_updays(10, up=5), find_anchor(wk))["scope_active"] is False


def test_climax_gates_all_none_when_left_censored():
    wk = _mk_weeks(_drift(40, 1000.0, 980.0))
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=5), find_anchor(wk))
    assert g["maturity_ok"] is None and g["p2_accel_ok"] is None and g["baseline"] is None


_ANCHOR_DEP_CLIMAX = ("maturity_weeks", "maturity_ok", "p2_best_roll_pct", "p2_is_steepest",
                      "p2_accel_ok", "t1_max_spread_now", "t2_max_volume_now", "scope_active")


def test_climax_gates_no_transition_anchor_fields_none():
    # (#169) 시작점 부재 = anchor 의존 필드 전부 None(구 #44 규약 P1 간주·전체 이력 극값 폐기)
    wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(80)])
    anchor = find_anchor(wk)
    assert anchor["no_transition"] is True
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), anchor)
    assert g["baseline"] == "no_transition"  # 모드 기록은 유지
    assert all(g[k] is None for k in _ANCHOR_DEP_CLIMAX)


def test_climax_gates_no_transition_keeps_non_anchor_fields():
    # (#169) anchor 비의존 T3/T4 는 anchored 와 같은 산술로 계산된다(daily 만 입력)
    wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(80)])
    daily = _mk_daily_updays(10, up=8)
    g = compute_climax_gates(wk, daily, find_anchor(wk))
    ref = compute_climax_gates(_fixture_climax_run(), daily, find_anchor(_fixture_climax_run()))
    assert g["t4_ok"] is True and g["t4_up_days_pct_max"] == ref["t4_up_days_pct_max"]
    assert g["t3_gap_up_today"] == ref["t3_gap_up_today"]
    assert g["quality_flag"] is False


def test_climax_gates_no_transition_equals_left_censored_on_anchor_fields():
    # (#169) anchor 의존 필드는 두 결측 모드가 동일 출력(None)
    nt_wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(80)])
    lc_wk = _mk_weeks(_drift(40, 1000.0, 980.0))
    daily = _mk_daily_updays(10, up=5)
    nt = compute_climax_gates(nt_wk, daily, find_anchor(nt_wk))
    lc = compute_climax_gates(lc_wk, daily, find_anchor(lc_wk))
    assert {k: nt[k] for k in _ANCHOR_DEP_CLIMAX} == {k: lc[k] for k in _ANCHOR_DEP_CLIMAX}
    # §6.2 anchor 의존 필드도 동일(None); anchor 비의존 G0/T-B/T-C/td_dist 는 계산됨
    tn = compute_topping_gates(nt_wk, 5, find_anchor(nt_wk))
    tl = compute_topping_gates(lc_wk, 5, find_anchor(lc_wk))
    assert tn["ta_max_decline_now"] is None and tn["td_max_down_volume_now"] is None
    assert tn["tc_prolonged_ok"] is None
    assert (tn["ta_max_decline_now"], tn["td_max_down_volume_now"]) == \
        (tl["ta_max_decline_now"], tl["td_max_down_volume_now"])
    assert tn["g0_below_10w"] is False and tn["td_dist_ok"] is True and tn["tb_ok"] is False


def test_climax_gates_quality_flag_on_bad_weekly():
    # anchored 픽스처의 마지막 주 close 를 0(비양수)으로 오염 — quality_flag=True +
    # weekly 값 의존 게이트(p2/t1/t2/scope) None 강등 (T4/T3 는 daily 기반이라 무영향).
    # 0.0 사용(None 아님): find_anchor 의 SMA 합산이 마지막 주를 포함하는 후보(i=87)를
    # 먼저 훑는데, None 이면 sum() 이 TypeError 로 죽어 anchor 자체를 못 구한다 —
    # 0.0 은 산술상 안전하고 closes[i]>s30 조건에서 자연 탈락해 anchor(idx65) 탐색에 무영향.
    wk = _fixture_climax_run()
    wk[-1]["close"] = 0.0
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), find_anchor(wk))
    assert g["quality_flag"] is True
    assert g["p2_accel_ok"] is None and g["t2_max_volume_now"] is None and g["scope_active"] is None
    assert g["t4_ok"] is True  # daily 기반 게이트는 오염 무관


# ===== Task 4: compute_topping_gates =====

def test_topping_g0_tb_fire():
    # 40주 완만 상승(1000→1390) + 12주 드리프트-다운(1400→1220): 손계산 검증
    # (10주 SMA 를 매 주 재계산해 대조) 결과 tb=9 연속(≥TOPPING_BELOW_10W_WEEKS=8).
    # no_transition(연속 상승 후 하락이라 Stage1 재형성 없음) — anchor 비의존 G0/T-B 는 계산되고
    # anchor 의존 T-A/T-D 거래량은 None(#169).
    up = [(1000.0 + 10 * i, 100_000) for i in range(40)]
    down = _drift(12, 1400.0, 1220.0, 100_000)
    wk = _mk_weeks(up + down)
    anchor = find_anchor(wk)
    assert anchor["no_transition"] is True  # 전제 확인
    g = compute_topping_gates(wk, dist_count_25s=1, anchor=anchor)
    assert g["g0_below_10w"] is True
    assert g["tb_weeks_below_10w"] == 9
    assert g["tb_ok"] is True  # 9 ≥ TOPPING_BELOW_10W_WEEKS(8)
    assert g["ta_max_decline_now"] is None and g["td_max_down_volume_now"] is None  # #169


def test_topping_silent_without_g0():
    # 60주 내내 완만 상승 — 마지막 주 종가가 10주선 위(shakeout 아님) → G0 자체가 거짓
    # (silent): T-B 도 0 연속(직전 주가 10주선 아래가 아니므로 즉시 break).
    wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(60)])
    anchor = find_anchor(wk)
    g = compute_topping_gates(wk, dist_count_25s=5, anchor=anchor)
    assert g["g0_below_10w"] is False
    assert g["tb_weeks_below_10w"] == 0
    assert g["tb_ok"] is False


def test_topping_dist_none_conservative():
    # dist_count_25s 결측(None) → td_dist_ok 는 null=보수 원칙으로 None(0 이 아님).
    # G0/T-B 는 dist_count_25s 와 무관한 별개 입력이므로 정상 계산 유지(독립성 확인).
    wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(60)])
    anchor = find_anchor(wk)
    g = compute_topping_gates(wk, dist_count_25s=None, anchor=anchor)
    assert g["td_dist_ok"] is None
    assert g["g0_below_10w"] is False  # dist 결측과 무관하게 계산됨(독립성)


# ---- triage 회귀 고정 (PR #56 최종 리뷰 이월 — scope 엣지 2본) ----


def test_scope_high_tie_uses_most_recent_occurrence():
    """고점 동률 시 '가장 최근 발생' 기준으로 경과를 세는 확정 해석의 회귀 고정.

    최고 종가 1800 이 idx85·idx87 두 번 등장 — 최근(idx87) 기준 경과 1주(≤2)라
    scope_active=True 여야 한다. 이전 발생(idx85) 기준이면 경과 3주로 False 가 되므로
    이 픽스처는 두 해석을 판별한다(Task 3 리뷰 확정 해석의 테스트 공백 보강).
    """
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
        + [(1100.0 + 35 * i, 110_000) for i in range(1, 21)] \
        + [(1750.0, 100_000), (1800.0, 100_000), (1790.0, 100_000)]
    wk = _mk_weeks(rows)
    anchor = find_anchor(wk)
    assert anchor["anchor_week"] == wk[65]["week_end"]
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=5), anchor)
    assert g["scope_active"] is True  # 최근 고점(1주 전) 기준 — 동률 최근 채택


def test_climax_gates_anchor_at_last_week_conservative():
    """anchor 가 마지막 주(weeks_since=0)인 극단에서 보수 폴백 회귀 고정.

    성숙(maturity_ok)은 False 로 확정되고, P2 는 True 로 새지 않는다 —
    best_ever 부재 극단이 발화 전제를 만들지 못함(최종 리뷰 이월 항목).
    """
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)]
    wk = _mk_weeks(rows)
    anchor = find_anchor(wk)
    assert anchor["weeks_since"] == 0
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=5), anchor)
    assert g["maturity_ok"] is False
    assert g["p2_accel_ok"] is not True
    assert g["p2_is_steepest"] is not True


# ===== 항목 ①: compute_daily_extremes (T5·T6·TA-d 일간 극값) =====

from kr_pipeline.llm_runner.compute.climax_topping import compute_daily_extremes  # noqa: E402

_ANCHORED = {"anchor_week": "2020-01-10", "left_censored": False, "no_transition": False, "weeks_since": 20}
_NO_TRANS = {"anchor_week": None, "left_censored": False, "no_transition": True, "weeks_since": None}
_CENSORED = {"anchor_week": None, "left_censored": True, "no_transition": False, "weeks_since": None}


def _mk_daily(closes: list[float], start="2020-01-02", spreads: list[float] | None = None) -> list[dict]:
    """연속 거래일 합성 일봉(주말 무시 — 날짜 비교만 쓰인다). spreads[i] 는 high-low
    절대폭(기본 close 의 2%)."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    out = []
    for i, c in enumerate(closes):
        sp = spreads[i] if spreads is not None else c * 0.02
        out.append({"date": str(d0 + timedelta(days=i)), "open": c, "high": c + sp / 2,
                    "low": c - sp / 2, "close": c, "volume": 100_000})
    return out


def test_daily_extremes_t5_fires_on_largest_up_day():
    # baseline 상승률: +2%, +3%, (−1%), 오늘 +5% → 최대 → T5 True. 하락일 아님 → TA-d False.
    closes = [100.0, 102.0, 105.06, 104.0, 109.2]
    g = compute_daily_extremes(_mk_daily(closes), "2020-01-02", _ANCHORED)
    assert g["t5_daily_max_up_now"] is True
    assert g["ta_d_daily_max_decline_now"] is False


def test_daily_extremes_t5_silent_when_earlier_day_larger():
    closes = [100.0, 110.0, 111.0, 112.0, 115.0]  # 첫 +10% 가 최대, 오늘 +2.7%
    g = compute_daily_extremes(_mk_daily(closes), "2020-01-02", _ANCHORED)
    assert g["t5_daily_max_up_now"] is False


def test_daily_extremes_tie_fires_with_gte():
    # 상한가 동률: +30% 가 두 번(과거·오늘) — 책 문언 "larger than" 대신 >= (노출 축소 방향)
    closes = [100.0, 130.0, 130.0, 100.0, 130.0]
    g = compute_daily_extremes(_mk_daily(closes), "2020-01-02", _ANCHORED)
    assert g["t5_daily_max_up_now"] is True


def test_daily_extremes_t6_spread_ratio_uses_prev_close():
    # 절대폭 동일(4.0)이지만 prev_close 가 커진 뒤라 비율은 작아짐 → 오늘 미발화.
    closes = [100.0, 100.0, 200.0, 200.0]
    spreads = [4.0, 4.0, 4.0, 4.0]
    g = compute_daily_extremes(_mk_daily(closes, spreads=spreads), "2020-01-02", _ANCHORED)
    assert g["t6_daily_max_spread_now"] is False
    # 오늘 절대폭 8.0 → 비율 4% = 첫 baseline 일(4/100) 과 동률 → >= 발화
    spreads2 = [4.0, 4.0, 4.0, 8.0]
    g2 = compute_daily_extremes(_mk_daily(closes, spreads=spreads2), "2020-01-02", _ANCHORED)
    assert g2["t6_daily_max_spread_now"] is True


def test_daily_extremes_ta_d_fires_on_largest_decline():
    closes = [100.0, 98.0, 99.0, 97.0, 90.0]  # −2%, −2.02%, 오늘 −7.2% 최대
    g = compute_daily_extremes(_mk_daily(closes), "2020-01-02", _ANCHORED)
    assert g["ta_d_daily_max_decline_now"] is True
    assert g["t5_daily_max_up_now"] is False  # 상승일 아님 → 자격 없음(False, None 아님)


def test_daily_extremes_left_censored_all_none():
    g = compute_daily_extremes(_mk_daily([100.0, 110.0, 120.0]), "2020-01-02", _CENSORED)
    assert g == {"t5_daily_max_up_now": None, "t6_daily_max_spread_now": None,
                 "ta_d_daily_max_decline_now": None}


def test_daily_extremes_no_transition_is_none():
    # Q-8 판정: 시작점 부재 → 신호 미정의(left_censored 와 동일 처리). 주간 관례(전체 이력)와 다름.
    closes = [100.0, 120.0, 121.0, 122.0, 128.1]
    g = compute_daily_extremes(_mk_daily(closes), None, _NO_TRANS)
    assert g == {"t5_daily_max_up_now": None, "t6_daily_max_spread_now": None,
                 "ta_d_daily_max_decline_now": None}


def test_daily_extremes_quality_flag_all_none():
    # Q-5 판정: 주봉 quality_flag(close<=0/None) → anchor 의존 게이트 관례대로 None 강등.
    closes = [100.0, 102.0, 105.0, 104.0, 109.2]
    g = compute_daily_extremes(_mk_daily(closes), "2020-01-02", _ANCHORED, quality_flag=True)
    assert g == {"t5_daily_max_up_now": None, "t6_daily_max_spread_now": None,
                 "ta_d_daily_max_decline_now": None}


def test_daily_extremes_zero_bar_between_excludes_pair():
    # Q-6 판정(C): prev↔today 사이에 zero-bar(거래정지) 가 있으면 그 쌍은 baseline 극값에서 제외.
    # 행1 +60%(재개일, 직전 행0 이 zero-bar) 는 제외 → 오늘 +5% 가 최대 → True.
    closes = [100.0, 160.0, 161.0, 162.0, 170.1]
    rows = _mk_daily(closes)
    rows.insert(1, {"date": "2020-01-02T", "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0,
                    "volume": 0, "zero_bar": True})
    # insert 후 날짜 정렬 유지: zero-bar 를 행0 과 행1 사이에 두기 위해 날짜만 사이값으로 조정
    rows[1]["date"] = "2020-01-02x"  # '2020-01-02' < '2020-01-02x' < '2020-01-03' (문자열 비교)
    g = compute_daily_extremes(rows, "2020-01-02", _ANCHORED)
    assert g["t5_daily_max_up_now"] is True
    # 같은 이력에서 zero-bar 가 없으면 +60% 가 baseline 최대 → False (대조)
    assert compute_daily_extremes(_mk_daily(closes), "2020-01-02", _ANCHORED)["t5_daily_max_up_now"] is False


def test_daily_extremes_today_is_resumption_day_all_none():
    # Q-6: 오늘이 재개일(직전 행이 zero-bar) 이면 3신호 None.
    closes = [100.0, 102.0, 103.0]
    rows = _mk_daily(closes)
    rows.insert(2, {"date": "2020-01-03x", "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0,
                    "volume": 0, "zero_bar": True})
    g = compute_daily_extremes(rows, "2020-01-02", _ANCHORED)
    assert g == {"t5_daily_max_up_now": None, "t6_daily_max_spread_now": None,
                 "ta_d_daily_max_decline_now": None}


def test_daily_extremes_mixed_adjustment_row_excluded_from_t6_only():
    # Q-7 판정(A): high·low 가 raw 대체(adj_hl=False) 인 행은 T6 공식 유효성 미충족 → 스프레드
    # 후보 제외. T5/TA-d(종가만 사용) 는 영향 없음.
    closes = [100.0, 101.0, 102.0, 103.0]
    spreads = [2.0, 40.0, 2.0, 3.0]  # 행1 은 분할 전 raw 폭(10×) 혼입 가정
    rows = _mk_daily(closes, spreads=spreads)
    rows[1]["adj_hl"] = False
    g = compute_daily_extremes(rows, "2020-01-02", _ANCHORED)
    assert g["t6_daily_max_spread_now"] is True   # 혼합 행 제외 → 오늘 3/102 가 최대
    assert g["t5_daily_max_up_now"] is False      # 행1 +1% > 오늘 +0.98% — 종가 판정은 유지
    rows[1]["adj_hl"] = True
    assert compute_daily_extremes(rows, "2020-01-02", _ANCHORED)["t6_daily_max_spread_now"] is False
    # 오늘 자체가 혼합 행이면 T6 만 None
    rows[-1]["adj_hl"] = False
    g3 = compute_daily_extremes(rows, "2020-01-02", _ANCHORED)
    assert g3["t6_daily_max_spread_now"] is None and g3["t5_daily_max_up_now"] is False


def test_daily_extremes_baseline_start_includes_anchor_week_first_day():
    # 행 0 은 baseline 이전(prev_close 공급용). 행 1(=anchor 주 첫 거래일) +20% 가 포함되어야
    # 오늘 +5% 는 미발화. 시작일을 행 2 로 옮기면(첫 거래일 배제) 오늘이 최대 → 발화.
    closes = [100.0, 120.0, 121.0, 122.0, 128.1]
    rows = _mk_daily(closes)
    assert compute_daily_extremes(rows, rows[1]["date"], _ANCHORED)["t5_daily_max_up_now"] is False
    assert compute_daily_extremes(rows, rows[2]["date"], _ANCHORED)["t5_daily_max_up_now"] is True


def test_daily_extremes_first_baseline_day_uses_prior_row_prev_close():
    # baseline 첫날(행 1)의 상승률은 행 0(baseline 이전) 종가 대비로 계산돼야 한다.
    closes = [100.0, 130.0, 131.0]  # 행1 +30%(prev=행0), 오늘 +0.8%
    rows = _mk_daily(closes)
    assert compute_daily_extremes(rows, rows[1]["date"], _ANCHORED)["t5_daily_max_up_now"] is False


def test_daily_extremes_insufficient_rows_none():
    assert compute_daily_extremes([], "2020-01-02", _ANCHORED)["t5_daily_max_up_now"] is None
    assert compute_daily_extremes(None, "2020-01-02", _ANCHORED)["t6_daily_max_spread_now"] is None
    one = _mk_daily([100.0])
    assert compute_daily_extremes(one, one[0]["date"], _ANCHORED)["ta_d_daily_max_decline_now"] is None


# ===== #158 Fix α: find_anchor 결합식에서 C4(30/40주 SMA 턴업) 제거 =====

from kr_pipeline.llm_runner.compute.climax_topping import _sma  # noqa: E402

def _fixture_reentry():
    """옛 사이클(돌파 idx65) → 60주 하락 드리프트(SMA40 아래·평탄/하락) → 재돌파(2.6×vol,
    close>SMA30/40) → 10주 상승. Phase B 179행 패턴: 재돌파 주에 C1∧C2∧C3∧C5 는 성립하나
    C4(SMA30/40 이 4주 전보다 높음) 는 하락 직후라 불성립."""
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
         + [(1100.0 + 15 * i, 110_000) for i in range(1, 20)] \
         + _drift(60, 1000.0, 800.0) \
         + [(950.0, 260_000)] \
         + [(950.0 + 10 * i, 110_000) for i in range(1, 11)]
    return _mk_weeks(rows), 65, 65 + 20 + 60  # (weekly, old_anchor_idx, reentry_idx)


def test_anchor_reentry_moves_to_current_cycle():
    wk, old_idx, re_idx = _fixture_reentry()
    r = find_anchor(wk)
    assert r["anchor_week"] == wk[re_idx]["week_end"]
    assert r["weeks_since"] == len(wk) - 1 - re_idx
    # 재돌파 주에서 C4 는 실제로 불성립(하락 직후 SMA30/40 이 4주 전보다 낮음) — Fix α 로만 잡힘
    closes = [w["close"] for w in wk]
    s30, s30p = _sma(closes, re_idx, 30), _sma(closes, re_idx - 4, 30)
    assert s30 <= s30p


def test_anchor_unchanged_without_reentry():
    # 252행 패턴: 옛 돌파 이후 Stage 1 재진입이 없으면 앵커 불변
    wk = _fixture_single_transition()
    assert find_anchor(wk)["anchor_week"] == wk[65]["week_end"]


def test_anchor_never_moves_earlier_as_history_extends():
    # 선행 이동 불가 가드: 이력을 뒤로 늘려도 앵커 week_end 는 단조 비감소
    wk, old_idx, re_idx = _fixture_reentry()
    last = None
    for cut in range(old_idx + 1, len(wk) + 1):
        a = find_anchor(wk[:cut])
        if a["anchor_week"] is None:
            continue
        assert last is None or a["anchor_week"] >= last
        last = a["anchor_week"]
    assert find_anchor(wk[:old_idx + 5])["anchor_week"] == wk[old_idx]["week_end"]
    assert last == wk[re_idx]["week_end"]


def test_anchor_catches_breakout_where_c4_fails():
    # 65주 급한 하락(1000→700) 직후 돌파 800(2.6×vol): C1(4주 연속 <SMA40)·C2(평탄/하락)·
    # C3(거래량)·C5(close>SMA30/40) 성립, C4 불성립 → Fix α 앵커 = 돌파 주
    rows = _drift(65, 1000.0, 700.0) + [(800.0, 260_000)] + [(800.0 + 5 * i, 110_000) for i in range(1, 6)]
    wk = _mk_weeks(rows)
    closes = [w["close"] for w in wk]
    i = 65
    assert closes[i] > _sma(closes, i, 30) and closes[i] > _sma(closes, i, 40)   # C5
    assert _sma(closes, i, 30) <= _sma(closes, i - 4, 30)                          # C4 불성립
    r = find_anchor(wk)
    assert r["anchor_week"] == wk[i]["week_end"] and r["no_transition"] is False


def test_anchor_three_modes_regression_after_fix_alpha():
    assert find_anchor(_mk_weeks(_drift(40, 1000.0, 980.0)))["left_censored"] is True
    assert find_anchor(_mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(80)]))["no_transition"] is True
    a = find_anchor(_fixture_single_transition())
    assert a["left_censored"] is False and a["no_transition"] is False and a["weeks_since"] == 19


# ===== #156: T1 주간 스프레드 절대값 → 비율((high−low)/prev_week_close) =====

def _t1_abs(weekly, start_idx):
    """구 정의(절대값) 재현 — 픽스처가 구 정의에서 발화함을 테스트 안에서 확인하기 위한 보조."""
    spreads = [w["high"] - w["low"] for w in weekly]
    return spreads[-1] >= max(spreads[start_idx:])


def test_t1_ratio_silent_where_absolute_fires():
    # 마지막 주 절대폭 78(1950×4%) 이 baseline 최대(절대값 정의 → True) 이지만, 저가 구간의
    # 60/1100=5.45% 가 마지막 주 78/1700=4.59% 보다 크므로 비율 정의 → False (후반부 자동 발화 제거).
    wk = _fixture_climax_run()
    wk[66]["high"], wk[66]["low"] = 1145.0, 1085.0
    a = find_anchor(wk); start_idx = len(wk) - 1 - a["weeks_since"]
    assert _t1_abs(wk, start_idx) is True
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), a)
    assert g["t1_max_spread_now"] is False
    assert g["t2_max_volume_now"] is True  # T2 절대값 불변


def test_t1_ratio_fires_and_tie_gte():
    wk = _fixture_climax_run()  # 마지막 주 4.59% 가 baseline 최대 → True
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), find_anchor(wk))
    assert g["t1_max_spread_now"] is True
    # 동률(>=): 66주 비율 275/1100 = 25% (이진 정확), 마지막 주 425/1700 = 25% → 발화
    wk2 = _fixture_climax_run()
    wk2[66]["high"], wk2[66]["low"] = wk2[66]["close"] + 137.5, wk2[66]["close"] - 137.5
    wk2[-1]["high"], wk2[-1]["low"] = wk2[-1]["close"] + 212.5, wk2[-1]["close"] - 212.5
    assert (wk2[66]["high"] - wk2[66]["low"]) / wk2[65]["close"] == (wk2[-1]["high"] - wk2[-1]["low"]) / wk2[-2]["close"]
    g2 = compute_climax_gates(wk2, _mk_daily_updays(10, up=8), find_anchor(wk2))
    assert g2["t1_max_spread_now"] is True
    # 마지막 주를 한 틱 좁히면 미발화 (엄격 비교가 아니라 >= 임을 양방향으로 고정)
    wk2[-1]["high"] -= 1.0
    assert compute_climax_gates(wk2, _mk_daily_updays(10, up=8), find_anchor(wk2))["t1_max_spread_now"] is False


def test_t1_none_when_today_is_resumption_week():
    wk = _fixture_climax_run()
    wk[-1]["gap_before"] = True  # 직전에 zero-bar 주(거래정지) 존재 → prev_close 불연속
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), find_anchor(wk))
    assert g["t1_max_spread_now"] is None
    assert g["t2_max_volume_now"] is True and g["p2_accel_ok"] is True  # 다른 게이트 무영향


def test_t1_gap_pair_inside_baseline_excluded():
    # baseline 안의 재개 주(66) 가 거대 비율이어도 쌍 제외 → 마지막 주가 최대로 발화
    wk = _fixture_climax_run()
    wk[66]["high"], wk[66]["low"], wk[66]["gap_before"] = 1300.0, 900.0, True
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), find_anchor(wk))
    assert g["t1_max_spread_now"] is True


def test_t1_mixed_adjustment_week_excluded():
    wk = _fixture_climax_run()
    wk[66]["high"], wk[66]["low"], wk[66]["adj_hl"] = 1300.0, 900.0, False  # raw 대체 주 → 제외
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), find_anchor(wk))
    assert g["t1_max_spread_now"] is True
    wk[-1]["adj_hl"] = False  # 오늘이 혼합 주 → T1 만 None
    g2 = compute_climax_gates(wk, _mk_daily_updays(10, up=8), find_anchor(wk))
    assert g2["t1_max_spread_now"] is None and g2["t2_max_volume_now"] is True


def test_t1_three_modes_regression():
    lc = compute_climax_gates(_mk_weeks(_drift(40, 1000.0, 980.0)), _mk_daily_updays(10, up=5),
                              find_anchor(_mk_weeks(_drift(40, 1000.0, 980.0))))
    assert lc["t1_max_spread_now"] is None
    nt_wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(80)])
    nt = compute_climax_gates(nt_wk, _mk_daily_updays(10, up=5), find_anchor(nt_wk))
    # (#169) no_transition 은 anchor 의존 → None(구: 전체 이력 기준 bool)
    assert nt["baseline"] == "no_transition" and nt["t1_max_spread_now"] is None
    wk = _fixture_climax_run(); wk[-1]["close"] = 0.0
    q = compute_climax_gates(wk, _mk_daily_updays(10, up=8), find_anchor(wk))
    assert q["quality_flag"] is True and q["t1_max_spread_now"] is None
