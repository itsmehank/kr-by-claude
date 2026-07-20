"""Stage3 검증 재생 — §6.1/§6.2(climax/topping) 결정론 게이트 (#44 Task 8 / D4).

사전등록: docs/superpowers/specs/2026-07-21-issue44-stage3-verification-prereg.md
(측정 전 지표·해석 밴드 고정 — 이 스크립트는 그 §3 지표 정의를 그대로 구현한다).

backtest_classification 의 (symbol, analyzed_for_date) 전 행에 대해, production 경로
(api.services.payload_builder)와 동일하게 weekly 전 이력·daily 60일·indicators 60일을
DB 에서 구성해 find_anchor + compute_climax_gates + compute_topping_gates 를 재생한다.
LLM 호출 없음(순수 함수만). production DB 는 read-only(SELECT 만) — 이 스크립트는
DB 에 아무것도 쓰지 않는다.

집계(정의는 사전등록 §3 그대로):
  ① §6.1 발화 후보율(P1·P2·트리거≥1·scope_active) — E1 미고려 상한
  ② §6.2 발화율(G0+T-B / G0+T-D분배일 분지별) + would_force(강제율, gates.py 조건 재현)
  ③ ①·②(=would_force 자격 branch_either) 발화 건의 기존 LLM classification 분포
  ④ anchor 안정성 — 표본 500행 2회 독립 재조회+재실행 일치율 + anchor 연령 분포
  ⑤ T4 민감도 — max(7~15) vs 고정 10일 단일창
  ⑥ left_censored/no_transition/anchored 비율 + quality_flag 분리 집계
"""
from __future__ import annotations

import json
import logging
import random
import sys
from collections import Counter
from pathlib import Path

from kr_pipeline.db.connection import connect
from kr_pipeline.common.thresholds import CLIMAX_UP_DAYS_PCT
from kr_pipeline.llm_runner.compute.climax_topping import (
    compute_climax_gates,
    compute_topping_gates,
    find_anchor,
)
from api.services.payload_builder import (
    _dist_count_25s,
    _fetch_daily_ohlcv,
    _fetch_indicators_recent,
    _fetch_weekly_full,
)

log = logging.getLogger("stage3.replay")

OUT_PATH = Path("data/verification/2026-07-21-stage3/replay_results.json")

ANCHOR_SAMPLE_N = 500
ANCHOR_SAMPLE_SEED = 44  # 재현 가능(사전등록 §3④) — 이슈 #44 참조 값, 의미 없는 상수
T4_FIXED_WINDOW = 10  # 사전등록 §3⑤ — WINDOW_MIN(7)~MAX(15) 사이 단일 고정창

_ROWS_SQL = """
SELECT symbol, analyzed_for_date, classification
  FROM backtest_classification
 ORDER BY analyzed_for_date, symbol
"""


def _replay_row(conn, symbol: str, on_date) -> tuple[dict, dict, dict, bool | None]:
    """production 경로와 동일한 데이터 구성 + 세 함수 재생. 반환: (anchor, climax, topping, t4_fixed10_ok)."""
    weekly_full = _fetch_weekly_full(conn, symbol, on_date)
    daily60 = _fetch_daily_ohlcv(conn, symbol, on_date, days=60)
    ind60 = _fetch_indicators_recent(conn, symbol, on_date, days=60)
    daily20 = daily60[-20:]

    anchor = find_anchor(weekly_full)
    climax = compute_climax_gates(weekly_full, daily20, anchor)
    dist_count_25s = _dist_count_25s(ind60)
    topping = compute_topping_gates(weekly_full, dist_count_25s, anchor)

    # T4 고정 10일 variant — 동일 daily20 입력(사전등록 §3⑤: max variant 와 apples-to-apples)
    flags = [daily20[i]["close"] > daily20[i - 1]["close"] for i in range(1, len(daily20))]
    if len(flags) >= T4_FIXED_WINDOW:
        pct10 = sum(flags[-T4_FIXED_WINDOW:]) / T4_FIXED_WINDOW * 100
        t4_fixed10_ok = pct10 >= CLIMAX_UP_DAYS_PCT
    else:
        t4_fixed10_ok = None

    return anchor, climax, topping, t4_fixed10_ok


