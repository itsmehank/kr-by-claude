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
    # Q-8: null 트리거 미평가 규칙 + (#169) no_transition 모드에서 anchor 의존 필드 전부 null 명시
    assert "T5·T6 이 `null` 이면 해당 트리거는 미평가" in s61
    assert "**anchor 의존 필드는 left_censored\n  와 동일하게 전부 `null`**" in s61
    assert "climax_run 은 발화 불가**\n  (left_censored 와 동일)" in s61
    assert "전체 이력** 기준으로 계산됨" not in s61  # 구 #44 규약 문구 잔존 금지


def test_prompt_null_rule_scoped_and_left_censored_rule_intact():
    text = _prompt()
    s61 = text[text.index("#### 6.1 climax_run"):text.index("#### 6.2 topping_distribution")]
    # 전 필드 null(left_censored) 규칙 불변 — 발화 금지 문장 유지
    assert "climax_run 을 발화하지" in s61 and "`left_censored=True`" in s61
    # Supporting 은 트리거 아님(7번째 OR 분지 금지) 문장 유지
    assert "Supporting 은 트리거가 아니다" in s61


def test_prompt_62_has_ta_d_beside_ta():
    text = _prompt()
    s62 = text[text.index("#### 6.2 topping_distribution"):]
    i_ta = s62.index("- T-A `ta_max_decline_now`")
    i_tad = s62.index("- TA-d `ta_d_daily_max_decline_now`")
    i_tb = s62.index("- T-B `tb_ok`")
    assert i_ta < i_tad < i_tb
    # anchor 의존 게이트 목록: 주간 T-A/T-D 거래량·일간 TA-d 모두 left_censored·no_transition 에서 null (#169)
    assert ("`td_max_down_volume_now`, 일간판 `ta_d_daily_max_decline_now` 는 `left_censored` **와\n"
            "`no_transition` 모두** `null`") in s62
    assert "`null` 이면 미평가 — 나머지(T-A/T-B/T-C/T-D)로만 판정" in s62
    assert "anchor 없이 전체 이력 기준으로 계산된다" not in s62  # 구 #44 규약 문구 잔존 금지


def test_prompt_top_ssot_declaration():
    # (#169 / #170 Q-2 B) governance 4-6 — 프롬프트 상단 SSOT 자기 선언
    first = _prompt().splitlines()[0]
    assert first.startswith("<!-- SSOT:") and "governance.md 4-6" in first
