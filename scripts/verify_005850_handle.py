# scripts/verify_005850_handle.py
"""Phase 1 2-A 회귀 1순위 앵커 — 005850 핸들 경계 휴리스틱 검증.

실 DB 의 005850 daily_prices 로 compute_handle_quality 를 돌려:
- handle_high ≈ 71,900 (pivot_price)
- handle_low ≈ 58,900 (18% 폭락 저점)
- ratio_A = handle_depth_pct / base_depth_pct ≈ 0.69 > 0.33
- handle_quality 발화
를 확인. 휴리스틱이 핸들을 올바로 짚는지가 회귀 전체의 전제.
"""
from dotenv import load_dotenv
load_dotenv()

from datetime import datetime
from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner.compute.handle_quality import compute_handle_quality


def main():
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT classified_at, classification, pattern, pivot_price, pivot_basis,
                   base_high, base_low, base_depth_pct, base_start_date
              FROM weekly_classification
             WHERE symbol = '005850'
             ORDER BY classified_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        assert row is not None, "005850 분류 행 없음"
        cls = {
            "classified_at": row[0], "classification": row[1], "pattern": row[2],
            "pivot_price": row[3], "pivot_basis": row[4], "base_high": row[5],
            "base_low": row[6], "base_depth_pct": row[7], "base_start_date": row[8],
        }
        print(f"005850 cls: pattern={cls['pattern']} pivot={cls['pivot_price']} "
              f"basis={cls['pivot_basis']} base_depth={cls['base_depth_pct']}%")

        result = compute_handle_quality(conn, "005850", cls["classified_at"], cls)

    print(f"compute_handle_quality result: {result}")
    assert result is not None, "❌ handle_quality 미발화 (휴리스틱이 핸들 못 짚음 — 회귀 전제 붕괴)"
    assert result["fired"] is True
    m = result["metrics"]
    print(f"  handle_window: {m['handle_start']} ~ {m['handle_end']}")
    print(f"  handle_high={m['handle_high']} handle_low={m['handle_low']} ratio_a={m['ratio_a']}")
    # 휴리스틱이 핸들을 올바로 짚었는지 — 예상 handle_high≈71900, handle_low≈58900.
    assert 70000 <= m["handle_high"] <= 73000, f"❌ handle_high={m['handle_high']} 예상(≈71900) 벗어남 — 우측 림 오인식"
    assert 55000 <= m["handle_low"] <= 62000, f"❌ handle_low={m['handle_low']} 예상(≈58900) 벗어남 — 핸들 저점 오인식"
    assert m["ratio_a"] > 0.33, f"❌ ratio_a={m['ratio_a']} <= 0.33"
    assert "deep_handle" in result["reasons"], "deep_handle 트리거 기대"
    print("✅ 005850 handle_quality 앵커 검증 통과")


if __name__ == "__main__":
    main()
