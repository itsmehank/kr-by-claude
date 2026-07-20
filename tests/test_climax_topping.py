# tests/test_climax_topping.py
"""(#44 D1) find_anchor — climax/topping anchor 전 이력 탐색 단위테스트.

가장 최근 Stage 1→2 전환 주를 anchor 로 잡는 순수 함수. 드리프트-다운 픽스처로
close<SMA 엄격 부등호가 항상 성립하도록 구성(정확 상수 평탄 구간은 부동소수/SMA
경계에서 부등호가 깨질 수 있음).
"""
from kr_pipeline.llm_runner.compute.climax_topping import find_anchor


def _mk_weeks(rows: list[tuple[float, int]], start="2018-01-05") -> list[dict]:
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [{"week_end": str(d0 + timedelta(weeks=i)), "open": p, "high": p * 1.02,
             "low": p * 0.98, "close": p, "volume": v} for i, (p, v) in enumerate(rows)]


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
