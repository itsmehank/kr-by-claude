"""#116 P2-4 — 상폐 통과 누락 정량화 (가격 미소비 경로, 수익률 일절 비산출).

표본 A/B/C 각 watch 윈도(A·B 2021-01-01~2024-12-31, C 2017-07-01~2020-12-31)에서,
상폐 종목이 프레임 구성 시점에 살아 있었다면 주말 필터를 통과했을 규모를 정량화한다.

통과 조작화 = bt_delisted_indicators.gate_pass IS TRUE ∧ 금요일(EXTRACT(DOW)=5)
∧ 윈도 내 — build_frame 의 금요일 조건과 동형. 이를 build_frame(생존 프레임)·
FROZEN_SAMPLE 멤버십과 대조해 누락 비율·추첨 기대 누락 수(카운트만)를 산출한다.

소비 표면: bt_delisted_indicators(백테스트 전용 게이트 표면)만.
가격 테이블(delisted_adj_prices·delisted_daily_prices) 무접촉 — 승인 소비자
열거 규칙 준수. 전 쿼리 SELECT 전용, 날짜 조건 상한 2024-12-31(홀드아웃 무접촉).

방법 한계(산출 JSON 에도 명기):
- RS 축 차이: c8/rs_gate 는 bt_rs(무편향 — 상폐 포함 유니버스) 기준으로,
  production daily_indicators 의 생존 한정 rs_rating 과 축이 다르다.
- build_frame 의 adj_low IS NULL 제외 조건은 상폐 표면에 대응물이 없어 비적용.
- carve 종목은 c8 부재 → gate_pass NULL → IS TRUE 에서 제외(평가 불능 수 별도 보고).
- frame 은 현재 DB 재계산치 — 추첨 시점 풀과 소폭 드리프트 가능(B 추첨 시점
  풀 1730 은 문서 기록, cf. frozen_sample_b.py docstring).
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_AT_DRAW, FROZEN_SAMPLE_B
from kr_pipeline.backtest.frozen_sample_c import FROZEN_SAMPLE_C
from kr_pipeline.backtest.sample import build_frame
from kr_pipeline.db.connection import connect

HOLDOUT_CAP = date(2024, 12, 31)

WINDOWS = {
    "A": (date(2021, 1, 1), date(2024, 12, 31), FROZEN_SAMPLE, []),
    "B": (date(2021, 1, 1), date(2024, 12, 31), FROZEN_SAMPLE_B, EXCLUDED_AT_DRAW),
    "C": (date(2017, 7, 1), date(2020, 12, 31), FROZEN_SAMPLE_C, []),
}

PASS_SQL = """
    SELECT DISTINCT ticker FROM bt_delisted_indicators
     WHERE date BETWEEN %s AND %s
       AND EXTRACT(DOW FROM date) = 5
       AND gate_pass IS TRUE
     ORDER BY ticker
"""
PASS_EVENTS_SQL = """
    SELECT COUNT(*) FROM bt_delisted_indicators
     WHERE date BETWEEN %s AND %s
       AND EXTRACT(DOW FROM date) = 5
       AND gate_pass IS TRUE
"""
CARVE_SQL = """
    SELECT COUNT(DISTINCT ticker) FROM bt_delisted_indicators
     WHERE date BETWEEN %s AND %s
       AND EXTRACT(DOW FROM date) = 5
       AND gate_pass IS NULL
       AND c1 AND c2 AND c3 AND c4 AND c5 AND c6 AND c7 AND rs_gate
       AND c8 IS NULL
"""
IN_WINDOW_SQL = """
    SELECT COUNT(DISTINCT ticker) FROM bt_delisted_indicators
     WHERE date BETWEEN %s AND %s
"""
COVERAGE_SQL = """
    SELECT COUNT(DISTINCT ticker), MIN(date), MAX(date)
      FROM bt_delisted_indicators
     WHERE date <= %s
"""


def main() -> int:
    out = {
        "issue": 116,
        "part": "P2-4",
        "grade": "supplementary_non_judgment",
        "returns_computed": False,
        "operationalization": (
            "delisted pass = bt_delisted_indicators.gate_pass IS TRUE AND "
            "EXTRACT(DOW)=5 AND date in watch window (build_frame Friday-cadence "
            "동형); 대조 = build_frame(생존 프레임)·FROZEN_SAMPLE 멤버십"
        ),
        "limitations": [
            "RS 축 차이: c8/rs_gate 는 bt_rs 무편향(상폐 포함) 축 — production "
            "생존 한정 rs_rating 과 상이",
            "build_frame 의 adj_low IS NULL 제외 조건 비적용(상폐 표면 대응물 없음)",
            "carve 종목 c8 부재 → gate_pass NULL → 평가 불능(별도 카운트)",
            "frame 은 현재 DB 재계산치 — 추첨 시점 풀과 소폭 드리프트 가능",
        ],
        "samples": {},
    }
    with connect() as conn, conn.cursor() as cur:
        cur.execute(COVERAGE_SQL, (HOLDOUT_CAP,))
        n_tk, dmin, dmax = cur.fetchone()
        out["bt_delisted_indicators_coverage"] = {
            "tickers": n_tk,
            "min_date": str(dmin),
            "max_date_capped_20241231": str(dmax),
        }
        for name, (ws, we, frozen, excluded) in WINDOWS.items():
            frame = build_frame(conn, ws, we)
            cur.execute(PASS_SQL, (ws, we))
            passers = [r[0] for r in cur.fetchall()]
            cur.execute(PASS_EVENTS_SQL, (ws, we))
            pass_events = cur.fetchone()[0]
            cur.execute(CARVE_SQL, (ws, we))
            carve_indeterminate = cur.fetchone()[0]
            cur.execute(IN_WINDOW_SQL, (ws, we))
            delisted_in_window = cur.fetchone()[0]

            frame_set, pass_set = set(frame), set(passers)
            pool = sorted(frame_set - set(excluded)) if excluded else frame
            f, d, p = len(frame), len(passers), len(pool)
            out["samples"][name] = {
                "watch_window": [str(ws), str(we)],
                "frame_size": f,
                "draw_pool_size": p,
                "excluded_at_draw": len(excluded),
                "delisted_tickers_in_window": delisted_in_window,
                "delisted_pass_tickers": d,
                "delisted_pass_friday_events": pass_events,
                "carve_indeterminate_tickers": carve_indeterminate,
                "omission_rate_pct": round(100.0 * d / (f + d), 2) if f + d else None,
                "expected_omitted_in_draw100": (
                    round(100.0 * d / (p + d), 2) if p + d else None
                ),
                "checks": {
                    "frame_overlap_delisted_pass": sorted(frame_set & pass_set),
                    "frozen_overlap_delisted_pass": sorted(set(frozen) & pass_set),
                },
                "delisted_pass_ticker_list": passers,
            }

    path = f"data/backtest/issue116_p24_delisted_omission_{date.today():%Y%m%d}.json"
    with open(path, "w") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2)
    print(json.dumps({k: {kk: vv for kk, vv in v.items()
                          if kk != "delisted_pass_ticker_list"}
                      for k, v in out["samples"].items()}, ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
