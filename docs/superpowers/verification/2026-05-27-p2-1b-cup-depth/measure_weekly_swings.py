"""P2-1d (가칭) — wide_and_loose '주간 봉 스윙 폭' KR vs US 측정 (read-only).

wide_and_loose 의 operative 임계는 'Weekly price swings > 10–15% during the base'
= 주간 봉폭 (bar-volatility). 분모가 *주간 봉폭* 이지 일간 σ 가 아니다.
→ P2-1a 의 일간 σ-ratio (2.3×) 재사용 금지. 일간 σ ×√5 단순환산도 금지
  (자기상관 의존). cup depth 와 같은 '차원 함정' 회피 — 주간 봉폭을 직접 잰다.

두 metric (literal 해석 민감도):
  (i)  weekly range %       = (weekly_high - weekly_low) / weekly_close × 100
                              ← '주간 봉 스윙 폭' 의 가장 직접적 해석 (봉의 시각적 폭)
  (ii) weekly |close ret| % = |weekly_close.pct_change()| × 100
                              ← 'week-to-week swing' 해석

데이터: P2-1b 장기 캐시 (data/*.csv) 를 주간(W-FRI) 리샘플.
  - KR 초기 OHLC=0 → range metric 은 valid-OHLC (KOSPI 1994-10/KOSDAQ 1996-07~) 만.
  - 1차 비교 = 공통 기간 1996-07~2026-05 (P2-1b 와 정렬).
  - weekly_index DB(105주) 는 너무 짧아 캐시 리샘플로 보강.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent / "data"
INDICES = ["KOSPI", "KOSDAQ", "SP500", "NASDAQ_COMP"]
PAIRS = [("KOSPI", "SP500"), ("KOSDAQ", "NASDAQ_COMP")]
COMMON_START = "1996-07-01"


def weekly(name: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{name}.csv", parse_dates=["date"]).set_index("date").sort_index()
    df = df[df["close"] > 0]
    wk = pd.DataFrame({
        "open": df["open"].resample("W-FRI").first(),
        "high": df["high"].resample("W-FRI").max(),
        "low": df["low"].resample("W-FRI").min(),
        "close": df["close"].resample("W-FRI").last(),
    }).dropna(subset=["close"])
    return wk


def quant(arr) -> dict:
    a = np.asarray(arr, dtype=float)
    a = a[~np.isnan(a)]
    if len(a) == 0:
        return dict(n=0, median=np.nan, q1=np.nan, q3=np.nan, p90=np.nan)
    return dict(n=len(a), median=float(np.median(a)), q1=float(np.percentile(a, 25)),
                q3=float(np.percentile(a, 75)), p90=float(np.percentile(a, 90)))


def run(label: str, start: str | None):
    print(f"\n{'='*74}\n## {label}\n{'='*74}")
    wks = {}
    for n in INDICES:
        wk = weekly(n)
        if start:
            wk = wk[wk.index >= pd.Timestamp(start)]
        wks[n] = wk

    # metric (i) weekly range %  — valid OHLC only
    print("\n### (i) weekly range % = (high-low)/close × 100  [valid-OHLC only]")
    print(f"{'index':12s} {'n':>5s} {'median':>8s} {'Q1':>7s} {'Q3':>7s} {'90p':>7s} {'first':>11s}")
    ri = {}
    for n in INDICES:
        wk = wks[n]
        v = wk[(wk.high > 0) & (wk.low > 0)]
        rng = (v.high - v.low) / v.close * 100
        ri[n] = quant(rng.values)
        first = v.index.min().date() if len(v) else "-"
        print(f"{n:12s} {ri[n]['n']:>5d} {ri[n]['median']:>8.2f} {ri[n]['q1']:>7.2f} {ri[n]['q3']:>7.2f} {ri[n]['p90']:>7.2f} {str(first):>11s}")

    # metric (ii) weekly |close return| %  — close valid full history
    print("\n### (ii) weekly |close-to-close return| % ")
    print(f"{'index':12s} {'n':>5s} {'median':>8s} {'Q1':>7s} {'Q3':>7s} {'90p':>7s}")
    rii = {}
    for n in INDICES:
        ret = wks[n]["close"].pct_change().abs() * 100
        rii[n] = quant(ret.values)
        print(f"{n:12s} {rii[n]['n']:>5d} {rii[n]['median']:>8.2f} {rii[n]['q1']:>7.2f} {rii[n]['q3']:>7.2f} {rii[n]['p90']:>7.2f}")

    # KR/US median ratio
    print("\n### KR median ÷ US median (주간 봉폭 비율)")
    print(f"{'pair (KR/US)':24s} {'(i)range':>9s} {'(ii)|ret|':>9s}")
    out = {}
    for kr, us in PAIRS:
        a = ri[kr]["median"] / ri[us]["median"] if ri[us]["median"] else float("nan")
        b = rii[kr]["median"] / rii[us]["median"] if rii[us]["median"] else float("nan")
        out[(kr, us)] = (a, b)
        print(f"{kr+'/'+us:24s} {a:>9.2f} {b:>9.2f}")
    return out


if __name__ == "__main__":
    common = run("공통 1996-07 ~ 2026-05 (1차 비교 기준)", COMMON_START)
    run("전체 역사 (보조; KR range 는 KOSPI 1994-10/KOSDAQ 1996-07~)", None)

    print(f"\n{'='*74}\n## 스케일 권고 (현행 10–15% 기준)\n{'='*74}")
    print("operative 임계 = 주간 봉폭. KR/US 비율(공통기간, metric (i) range 우선):")
    for (kr, us), (a, b) in common.items():
        lo, hi = 10 * a, 15 * a
        print(f"  {kr}/{us}: range비율={a:.2f} → 10–15% × {a:.2f} ≈ {lo:.0f}–{hi:.0f}%  (|ret|비율 {b:.2f} 참고)")
    print("  ※ 비율≈1 → 10–15% 유지. >1 → 위 스케일. clamp 범위는 web 판정 (예: floor=현행10%).")
