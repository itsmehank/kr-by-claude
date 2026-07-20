# kr_pipeline/llm_runner/compute/climax_topping.py
"""(#44 D1) climax/topping anchor 전 이력 탐색 — 순수 함수.

순수 함수 — DB 접근 없음, pandas 미사용(리스트 산술만). 주봉 이력에서 가장 최근
Stage 1→2 전환 주(anchor)를 뒤에서부터 탐색한다. 확정 D1: "전 이력 중 가장 최근"
전환을 anchor 로 채택 — 과거의 오래된 전환은 이후 Stage 4 재하락으로 무효화된 것으로
간주(test_anchor_resets_after_stage4).

null 규약(보수): 이력이 CLIMAX_ANCHOR_VOL_AVG_WEEKS(50)주 이하 = 탐색 자체가 불가능한
결측 → left_censored=True, 게이트 전부 None. 이력은 충분하나 전환 조건을 만족하는 주가
없으면(예: 줄곧 Stage 2 상승) no_transition=True — 원 규칙 보존을 위해 P1(선행조건)
충족으로 간주하는 모드(anchor_week=None 이지만 게이트 거부가 아님).

탐색 하한 `range(n - 1, W - 1, -1)`: i=W(=50) 포함 — off-by-one 가드. i 를 W-1까지로
좁히면 n=W+1(=51) 부근에서 유효한 i=W 후보를 건너뛰어 no_transition 으로 폴스루하는
회귀가 발생한다(라운드 2 리뷰 N2 발견).

anchor 판정(가장 최근 주 w, index i):
- Stage1 재형성: 직전 CLIMAX_ANCHOR_STAGE1_MIN_WEEKS(4)주 연속 close < 그 주의 40주 SMA
- 40주 SMA 의 TURNUP_WEEKS(4)주 기울기 ≤ +CLIMAX_ANCHOR_FLAT_BAND_PCT(2.0)% (평탄/하락)
- w 에서 volume ≥ BREAKOUT_VOL_FLOOR × 50주 평균 거래량 (돌파 거래량)
- s30/s40 이 TURNUP_WEEKS(4)주 전 대비 상승 AND close > s30, s40 (턴업 확정)
"""
from __future__ import annotations

from kr_pipeline.common.thresholds import (
    BREAKOUT_VOL_FLOOR,
    CLIMAX_ANCHOR_FLAT_BAND_PCT,
    CLIMAX_ANCHOR_STAGE1_MIN_WEEKS,
    CLIMAX_ANCHOR_TURNUP_WEEKS,
    CLIMAX_ANCHOR_VOL_AVG_WEEKS,
)


def _sma(vals: list[float], i: int, n: int) -> float | None:
    """vals[i] 를 마지막으로 하는 n 주 단순이동평균. 창이 부족하면 None."""
    return sum(vals[i - n + 1 : i + 1]) / n if i + 1 >= n else None


def find_anchor(weekly: list[dict]) -> dict:
    """주봉 이력(오름차순)에서 가장 최근 Stage 1→2 전환 주를 탐색한다.

    weekly: [{week_end, open, high, low, close, volume}, ...] (adj 전 이력, zero-bar 제외 입력)
    반환: {"anchor_week": str|None, "left_censored": bool, "no_transition": bool,
           "weeks_since": int|None}
    """
    closes = [w["close"] for w in weekly]
    vols = [w["volume"] or 0 for w in weekly]
    n = len(weekly)
    W = CLIMAX_ANCHOR_VOL_AVG_WEEKS
    if n <= W:  # 이력 ≤50주 = 탐색 불가 결측 (실효 경계 문서 일치 — 검토 하 수리)
        return {"anchor_week": None, "left_censored": True,
                "no_transition": False, "weeks_since": None}
    k = CLIMAX_ANCHOR_TURNUP_WEEKS
    s1 = CLIMAX_ANCHOR_STAGE1_MIN_WEEKS
    for i in range(n - 1, W - 1, -1):  # i=W(=50) 포함 — n=51 폴스루가 no_transition(P1 간주)으로 새는 회귀 방지(라운드 2 N2)
        s30, s40 = _sma(closes, i, 30), _sma(closes, i, 40)
        s30p, s40p = _sma(closes, i - k, 30), _sma(closes, i - k, 40)
        v_avg = sum(vols[i - W : i]) / W
        if None in (s30, s40, s30p, s40p) or v_avg <= 0:
            continue
        # Stage1 재형성: 직전 s1(4)주 연속 close < 그 주의 40주 SMA (검토 중6)
        stage1 = all(
            (sm := _sma(closes, j, 40)) is not None and closes[j] < sm
            for j in range(i - s1, i))
        prev_s40, prev_s40k = _sma(closes, i - 1, 40), _sma(closes, i - 1 - k, 40)
        slope_ok = (prev_s40 and prev_s40k
                    and (prev_s40 - prev_s40k) / prev_s40k * 100 <= CLIMAX_ANCHOR_FLAT_BAND_PCT)
        if (stage1 and slope_ok and vols[i] >= BREAKOUT_VOL_FLOOR * v_avg
                and s30 > s30p and s40 > s40p
                and closes[i] > s30 and closes[i] > s40):
            return {"anchor_week": weekly[i]["week_end"], "left_censored": False,
                    "no_transition": False, "weeks_since": n - 1 - i}
    return {"anchor_week": None, "left_censored": False,
            "no_transition": True, "weeks_since": None}
