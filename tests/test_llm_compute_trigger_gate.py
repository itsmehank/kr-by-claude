"""trigger_gate — breakout/invalidation 판정 (LLM 없이 결정론 로직)."""


def test_breakout_close_above_pivot_with_volume():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=82500, pivot_price=80000,
        volume=1_500_000, avg_volume_50d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result == "breakout"


def test_no_trigger_close_below_pivot_no_invalidation():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=79000, pivot_price=80000,
        volume=900_000, avg_volume_50d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result is None


def test_breakout_volume_insufficient_no_trigger():
    """가격 돌파했지만 거래량이 평균보다 낮음 → 트리거 없음.

    게이트는 1.0× (평균 이상) 만 요구. 책 표준 (1.4-1.5×) 의 정밀 판정은
    LLM 에 위임. 평균 미만은 명백한 저거래량 헛돌파 차단.
    """
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=82500, pivot_price=80000,
        volume=900_000, avg_volume_50d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result is None


def test_breakout_at_1x_volume_triggers():
    """가격 돌파 + 거래량 평균 이상 (1.1×) → breakout 트리거.

    1.5× 표준 미달이라도 게이트는 통과 → LLM 이 pocket pivot / 거래량
    1.4-1.5× 표준 / 일중 상단 1/3 등을 정밀 판정.
    """
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=82500, pivot_price=80000,
        volume=1_100_000, avg_volume_50d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result == "breakout"


def test_invalidation_below_sma50():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=75000, pivot_price=80000,
        volume=1_200_000, avg_volume_50d=1_000_000,
        stop_loss=76000, sma_50=78000,
        classification="entry",
    )
    assert result == "invalidation"


def test_invalidation_below_stop_loss():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=75500, pivot_price=80000,
        volume=900_000, avg_volume_50d=1_000_000,
        stop_loss=76000, sma_50=77000,
        classification="entry",
    )
    assert result == "invalidation"


def test_watch_promotion_close_within_5pct_of_pivot():
    """watch 종목 — pivot 95% 이상 도달 + 정상 거래량 → promotion."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate

    result = evaluate(
        close=76500, pivot_price=80000,
        volume=1_000_000, avg_volume_50d=1_000_000,
        stop_loss=72000, sma_50=75000,
        classification="watch",
    )
    assert result == "promotion"


def test_stop_loss_none_skips_stop_invalidation_but_sma_still_fires():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    assert evaluate(
        close=77000, pivot_price=80000, volume=900_000, avg_volume_50d=1_000_000,
        stop_loss=None, sma_50=78000, classification="entry",
    ) == "invalidation"   # close(77000) < sma_50(78000)


def test_stop_loss_none_allows_breakout():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    assert evaluate(
        close=82500, pivot_price=80000, volume=1_500_000, avg_volume_50d=1_000_000,
        stop_loss=None, sma_50=78000, classification="entry",
    ) == "breakout"


def test_stop_loss_none_no_false_invalidation():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    assert evaluate(
        close=79000, pivot_price=80000, volume=900_000, avg_volume_50d=1_000_000,
        stop_loss=None, sma_50=78000, classification="entry",
    ) is None


def test_stop_loss_value_still_invalidates():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    assert evaluate(
        close=75000, pivot_price=80000, volume=900_000, avg_volume_50d=1_000_000,
        stop_loss=76000, sma_50=70000, classification="entry",
    ) == "invalidation"


# ===== breakout_from_watch (watch 종목 정당한 돌파 갭 해소) =====


def _watch_kwargs(**overrides):
    """fresh cross 한 watch 종목 기본값 (close>pivot, prev_close<=pivot, 거래량 충분)."""
    base = dict(
        close=82500, pivot_price=80000, prev_close=79500,
        volume=1_500_000, avg_volume_50d=1_000_000,
        stop_loss=72000, sma_50=75000,
        classification="watch", watch_reason="valid_base_awaiting_breakout",
    )
    base.update(overrides)
    return base


def test_breakout_from_watch_allowed_reason_fresh_cross():
    """watch + ALLOWED 사유 + fresh_cross + 거래량 → breakout_from_watch."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    for reason in ("unfavorable_market", "marginal_tt", "valid_base_awaiting_breakout"):
        assert evaluate(**_watch_kwargs(watch_reason=reason)) == "breakout_from_watch"


def test_breakout_from_watch_preempts_promotion():
    """close>pivot 인 날 breakout_from_watch 가 promotion 을 선점 (결정 2 배타)."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    # close(82500)>pivot(80000) 이라 promotion 조건(>=0.95*pivot)도 충족하지만
    # breakout_from_watch 가 우선.
    assert evaluate(**_watch_kwargs()) == "breakout_from_watch"


def test_excluded_reason_falls_back_to_promotion():
    """base_forming/extended(비-ALLOWED) 는 fresh_cross 여도 promotion 유지 (D2)."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    for reason in ("base_forming", "extended"):
        assert evaluate(**_watch_kwargs(watch_reason=reason)) == "promotion"


def test_watch_reason_none_backward_compat_promotion():
    """기존 레코드(watch_reason=None)는 breakout_from_watch 비대상 → promotion (하위호환)."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    assert evaluate(**_watch_kwargs(watch_reason=None)) == "promotion"


def test_not_fresh_cross_already_extended_falls_back_to_promotion():
    """prev_close 가 이미 pivot 위(어제도 돌파 상태=extended) → fresh_cross=False → promotion."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    assert evaluate(**_watch_kwargs(prev_close=81000)) == "promotion"


def test_prev_close_none_conservative_no_breakout_from_watch():
    """prev_close 누락 → fresh_cross=False (보수) → breakout_from_watch 미발화 → promotion."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    assert evaluate(**_watch_kwargs(prev_close=None)) == "promotion"


def test_breakout_from_watch_low_volume_no_trigger():
    """fresh_cross 지만 거래량 평균 미만 → breakout_from_watch·promotion 둘 다 미발화 → None."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    assert evaluate(**_watch_kwargs(volume=900_000)) is None


def test_invalidation_preempts_breakout_from_watch():
    """invalidation(종가<SMA50)은 ALLOWED watch fresh_cross 여도 최우선."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    # close < sma_50 → invalidation 우선 (fresh_cross 무관)
    assert evaluate(**_watch_kwargs(close=74000, sma_50=75000, prev_close=79500)) == "invalidation"


def test_entry_breakout_ignores_fresh_cross_and_watch_reason():
    """entry breakout 경로는 fresh_cross/watch_reason 무관 — 기존 동작 보존(회귀 방지)."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    # prev_close 이미 pivot 위(=not fresh) 여도 entry 는 breakout.
    assert evaluate(
        close=82500, pivot_price=80000, prev_close=81000,
        volume=1_500_000, avg_volume_50d=1_000_000,
        stop_loss=76000, sma_50=78000, classification="entry",
    ) == "breakout"
