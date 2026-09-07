"""(항목 ① 2026-09-07) 일간 극값 신호 T5·T6·TA-d — 코드 키 ↔ 프롬프트 동기화 grep 가드.

compute_daily_extremes 가 내는 모든 키가 analyze_chart_v3.md 에 등장해야 하고, §6.1
결합식이 "T1~T6" 로 갱신돼 있어야 한다. 잔여 불일치(코드만 바뀌고 프롬프트 미반영, 또는
그 역)를 기계적으로 잡는다.
"""
from pathlib import Path

from kr_pipeline.llm_runner.compute.climax_topping import _DAILY_KEYS, compute_daily_extremes

_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "analyze_chart_v3.md"


def _prompt() -> str:
    return _PROMPT.read_text(encoding="utf-8")


def test_daily_keys_all_named_in_prompt():
    text = _prompt()
    anchor = {"anchor_week": None, "left_censored": True, "no_transition": False, "weeks_since": None}
    produced = set(compute_daily_extremes(None, None, anchor))
    assert produced == set(_DAILY_KEYS)
    for k in _DAILY_KEYS:
        assert k in text, f"prompt 에 {k} 미등재"


def test_prompt_61_trigger_count_is_t1_to_t6():
    text = _prompt()
    s61 = text[text.index("#### 6.1 climax_run"):text.index("#### 6.2 topping_distribution")]
    assert "T1~T6 중 ≥1" in s61
    assert "- T5 `t5_daily_max_up_now`" in s61
    assert "- T6 `t6_daily_max_spread_now`" in s61
    assert "TTLC Ch.9 단독 출처" in s61  # D-2: Minervini 단독 출처 병기 필수


def test_prompt_62_has_ta_d_beside_ta():
    text = _prompt()
    s62 = text[text.index("#### 6.2 topping_distribution"):]
    i_ta = s62.index("- T-A `ta_max_decline_now`")
    i_tad = s62.index("- TA-d `ta_d_daily_max_decline_now`")
    i_tb = s62.index("- T-B `tb_ok`")
    assert i_ta < i_tad < i_tb
    # anchor 의존 게이트 목록에도 등재
    assert "`ta_d_daily_max_decline_now` 는 `left_censored=True` 면" in s62
