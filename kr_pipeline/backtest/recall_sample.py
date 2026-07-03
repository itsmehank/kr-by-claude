"""Phase 0.5 — recall 감사 표집 (2차 잠금 구현, LLM 0회).

spec §7 2차 잠금 (2026-07-03):
- 프레임 = T13=0.40 / T26=0.50 / L=10억 (combo 고정).
- 결정론 버킷(filter_excluded / structurally_uncatchable / censored 플래그)은
  프레임 전수 집계 — 표집 없음.
- 표집 = phase1 후보 풀에만: N_cap=120, 에피소드 초과수익 터사일 층화 40×3,
  seed=20260702. 층화 기준 = 당첨 주 max(excess13, excess26) 의 최댓값
  (recall_phase0 의 ep_excess_pct).

실행: uv run python -m kr_pipeline.backtest.recall_sample
출력: data/backtest/recall_phase1_sample_20260703.csv + stdout 견적(셀 수·소요).
"""
from __future__ import annotations

import csv
import random
from collections import Counter
from pathlib import Path

T13, T26 = "0.4", "0.5"
L_MIN = 1_000_000_000
N_PER_TERTILE = 40
SEED = 20260702
AVG_CALL_S = 159  # Sonnet 5 실측 (spec §11)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "backtest"
SRC = DATA_DIR / "recall_phase0_episodes_20260702.csv"
OUT = DATA_DIR / "recall_phase1_sample_20260703.csv"


def main() -> None:
    with open(SRC) as f:
        rows = [r for r in csv.DictReader(f) if r["t13"] == T13 and r["t26"] == T26]
    frame = [r for r in rows if r["avg_value_20d"] and int(r["avg_value_20d"]) >= L_MIN]

    # ── 결정론 버킷 전수 집계 ──
    buckets = Counter(r["bucket"] for r in frame)
    censored = sum(r["censored"] == "True" for r in frame)
    print(f"[frame] 에피소드 {len(frame)} = {dict(buckets)} / censored 플래그 {censored}")

    pool = sorted(
        (r for r in frame if r["bucket"] == "phase1_candidate"),
        key=lambda r: (float(r["ep_excess_pct"]), r["ticker"], r["ep_start"]),
    )
    n = len(pool)
    print(f"[pool] phase1 후보 {n}")

    # 터사일 분할 (초과수익 오름차순 3등분; 나머지는 앞 분위부터 1개씩)
    base, rem = divmod(n, 3)
    sizes = [base + (1 if k < rem else 0) for k in range(3)]
    tertiles, pos = [], 0
    for size in sizes:
        tertiles.append(pool[pos: pos + size])
        pos += size

    rng = random.Random(SEED)
    sampled = []
    for k, group in enumerate(tertiles):
        take = rng.sample(group, min(N_PER_TERTILE, len(group)))
        for r in take:
            r["tertile"] = f"T{k + 1}"
            r["tertile_pool_size"] = len(group)
        sampled.extend(sorted(take, key=lambda r: (r["ticker"], r["ep_start"])))
        lo, hi = float(group[0]["ep_excess_pct"]), float(group[-1]["ep_excess_pct"])
        print(f"  터사일 T{k + 1}: 풀 {len(group)} (초과수익 {lo:.0f}~{hi:.0f}%) → 표본 {min(N_PER_TERTILE, len(group))}")

    cells = sum(int(r["n_backfill_weeks"]) for r in sampled)
    trunc = sum(r["truncated"] == "True" for r in sampled)
    cens = sum(r["censored"] == "True" for r in sampled)
    serial_h = cells * AVG_CALL_S / 3600
    print(f"\n[표본] 에피소드 {len(sampled)} / 백필 셀(=Phase 1 LLM 호출) **{cells}** / truncated {trunc} / censored {cens}")
    print(f"[소요] 직렬 {serial_h:.1f}h · 4병렬 {serial_h / 4:.1f}h · 6병렬 {serial_h / 6:.1f}h (호출당 {AVG_CALL_S}s 실측)")

    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(sampled[0].keys()))
        w.writeheader()
        w.writerows(sampled)
    print(f"CSV: {OUT}")


if __name__ == "__main__":
    main()
