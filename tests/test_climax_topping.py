# tests/test_climax_topping.py
"""(#44 D1) find_anchor — climax/topping anchor 전 이력 탐색 단위테스트.

가장 최근 Stage 1→2 전환 주를 anchor 로 잡는 순수 함수. 드리프트-다운 픽스처로
close<SMA 엄격 부등호가 항상 성립하도록 구성(정확 상수 평탄 구간은 부동소수/SMA
경계에서 부등호가 깨질 수 있음).
"""
from kr_pipeline.llm_runner.compute.climax_topping import compute_climax_gates, find_anchor


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


def test_climax_gates_no_transition_presumes_p1():
    wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(80)])
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=5), find_anchor(wk))
    assert g["baseline"] == "no_transition" and g["maturity_ok"] is True  # 간주(원 규칙)


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
