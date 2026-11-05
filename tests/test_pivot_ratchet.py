"""(#253) 방향 한정 래칫 순수 함수 — 스펙 §3.1 표.

same/near 베이스에서 새 pivot < 직전 effective 면 직전 값 유지(kept), 그 외 새 값.
"""
import pytest

from kr_pipeline.llm_runner.compute.pivot_ratchet import ratchet_pivot


@pytest.mark.parametrize("new,prev,cont,pat,exp", [
    # 새 pivot 없음 → NULL
    (None, 23650.0, "same", "cup_with_handle", (None, "no_pivot")),
    (float("nan"), 23650.0, "same", "cup_with_handle", (None, "no_pivot")),
    # 직전 기준 없음(관측 None / 직전 pivot None) → 새 값
    (22050.0, None, None, "cup_with_handle", (22050.0, "no_baseline")),
    (22050.0, None, "same", "cup_with_handle", (22050.0, "no_baseline")),
    # 베이스 변경·비교 불능 → 새 값
    (22050.0, 23650.0, "different", "cup_with_handle", (22050.0, "released")),
    (22050.0, 23650.0, "unknown", "cup_with_handle", (22050.0, "unknown")),
    # 3-C/low cheat 는 같은 컵 안의 정당한 더 낮은 pivot(현재 비활성 패턴)
    (22050.0, 23650.0, "same", "3c_cheat", (22050.0, "cheat_release")),
    # same/near 하향 → 유지
    (22050.0, 23650.0, "same", "cup_with_handle", (23650.0, "kept")),
    (22050.0, 23650.0, "near", "cup_with_handle", (23650.0, "kept")),
    # 동일·상향 → 새 값
    (23650.0, 23650.0, "same", "cup_with_handle", (23650.0, "accepted")),
    (23800.0, 23650.0, "same", "cup_with_handle", (23800.0, "accepted")),
])
def test_ratchet_pivot_table(new, prev, cont, pat, exp):
    assert ratchet_pivot(new, prev, cont, pat) == exp
