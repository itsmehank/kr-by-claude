"""#44 D2-b — 제3안 watch_reason 차단·왕복 고정 (characterization).

배경: E1(§6.1 climax) 판정 불능 시 LLM 이 verdict=watch + watch_reason=
'suspected_climax_stage_indeterminate' 를 내도록 프롬프트가 개정될 예정(Task 9).
이 값은 trigger_gate.ALLOWED_WATCH_REASONS 에 비포함이라 breakout_from_watch 가
발화하지 않고 promotion 으로만 흐른다(go_now 금지 경로). store 는 watch_reason 을
검증 없이 pass-through 한다.

이 파일은 이미 green 인 동작(trigger_gate 평가 순서 + store pass-through, 둘 다
기존 구현이 그대로 만족)을 회귀 고정하는 characterization 테스트다 — red 단계
없음. 신규/변경 프로덕션 코드 없음(store.py 는 주석만 추가).
"""
from datetime import datetime, timezone

SUSPECTED_CLIMAX_STAGE_INDETERMINATE = "suspected_climax_stage_indeterminate"


def test_suspected_climax_stage_indeterminate_blocks_breakout_from_watch():
    """§6.1 판정불능 사유는 ALLOWED_WATCH_REASONS 비포함 → fresh_cross·거래량
    조건이 전부 충족돼도 breakout_from_watch 가 아니라 promotion 으로 강등.

    (매수 경로 차단 — promotion 은 go_now 금지, LLM 정밀판정 staging 만 가능.)
    """
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=1060.0,
        pivot_price=1000.0,
        volume=2_000_000,
        avg_volume_50d=1_000_000.0,
        stop_loss=None,
        sma_50=900.0,
        classification="watch",
        prev_close=990.0,
        watch_reason=SUSPECTED_CLIMAX_STAGE_INDETERMINATE,
    )
    assert result != "breakout_from_watch"
    assert result == "promotion"


def test_store_roundtrips_suspected_climax_stage_indeterminate(db):
    """store 는 watch_reason 값을 enum 검증 없이 그대로 저장·재조회 보존한다
    (스키마 CHECK 부재 회귀 고정 — 향후 누군가 enum 제약을 넣으면 이 테스트가 잡음)."""
    from kr_pipeline.llm_runner.store import insert_classification

    symbol = "CXSHDW"
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (symbol,))
    db.commit()

    insert_classification(
        db,
        symbol=symbol,
        classified_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch",
            "pattern": "flat_base",
            "pivot_price": 1000.0,
            "pivot_basis": "high_of_base",
            "base_high": 1000.0,
            "base_low": 900.0,
            "base_depth_pct": 10.0,
            "base_start_date": "2026-03-01",
            "risk_flags": [],
            "confidence": 0.5,
            "reasoning": "test",
            "watch_reason": SUSPECTED_CLIMAX_STAGE_INDETERMINATE,
        },
        source="weekend",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT watch_reason FROM weekly_classification WHERE symbol=%s", (symbol,)
        )
        row = cur.fetchone()
    assert row[0] == SUSPECTED_CLIMAX_STAGE_INDETERMINATE
