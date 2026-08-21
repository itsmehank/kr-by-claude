"""#115 P1 — 승자 리콜·후보 축소율 순수 함수 테스트 (5차 봉인 자구 기준)."""
from datetime import date

import pytest

from kr_pipeline.backtest.p1_recall import (
    interval_recall, pass_window, winner_cells_sealed,
)


def test_pass_window_boundary_sealed():
    # 봉인 자구: (anchor−28역일, anchor 직전 거래일] — 개구간 하한·anchor 당일 제외
    trading = [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 30),
               date(2026, 2, 2), date(2026, 2, 27)]
    anchor = date(2026, 2, 27)                          # anchor-28 = 1/30
    w = pass_window(trading, anchor, days=28)
    assert w == [date(2026, 2, 2)]                      # 1/30(하한 당일)·2/27(당일) 제외


def test_pass_window_open_lower_bound():
    # anchor−28 정확히 그 날짜는 제외(개구간), 그 다음 거래일부터 포함
    trading = [date(2026, 1, 30), date(2026, 1, 31), date(2026, 2, 27)]
    w = pass_window(trading, date(2026, 2, 27), days=28)
    assert date(2026, 1, 30) not in w                   # anchor-28 당일 = 하한 개구간
    assert date(2026, 1, 31) in w


def test_winner_cells_sealed_definition():
    # 13주 초과 +40%p AND 절대>0 — 시장 0% 가정, 유동성 통과 가정
    anchors = [date(2025, 1, 3), date(2025, 4, 4), date(2025, 7, 4),
               date(2026, 1, 2)]
    # i=0 에서 13주(i+1) 수익 +50% → 승자. i=1 은 13주 뒤 -10% → 아님.
    closes = {anchors[0]: 100.0, anchors[1]: 150.0, anchors[2]: 135.0,
              anchors[3]: 135.0}
    idx = {a: 100.0 for a in anchors}
    cells = winner_cells_sealed(anchors, closes, idx, idx13=1, idx26=2,
                                liq_ok=lambda a: True)
    assert 0 in cells and 1 not in cells
    # 절대수익 >0 필수: 시장 -60% 에서 종목 -10% (초과 +50%p) → 승자 아님
    closes2 = {anchors[0]: 100.0, anchors[1]: 90.0, anchors[2]: 90.0,
               anchors[3]: 90.0}
    idx2 = {anchors[0]: 100.0, anchors[1]: 40.0, anchors[2]: 40.0,
            anchors[3]: 40.0}
    assert winner_cells_sealed(anchors, closes2, idx2, idx13=1, idx26=2,
                               liq_ok=lambda a: True) == []


def test_interval_recall_sealed():
    # 생존 80건 중 60 통과, 상폐 20건 미판정 → 헤드라인 0.75,
    # 구간 [60/100, 80/100] (전원 미통과 → min, 전원 통과 → max)
    r = interval_recall(passed=60, survivors=80, delisted=20)
    assert r["headline"] == pytest.approx(0.75)
    assert r["interval"] == (pytest.approx(0.60), pytest.approx(0.80))
    # 상폐 0 이면 구간 = 헤드라인 점
    r2 = interval_recall(passed=60, survivors=80, delisted=0)
    assert r2["interval"] == (pytest.approx(0.75), pytest.approx(0.75))