def _dist_summary(vals: list[int]) -> dict | None:
    if not vals:
        return None
    vs = sorted(vals)
    n = len(vs)
    return {
        "n": n, "min": vs[0], "p25": vs[n // 4], "p50": vs[n // 2],
        "p75": vs[(3 * n) // 4], "max": vs[-1],
    }


def _rate(true_n: int, false_n: int) -> float | None:
    denom = true_n + false_n
    return true_n / denom * 100 if denom else None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    agg = {
        "rows_total": 0,
        "build_errors": Counter(),
        "baseline_counts": Counter(),
        "quality_flag_climax": Counter(),
        "quality_flag_topping": Counter(),
        "s61_candidate": 0,
        "s61_classification": Counter(),
        "s62_branch_b": 0,
        "s62_branch_d": 0,
        "s62_branch_either": 0,
        "s62_classification": Counter(),
        "s62_would_force": 0,
        "t4_max": Counter(),      # true/false/none
        "t4_fixed10": Counter(),  # true/false/none
        "anchor_weeks_since": [],
    }
    records = []
    replayed = []  # (row, anchor) — anchor 안정성 표본 추출용

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_ROWS_SQL)
            rows = [
                {"symbol": r[0], "date": r[1], "classification": r[2]}
                for r in cur.fetchall()
            ]
        if limit:
            rows = rows[:limit]
        agg["rows_total"] = len(rows)

        for i, row in enumerate(rows):
            try:
                anchor, climax, topping, t4f = _replay_row(conn, row["symbol"], row["date"])
            except Exception as e:  # 측정 대상: 실데이터에서의 재생 실패 유형
                agg["build_errors"][f"{type(e).__name__}: {e}"] += 1
                continue

            replayed.append((row, anchor))

            baseline = (
                "left_censored" if anchor["left_censored"]
                else "no_transition" if anchor["no_transition"]
                else "anchored"
            )
            agg["baseline_counts"][baseline] += 1
            agg["quality_flag_climax"][str(climax["quality_flag"])] += 1
            agg["quality_flag_topping"][str(topping["quality_flag"])] += 1
            if baseline == "anchored":
                agg["anchor_weeks_since"].append(anchor["weeks_since"])

            # ① §6.1 후보 (사전등록 §3①)
            trig = any(
                x is True for x in (
                    climax["t1_max_spread_now"], climax["t2_max_volume_now"],
                    climax["t3_gap_up_today"], climax["t4_ok"],
                )
            )
            candidate = (
                climax["maturity_ok"] is True and climax["p2_accel_ok"] is True
                and trig and climax["scope_active"] is True
            )
            if candidate:
                agg["s61_candidate"] += 1
                agg["s61_classification"][row["classification"]] += 1

            # ② §6.2 분지 (사전등록 §3②, gates.py 의 6_2_topping_shadow 자격 조건 재현)
            g0 = topping["g0_below_10w"] is True
            qual_ok = topping["quality_flag"] is not True
            tb = topping["tb_ok"] is True
            td = topping["td_dist_ok"] is True
            branch_b = g0 and qual_ok and tb
            branch_d = g0 and qual_ok and td
            branch_either = g0 and qual_ok and (tb or td)
            if branch_b:
                agg["s62_branch_b"] += 1
            if branch_d:
                agg["s62_branch_d"] += 1
            if branch_either:
                agg["s62_branch_either"] += 1
                agg["s62_classification"][row["classification"]] += 1
                if row["classification"] != "ignore":
                    agg["s62_would_force"] += 1

            # ⑤ T4 두 variant
            for key, val in (("t4_max", climax["t4_ok"]), ("t4_fixed10", t4f)):
                agg[key]["true" if val is True else "false" if val is False else "none"] += 1

            records.append({
                "symbol": row["symbol"], "date": str(row["date"]),
                "classification": row["classification"], "baseline": baseline,
                "quality_flag_climax": climax["quality_flag"],
                "quality_flag_topping": topping["quality_flag"],
                "s61_candidate": candidate,
                "s62_branch_b": branch_b, "s62_branch_d": branch_d,
                "s62_branch_either": branch_either,
                "t4_max_ok": climax["t4_ok"], "t4_fixed10_ok": t4f,
            })

            if (i + 1) % 500 == 0:
                log.info("progress %d/%d (replayed_ok %d)", i + 1, len(rows), len(replayed))

        # ④ anchor 안정성 — 표본 500행, weekly_full 독립 2회 재조회 + find_anchor 재실행
        rng = random.Random(ANCHOR_SAMPLE_SEED)
        sample = rng.sample(replayed, min(ANCHOR_SAMPLE_N, len(replayed)))
        mismatch = 0
        for row, anchor1 in sample:
            weekly_full_2 = _fetch_weekly_full(conn, row["symbol"], row["date"])
            anchor2 = find_anchor(weekly_full_2)
            if anchor1 != anchor2:
                mismatch += 1
        log.info("anchor stability sample: n=%d mismatch=%d", len(sample), mismatch)

    rows_ok = sum(agg["baseline_counts"].values())

    out = {
        "rows_total": agg["rows_total"],
        "rows_replayed_ok": rows_ok,
        "build_errors": dict(agg["build_errors"]),
        "baseline_counts": dict(agg["baseline_counts"]),
        "quality_flag_climax": dict(agg["quality_flag_climax"]),
        "quality_flag_topping": dict(agg["quality_flag_topping"]),
        "s61_candidate_rate": {
            "count": agg["s61_candidate"], "denom": rows_ok,
            "pct": agg["s61_candidate"] / rows_ok * 100 if rows_ok else None,
            "existing_classification": dict(agg["s61_classification"]),
        },
        "s62_rates": {
            "branch_b": {
                "count": agg["s62_branch_b"],
                "pct": agg["s62_branch_b"] / rows_ok * 100 if rows_ok else None,
            },
            "branch_d": {
                "count": agg["s62_branch_d"],
                "pct": agg["s62_branch_d"] / rows_ok * 100 if rows_ok else None,
            },
            "branch_either": {
                "count": agg["s62_branch_either"],
                "pct": agg["s62_branch_either"] / rows_ok * 100 if rows_ok else None,
            },
            "existing_classification_of_branch_either": dict(agg["s62_classification"]),
            "ignore_alignment_pct": (
                agg["s62_classification"].get("ignore", 0) / agg["s62_branch_either"] * 100
                if agg["s62_branch_either"] else None
            ),
            "would_force_count": agg["s62_would_force"],
            "would_force_pct_of_population": (
                agg["s62_would_force"] / rows_ok * 100 if rows_ok else None
            ),
        },
        "anchor_stability": {
            "sample_n": len(sample),
            "mismatch": mismatch,
            "match_rate_pct": (
                (len(sample) - mismatch) / len(sample) * 100 if sample else None
            ),
            "seed": ANCHOR_SAMPLE_SEED,
        },
        "anchor_weeks_since_distribution": _dist_summary(agg["anchor_weeks_since"]),
        "t4_sensitivity": {
            "max_variant": {
                **{k: agg["t4_max"][k] for k in ("true", "false", "none")},
                "fire_rate_pct": _rate(agg["t4_max"]["true"], agg["t4_max"]["false"]),
            },
            "fixed10_variant": {
                **{k: agg["t4_fixed10"][k] for k in ("true", "false", "none")},
                "fire_rate_pct": _rate(agg["t4_fixed10"]["true"], agg["t4_fixed10"]["false"]),
            },
        },
        "records": records,
    }
    mv = out["t4_sensitivity"]["max_variant"]["fire_rate_pct"]
    fv = out["t4_sensitivity"]["fixed10_variant"]["fire_rate_pct"]
    out["t4_sensitivity"]["diff_pp"] = (mv - fv) if (mv is not None and fv is not None) else None

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    summary_keys = (
        "rows_total", "rows_replayed_ok", "build_errors", "baseline_counts",
        "quality_flag_climax", "quality_flag_topping", "s61_candidate_rate",
        "s62_rates", "anchor_stability", "anchor_weeks_since_distribution",
        "t4_sensitivity",
    )
    print(json.dumps({k: out[k] for k in summary_keys}, ensure_ascii=False, indent=2, default=str))
    print(f"\nsaved -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
