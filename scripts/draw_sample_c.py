"""표본 C 추첨 — 독립 검증 구간(2017-H2~2020, 이슈 #52). 기본 = preview(읽기 전용).

  uv run python scripts/draw_sample_c.py           # preview: frame/pool·A/B 겹침·주간
                                                   #   qualifying 밀도·호출량 견적 (추첨 없음)
  uv run python scripts/draw_sample_c.py --draw    # 사전등록 승인 후 **정확히 1회** 실행

preview 는 2017-H2 워밍업 가정(주간 qualifying 밀도) 검증과 LLM 호출량 견적의 실측
근거 산출용 — DB 쓰기 0. --draw 결과는 data/backtest/sample_c_draw_20260721.json 으로
저장한 뒤 kr_pipeline/backtest/frozen_sample_c.py 와 prereg 문서에 동결한다(이후 권위는
frozen 모듈 — 재추첨 금지, cf. draw_sample_b.py). pool < MIN_POOL 이면 draw 거부.

표본 A/B 와의 종목 겹침은 **허용**(독립성의 축은 기간 — 2017-H2~2020 vs 2021~2024,
backtest_classification 은 (symbol, analyzed_for_date) 단위라 적재 충돌 없음). 겹침
수는 산출물에 기록한다.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.backtest.sample import build_frame, draw_sample
from kr_pipeline.db.connection import connect

SEED_C = 20260721
FRAME_START, FRAME_END = date(2017, 7, 1), date(2020, 12, 31)
N = 100
MIN_POOL = 300          # prereg: 표본의 3배 미만이면 draw 거부(재설계)
H1_PROBE_END = date(2017, 12, 31)   # 워밍업 검증 구간(2017-H2) 주별 상세 출력


def weekly_density(conn, start: date, end: date) -> list[tuple[date, int]]:
    """주(금요일)별 production 주말 필터 통과 종목 수 — build_frame 과 동일 조건.

    backfill 은 토요일 열거 + as_of 이하 최근 지표일(=금요일)을 쓰므로 금요일 밀도가
    주간 호출 후보 수와 1:1 대응한다.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.date, COUNT(*)
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date BETWEEN %s AND %s
               AND EXTRACT(DOW FROM i.date) = 5
               AND i.minervini_pass = TRUE
               AND i.rs_line_not_declining_7m = TRUE
               AND s.delisted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM daily_prices p
                    WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL
               )
             GROUP BY i.date
             ORDER BY i.date
            """,
            (start, end),
        )
        return cur.fetchall()


def main() -> int:
    do_draw = "--draw" in sys.argv[1:]
    with connect() as conn:
        frame = build_frame(conn, FRAME_START, FRAME_END)
        dens = weekly_density(conn, FRAME_START, FRAME_END)
    pool = sorted(set(frame))       # 제외 없음 — A/B 겹침 허용(모듈 docstring)
    total_q = sum(c for _, c in dens)
    by_year: dict[int, list[int]] = {}
    for d, c in dens:
        by_year.setdefault(d.year, []).append(c)
    out = {
        "mode": "draw" if do_draw else "preview",
        "seed": SEED_C,
        "frame_start": str(FRAME_START), "frame_end": str(FRAME_END),
        "frame_size": len(pool), "min_pool": MIN_POOL, "n": N,
        "overlap_pool_sample_a": len(set(pool) & set(FROZEN_SAMPLE)),
        "overlap_pool_sample_b": len(set(pool) & set(FROZEN_SAMPLE_B)),
        "weeks": len(dens),
        "total_qualifying_ticker_weeks": total_q,
        "weekly_qualifying_mean": round(total_q / len(dens), 1) if dens else None,
        "weekly_qualifying_by_year_mean": {
            y: round(sum(v) / len(v), 1) for y, v in sorted(by_year.items())},
        "weekly_qualifying_2017H2": [
            [str(d), c] for d, c in dens if d <= H1_PROBE_END],
        # 표본 100이 frame 균등 추출일 때 기대 호출 수 = Σ주간밀도 × (N/frame)
        "estimated_llm_calls_n100": (
            round(total_q * N / len(pool)) if pool else None),
    }
    if do_draw:
        if len(pool) < MIN_POOL:
            raise SystemExit(
                f"pool {len(pool)} < MIN_POOL {MIN_POOL} — draw 거부(표본 규칙 재설계 필요)")
        sample_c = draw_sample(pool, n=N, seed=SEED_C)
        assert len(sample_c) == N, f"표본 크기 {len(sample_c)} != {N}"
        out["sample_c"] = sample_c
        out["overlap_in_sample_a"] = sorted(set(sample_c) & set(FROZEN_SAMPLE))
        out["overlap_in_sample_b"] = sorted(set(sample_c) & set(FROZEN_SAMPLE_B))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
