from datetime import date


def test_draw_sample_is_deterministic():
    from kr_pipeline.backtest.sample import draw_sample
    frame = [f"{i:06d}" for i in range(1000)]
    a = draw_sample(frame, n=100, seed=20260623)
    b = draw_sample(frame, n=100, seed=20260623)
    assert a == b                 # 같은 시드 → 동일
    assert len(a) == 100
    assert len(set(a)) == 100     # 중복 없음
    assert a == sorted(a)         # 정렬 반환
    c = draw_sample(frame, n=100, seed=1)
    assert c != a                 # 다른 시드 → 다름


def test_draw_sample_order_independent():
    from kr_pipeline.backtest.sample import draw_sample
    frame1 = [f"{i:06d}" for i in range(1000)]
    frame2 = list(reversed(frame1))
    # 입력 순서가 달라도(내부 정렬) 동일 표본
    assert draw_sample(frame1, seed=20260623) == draw_sample(frame2, seed=20260623)


def test_draw_sample_n_exceeds_frame():
    from kr_pipeline.backtest.sample import draw_sample
    assert sorted(draw_sample(["a", "b", "c"], n=100, seed=1)) == ["a", "b", "c"]
