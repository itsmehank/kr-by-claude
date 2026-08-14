# (#68) F-S2 러너 표본 구성 — look #9(A+B) / look #10(표본 C) 해석.
from datetime import date


def test_resolve_config_ab_default_unchanged():
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
    from scripts.issue68_fs2_observe import resolve_config

    cfg = resolve_config("ab")
    assert cfg["tickers"] == list(FROZEN_SAMPLE) + list(FROZEN_SAMPLE_B)
    assert cfg["windows"] == {}          # 기본 윈도(2021~24 상수) 그대로


def test_resolve_config_c_uses_prereg_windows():
    """표본 C 윈도 = independent-window prereg §1 리터럴."""
    from kr_pipeline.backtest.frozen_sample_c import FROZEN_SAMPLE_C
    from scripts.issue68_fs2_observe import resolve_config

    cfg = resolve_config("c")
    assert cfg["tickers"] == list(FROZEN_SAMPLE_C)
    assert cfg["windows"] == {
        "watch_start": date(2017, 7, 1), "watch_end": date(2020, 12, 31),
        "px_start": date(2017, 1, 1), "px_end": date(2021, 6, 30),
    }
    assert "look #10" in cfg["label"]
