"""trigger_gate — breakout/invalidation 판정 (LLM 없이 결정론 로직)."""


def test_breakout_close_above_pivot_with_volume():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=82500, pivot_price=80000,
        volume=1_500_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result == "breakout"


def test_no_trigger_close_below_pivot_no_invalidation():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=79000, pivot_price=80000,
        volume=900_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result is None


def test_breakout_volume_insufficient_no_trigger():
    """가격 돌파했지만 거래량 1.5배 미달 → 트리거 없음."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=82500, pivot_price=80000,
        volume=1_100_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result is None


def test_invalidation_below_sma50():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=75000, pivot_price=80000,
        volume=1_200_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result == "invalidation"


def test_invalidation_below_stop_loss():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=75500, pivot_price=80000,
        volume=900_000, avg_volume_20d=1_000_000,
        stop_loss=76000, sma_50=77000,
        classification="entry",
    )
    assert result == "invalidation"


def test_watch_promotion_close_within_5pct_of_pivot():
    """watch 종목 — pivot 95% 이상 도달 + 정상 거래량 → promotion."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=76500, pivot_price=80000,
        volume=1_000_000, avg_volume_20d=1_000_000,
        stop_loss=72000, sma_50=75000,
        classification="watch",
    )
    assert result == "promotion"
