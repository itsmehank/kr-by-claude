"""recent_transition_count_63d 순수 함수 — 경계 가드 (#118 rtc_63d, 13차 맵 §1-1).

13차 구현 전 확인 반영:
- ① F→T 정의 = #117 이벤트 정의(extract_transitions §2.1)와 자구 동일
- ② 관측창 <63거래일 = None (0 금지 — 신규 상장 '안정 통과' 위장 방지)
"""
from kr_pipeline.llm_runner.compute.recent_transition import (
    WINDOW_ROWS,
    recent_transition_count_63d,
)


def test_window_constant_is_63():
    """§0 정의 상수 — thresholds.py 무접촉(맵 §2), 지역 정의 63 고정."""
    assert WINDOW_ROWS == 63


def test_short_history_returns_none_not_zero():
    """확인 ②: 62행(관측창 부족) → None. 0 이면 신규 상장이 '안정 통과'로 위장."""
    assert recent_transition_count_63d([False] * 62) is None


def test_exactly_63_rows_counts():
    """63행 = 관측창 정확 충족 → 확정값. 말미 F→T 1회."""
    passes = [False] * 62 + [True]
    assert recent_transition_count_63d(passes) == 1


def test_asof_day_transition_included():
    """기준일(마지막 행) 당일 전환 포함 — look-ahead 없는 당일 포함 규약."""
    passes = [True] * 62 + [False, True]
    # 62 True → False (전환 아님) → True (F→T 1회, 당일)
    assert recent_transition_count_63d(passes[-63:]) == 1


def test_no_transition_is_zero():
    """전환 없음 → 확정 0 (None 아님 — 관측창 충족 시 0 은 정보)."""
    assert recent_transition_count_63d([True] * 63) == 0
    assert recent_transition_count_63d([False] * 63) == 0


def test_multiple_transitions_counted():
    """F→T 반복 전부 계수 — #117 '반복 전환' 관심사의 노출 지표."""
    passes = [False, True, False, True, False, True] + [True] * 57
    assert recent_transition_count_63d(passes) == 3


def test_none_rows_break_adjacency_not_spliced():
    """결측(None) 행 무시 — #117 자구(is False AND is True) 그대로:
    None 은 어느 쪽도 아니므로 F→None→T 는 전환 불성립(재접합 금지)."""
    passes = [False, None, True] + [True] * 60
    assert recent_transition_count_63d(passes) == 0


def test_transition_older_than_window_excluded():
    """창 밖(63거래일 이전) 전환 배제 — 100행, 전환이 창 시작 직전 행에만 존재."""
    passes = [False] * 100
    passes[100 - 64] = True  # 창(마지막 63행) 밖 마지막 행에서 F→T
    assert recent_transition_count_63d(passes) == 0


def test_transition_at_window_start_included():
    """창 시작 행(len-63)의 전환은 직전 행(len-64)과 비교해 포함."""
    passes = [False] * 100
    for i in range(100 - 63, 100):
        passes[i] = True  # 창 시작 행에서 F→T 후 유지
    assert recent_transition_count_63d(passes) == 1


def test_definition_identical_to_issue117_lineage():
    """확인 ①: 계산이 extract_transitions(#111/#117 §2.1) 재사용으로 자구 동일."""
    import inspect

    from kr_pipeline.llm_runner.compute import recent_transition

    src = inspect.getsource(recent_transition)
    assert "extract_transitions" in src, (
        "F→T 정의는 minervini_forward.extract_transitions 재사용으로 보장해야 함 "
        "(복제 금지 — 자구 동일의 코드 보장, 13차 확인 ①)"
    )
