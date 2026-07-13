"""표본 B 일회성 추첨 — 실행 후 결과를 frozen_sample_b.py 와 사전등록 문서에 동결.

frame(2021-2024 주말필터 통과) − 기적재(backtest_classification 전체 symbol) 풀에서
seed 20260713 로 100종목. DB 가 바뀌면 재실행 결과가 달라질 수 있으므로 **추첨은
정확히 1회** — 이후 권위는 kr_pipeline/backtest/frozen_sample_b.py.
"""
from __future__ import annotations

import json
from datetime import date

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.sample import build_frame, draw_sample
from kr_pipeline.db.connection import connect

SEED_B = 20260713
START, END = date(2021, 1, 1), date(2024, 12, 31)


def main() -> int:
    with connect() as conn:
        frame = build_frame(conn, START, END)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT symbol FROM backtest_classification")
            loaded = sorted(r[0] for r in cur.fetchall())
    pool = sorted(set(frame) - set(loaded))
    sample_b = draw_sample(pool, n=100, seed=SEED_B)
    assert len(sample_b) == 100, f"표본 크기 {len(sample_b)} != 100"
    assert not set(sample_b) & set(loaded), "기적재 종목 혼입"
    assert not set(sample_b) & set(FROZEN_SAMPLE), "표본 A 혼입"
    assert set(FROZEN_SAMPLE) <= set(loaded), "기적재에 표본 A 미포함 — 전제 붕괴"
    print(json.dumps({
        "seed": SEED_B, "frame_size": len(frame), "excluded_loaded": len(loaded),
        "pool_size": len(pool), "sample_b": sample_b, "excluded_at_draw": loaded,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
