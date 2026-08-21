# kr_pipeline/backtest/p1_recall.py
"""#115 P1 — 승자 리콜·후보 축소율 순수 함수 (5차 봉인 자구 구현).

- 승자 정의(4차 봉인, recall 감사 재사용): 13주 시장초과 ≥ +40%p 또는 26주
  ≥ +50%p, 해당 창 절대수익 > 0 필수, 유동성 하한 10억(호출자 판정 주입).
- 통과 상태 윈도우(5차 ⑤): (anchor−28역일, anchor 직전 거래일] — 개구간
  하한, anchor 당일 제외.
- 리콜 구간 보고(5차 ④): 상폐 승자 미판정 → [전원 미통과 min, 전원 통과 max].
"""
from __future__ import annotations

from datetime import date, timedelta

T13, T26 = 0.40, 0.50          # 4차 봉인 — 변경 금지
MERGE_GAP_WEEKS = 4            # recall 1차 잠금 승계
PASS_WINDOW_DAYS = 28          # 5차 ⑤ 봉인


def pass_window(trading_dates: list[date], anchor: date,
                days: int = PASS_WINDOW_DAYS) -> list[date]:
    """통과 상태 판정 대상 거래일: (anchor−days, anchor) 개구간·당일 제외."""
    lo = anchor - timedelta(days=days)
    return [d for d in trading_dates if lo < d < anchor]


def winner_cells_sealed(anchors: list[date], closes: dict[date, float],
                        idx: dict[date, float], *, idx13: int, idx26: int,
                        liq_ok) -> list[int]:
    """봉인 정의의 승자 셀 인덱스. idx13/idx26 = 13·26주에 해당하는 anchor
    오프셋(주 단위 anchor 리스트 기준 13, 26 — 테스트는 축약 오프셋 주입).
    우측 절단(5차 ⑥): i+오프셋이 anchor 범위를 벗어나면 그 지표는 평가 불가.
    """
    out = []
    for i, a in enumerate(anchors):
        c0, x0 = closes.get(a), idx.get(a)
        if not c0 or not x0 or not liq_ok(a):
            continue
        win = False
        for off, thr in ((idx13, T13), (idx26, T26)):
            j = i + off
            if j >= len(anchors):
                continue                    # 우측 절단 — 평가 불가
            c1, x1 = closes.get(anchors[j]), idx.get(anchors[j])
            if not c1 or not x1:
                continue
            ret = c1 / c0 - 1
            exc = ret - (x1 / x0 - 1)
            if ret > 0 and exc >= thr:
                win = True
                break
        if win:
            out.append(i)
    return out


def merge_episodes(cell_idx: list[int],
                   gap: int = MERGE_GAP_WEEKS) -> list[tuple[int, int]]:
    """승자 셀 → 에피소드 [시작, 끝] (gap 주 이내 병합 — recall 1차 잠금)."""
    if not cell_idx:
        return []
    eps = [[cell_idx[0], cell_idx[0]]]
    for i in cell_idx[1:]:
        if i - eps[-1][1] <= gap:
            eps[-1][1] = i
        else:
            eps.append([i, i])
    return [(a, b) for a, b in eps]


def interval_recall(*, passed: int, survivors: int, delisted: int) -> dict:
    """5차 ④ 구간 보고. headline = 생존 리콜, interval = 상폐 전원 미통과/통과."""
    total = survivors + delisted
    return {
        "headline": passed / survivors if survivors else None,
        "interval": ((passed / total if total else None),
                     ((passed + delisted) / total if total else None)),
        "survivors": survivors, "passed": passed, "delisted": delisted,
    }
