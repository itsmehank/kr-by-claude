# scripts/regression_phase1_2a.py
"""Phase 1 2-A 회귀 — 005850 → watch (2E_tier2), 037760 → 2F 발화.

실 DB 의 005850·037760 최신 분류 입력을 gate 에 통과시켜 기대 결과 확인.
FREEZE 인프라로 입력 보존돼 재현 가능.
"""
from dotenv import load_dotenv
load_dotenv()

from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner.gates import apply_phase1_gates


def _load_cls(conn, symbol):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT classified_at, classification, pattern, pivot_price, pivot_basis,
                   base_high, base_low, base_depth_pct, base_start_date, risk_flags, confidence
              FROM weekly_classification
             WHERE symbol = %s ORDER BY classified_at DESC LIMIT 1
        """, (symbol,))
        r = cur.fetchone()
    assert r, f"{symbol} 분류 없음"
    return {
        "classified_at": r[0], "classification": r[1], "pattern": r[2], "pivot_price": r[3],
        "pivot_basis": r[4], "base_high": r[5], "base_low": r[6], "base_depth_pct": r[7],
        "base_start_date": r[8], "risk_flags": list(r[9] or []), "confidence": float(r[10]) if r[10] else None,
    }


def main():
    with connect() as conn:
        # 005850 — entry → watch (2E_tier2)
        c1 = _load_cls(conn, "005850")
        print(f"005850 입력: class={c1['classification']} conf={c1['confidence']} flags={c1['risk_flags']}")
        out1, tr1 = apply_phase1_gates(conn, "005850", c1["classified_at"], dict(c1))
        print(f"005850 게이트 후: class={out1['classification']} conf={out1['confidence']} flags={out1['risk_flags']} tr={tr1}")
        assert out1["classification"] == "watch", "❌ 005850 entry→watch 강등 실패"
        assert out1["confidence"] <= 0.50, "❌ 005850 Tier2 conf cap 실패"
        assert tr1 and "2E_tier2" in tr1, "❌ 005850 2E_tier2 미발화"
        assert "handle_quality" in out1["risk_flags"], "❌ handle_quality 미주입"
        print("✅ 005850 회귀 통과")

        # 037760 — 2F 발화 (watch 유지)
        c2 = _load_cls(conn, "037760")
        print(f"037760 입력: class={c2['classification']} pattern={c2['pattern']} pivot={c2['pivot_price']}")
        out2, tr2 = apply_phase1_gates(conn, "037760", c2["classified_at"], dict(c2))
        print(f"037760 게이트 후: class={out2['classification']} tr={tr2}")
        assert tr2 and "2F_failed_breakout" in tr2, "❌ 037760 2F 미발화"
        assert out2["classification"] == "watch", "❌ 037760 2F 후 classification 변조 (2F 는 강등 안 함)"
        print("✅ 037760 회귀 통과")

        print("\n=== 룰별 독립 카운트 (전체 분류) ===")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                  COUNT(*) FILTER (WHERE triggered_rules ? '2E_tier1') AS t1,
                  COUNT(*) FILTER (WHERE triggered_rules ? '2E_tier2') AS t2,
                  COUNT(*) FILTER (WHERE triggered_rules ? '2F_failed_breakout') AS fb
                  FROM weekly_classification
            """)
            t1, t2, fb = cur.fetchone()
            print(f"  2E_tier1={t1}  2E_tier2={t2}  2F_failed_breakout={fb}")
    print("\n✅✅ Phase 1 2-A 회귀 마일스톤 통과 — 2-B/C/D 진입 가능")


if __name__ == "__main__":
    main()
