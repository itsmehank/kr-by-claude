"""P2-1b — KR vs US 지수 intermediate correction 낙폭 측정 (read-only).

Q0: 한국 지수의 전형적 intermediate correction 낙폭이 미국과 유사한가?

세 가지 탐지 정의로 각각 측정하여 결과 민감도를 본다 (탐지방법이 결과를 좌우하므로):
  A. drawdown-episode : running-peak→trough→recovery, depth∈[5%,25%], peak→trough ≥15 거래일
  B. rolling-window   : cup 전형 길이(7/16/25주) 윈도우별 max peak-to-trough drawdown 분포
  C. zigzag (θ=5%)    : 5% 반전 임계 swing pivot, 각 high→low 하락스윙 depth∈[5%,25%]
                        (자체 대안 — 근거: 책이 기술하는 '시각적 차트 판독'에 부합,
                         local swing high 기준이라 진행중 상승추세 내 중간조정 포착,
                         repo 가 P2-3 VCP footprint 용으로 이미 채택한 primitive 재사용)

모든 정의를 KOSPI/KOSDAQ/SP500/NASDAQ_COMP 에 동일 파라미터로 적용 (apples-to-apples).
close-to-close 기준 (index_daily 와 동일, KR 초기 OHLC=0 문제 회피).
σ / ratio-clamp (P2-1a) 는 차원이 달라 재사용하지 않음 — 여기는 누적 지수 낙폭.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent / "data"
INDICES = ["KOSPI", "KOSDAQ", "SP500", "NASDAQ_COMP"]

DEPTH_MIN = 5.0      # %, intermediate correction 하한
DEPTH_MAX = 25.0     # %, 초과는 major bear (≤50% 예외 조항 영역) → 제외
MIN_TROUGH_DAYS = 15  # 거래일, def A peak→trough 최소 지속
ZIGZAG_THETA = 5.0   # %, def C 반전 임계
ROLL_WEEKS = [7, 16, 25]  # def B cup 전형 길이
TD_PER_WEEK = 5      # 거래일/주 근사


def load_close(name: str) -> pd.Series:
    df = pd.read_csv(DATA / f"{name}.csv", parse_dates=["date"])
    s = df.set_index("date")["close"].astype(float)
    s = s[s > 0].sort_index()  # KR 초기 0.0 OHLC 행 방어 (close 는 base 100 부터 유효)
    return s


# ---------- Def A: drawdown episodes (running-peak → trough → recovery) ----------
def episodes(close: pd.Series) -> pd.DataFrame:
    """running peak 를 기준으로 한 underwater episode 분할.
    새 고점 갱신 시 직전 episode 종료. 각 episode: depth, peak→trough 거래일."""
    vals = close.values
    n = len(vals)
    out = []
    peak = vals[0]
    peak_i = 0
    trough = vals[0]
    trough_i = 0
    in_dd = False
    for i in range(1, n):
        p = vals[i]
        if p >= peak:
            # 고점 회복/갱신 → 진행중 episode 종료
            if in_dd:
                depth = (peak - trough) / peak * 100.0
                dur = trough_i - peak_i
                out.append((depth, dur, peak_i, trough_i, i))
            peak = p
            peak_i = i
            trough = p
            trough_i = i
            in_dd = False
        else:
            in_dd = True
            if p < trough:
                trough = p
                trough_i = i
    # 미회복(진행중) episode 는 미완결 → 제외
    df = pd.DataFrame(out, columns=["depth", "trough_days", "peak_i", "trough_i", "recover_i"])
    return df[(df.depth >= DEPTH_MIN) & (df.depth <= DEPTH_MAX) & (df.trough_days >= MIN_TROUGH_DAYS)]


# ---------- Def B: rolling-window max drawdown ----------
def rolling_maxdd(close: pd.Series, window: int) -> np.ndarray:
    """각 길이 window 윈도우 내 max peak-to-trough drawdown (%)."""
    vals = close.values
    n = len(vals)
    res = []
    for start in range(0, n - window + 1):
        w = vals[start:start + window]
        run_max = np.maximum.accumulate(w)
        dd = (run_max - w) / run_max * 100.0
        res.append(dd.max())
    return np.array(res)


# ---------- Def C: zigzag swing detection (θ% reversal) ----------
def zigzag_downswings(close: pd.Series, theta: float) -> np.ndarray:
    """θ% 반전 임계 zigzag. 확정된 swing high→low 하락스윙 depth (%) 만 반환."""
    vals = close.values
    n = len(vals)
    if n == 0:
        return np.array([])
    pivots = []  # (idx, price, kind) kind: 'H'/'L'
    last_ext_i = 0
    last_ext = vals[0]
    direction = 0  # +1 up, -1 down, 0 unknown
    for i in range(1, n):
        p = vals[i]
        if direction >= 0:
            # 상승/미정: 신고가 추적
            if p > last_ext:
                last_ext = p
                last_ext_i = i
            elif (last_ext - p) / last_ext * 100.0 >= theta:
                # high 확정
                pivots.append((last_ext_i, last_ext, "H"))
                direction = -1
                last_ext = p
                last_ext_i = i
        if direction <= 0:
            if p < last_ext:
                last_ext = p
                last_ext_i = i
            elif (p - last_ext) / last_ext * 100.0 >= theta:
                # low 확정
                pivots.append((last_ext_i, last_ext, "L"))
                direction = 1
                last_ext = p
                last_ext_i = i
    # high→low 하락스윙 depth
    depths = []
    for a, b in zip(pivots, pivots[1:]):
        if a[2] == "H" and b[2] == "L":
            depths.append((a[1] - b[1]) / a[1] * 100.0)
    d = np.array(depths)
    return d[(d >= DEPTH_MIN) & (d <= DEPTH_MAX)]


def quantiles(arr) -> dict:
    a = np.asarray(arr, dtype=float)
    if len(a) == 0:
        return {"n": 0, "median": np.nan, "q1": np.nan, "q3": np.nan, "p90": np.nan}
    return {
        "n": len(a),
        "median": float(np.median(a)),
        "q1": float(np.percentile(a, 25)),
        "q3": float(np.percentile(a, 75)),
        "p90": float(np.percentile(a, 90)),
    }


def run(period_label: str, start: str | None):
    print(f"\n{'='*78}\n## 기간: {period_label}\n{'='*78}")
    series = {}
    for name in INDICES:
        s = load_close(name)
        if start:
            s = s[s.index >= pd.Timestamp(start)]
        series[name] = s
        print(f"  {name:12s} {s.index.min().date()} ~ {s.index.max().date()}  ({len(s)} 거래일)")

    # Def A
    print("\n### Def A — drawdown-episode (depth∈[5,25]%, peak→trough ≥15d)")
    print(f"{'index':12s} {'n':>4s} {'median':>8s} {'Q1':>7s} {'Q3':>7s} {'90p':>7s}")
    rA = {}
    for name in INDICES:
        q = quantiles(episodes(series[name]).depth.values)
        rA[name] = q
        print(f"{name:12s} {q['n']:>4d} {q['median']:>8.2f} {q['q1']:>7.2f} {q['q3']:>7.2f} {q['p90']:>7.2f}")

    # Def B
    print("\n### Def B — rolling-window max drawdown (per window)")
    rB = {}
    for wk in ROLL_WEEKS:
        w = wk * TD_PER_WEEK
        print(f"  -- window {wk}주 ({w}거래일) --")
        print(f"  {'index':12s} {'n':>5s} {'median':>8s} {'Q1':>7s} {'Q3':>7s} {'90p':>7s} {'%>25':>6s}")
        for name in INDICES:
            dd = rolling_maxdd(series[name], w)
            q = quantiles(dd)  # 주의: B 는 cap 미적용 (전체 분포)
            pct_over = float((dd > DEPTH_MAX).mean() * 100) if len(dd) else float("nan")
            rB[(wk, name)] = (q, pct_over)
            print(f"  {name:12s} {q['n']:>5d} {q['median']:>8.2f} {q['q1']:>7.2f} {q['q3']:>7.2f} {q['p90']:>7.2f} {pct_over:>6.1f}")

    # Def C
    print("\n### Def C — zigzag downswing (θ=5%, depth∈[5,25]%)")
    print(f"{'index':12s} {'n':>4s} {'median':>8s} {'Q1':>7s} {'Q3':>7s} {'90p':>7s}")
    rC = {}
    for name in INDICES:
        q = quantiles(zigzag_downswings(series[name], ZIGZAG_THETA))
        rC[name] = q
        print(f"{name:12s} {q['n']:>4d} {q['median']:>8.2f} {q['q1']:>7.2f} {q['q3']:>7.2f} {q['p90']:>7.2f}")

    # KR/US median 비율 (자연 페어링 + 교차)
    print("\n### KR median ÷ US median 비율 (median 기준)")
    def med(r, name):
        return r[name]["median"]
    pairs = [("KOSPI", "SP500"), ("KOSDAQ", "NASDAQ_COMP"), ("KOSPI", "NASDAQ_COMP"), ("KOSDAQ", "SP500")]
    print(f"{'pair (KR/US)':24s} {'A':>7s} {'C':>7s} {'B16w':>7s}")
    for kr, us in pairs:
        ra = med(rA, kr) / med(rA, us) if med(rA, us) else float("nan")
        rc = med(rC, kr) / med(rC, us) if med(rC, us) else float("nan")
        b_kr = rB[(16, kr)][0]["median"]; b_us = rB[(16, us)][0]["median"]
        rb = b_kr / b_us if b_us else float("nan")
        print(f"{kr+'/'+us:24s} {ra:>7.2f} {rc:>7.2f} {rb:>7.2f}")


if __name__ == "__main__":
    # 1차 비교 기준: 공통 기간 (KOSDAQ inception 1996-07 ~)
    run("공통 1996-07 ~ 2026-05 (KOSDAQ inception, 1차 비교 기준)", "1996-07-01")
    # 보조: 전체 역사 (지수별 상이 — KOSDAQ 만 1996, 나머지 1980)
    run("전체 역사 (지수별 상이 시작, 보조)", None)
