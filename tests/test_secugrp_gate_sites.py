"""(Q-5) minervini_pass 산출 3곳이 SSOT 조각/함수를 참조하는지 — 손으로 쓴 조건문 금지(전문가 판정 회신 3).

plan: docs/superpowers/plans/2026-09-15-secugrp-universe-filter.md Task 5.
"""
import inspect
import pathlib
import re

from kr_pipeline.indicators import delisted, store


def test_daily_and_weekly_updates_reference_ssot_fragment():
    for fn in (store.update_daily_indicators_minervini_pass, store.update_weekly_indicators_minervini_pass):
        src = inspect.getsource(fn)
        assert "security_group_gate_sql(" in src, fn.__name__
        assert "security_group_gate_params()" in src, fn.__name__
        stripped = src.replace("security_group_gate_sql(", "").replace("security_group_gate_params()", "")
        # docstring 의 설명 문구는 허용 — 코드 라인(따옴표 밖)에서의 직접 참조만 금지
        code_lines = [ln for ln in stripped.splitlines() if not ln.strip().startswith(("\"\"\"", "#", "(Q-5)"))]
        assert not any(re.search(r"security_group\b(?!_gate)", ln) for ln in code_lines if "\"\"\"" not in ln), \
            f"{fn.__name__}: SSOT 조각 외 security_group 직접 참조 금지"


def test_delisted_compute_references_ssot_predicate():
    src = inspect.getsource(delisted.compute_delisted_rows)
    assert "is_gated_out(" in src
    assert "QUALIFYING_SECURITY_GROUPS" not in src   # 집합을 직접 비교하지 않는다


def test_no_other_minervini_pass_writer_bypasses_gate():
    """minervini_pass 를 쓰는 산출 지점은 2파일(3곳)뿐이어야 한다(우회 경로 = 필터 아님)."""
    root = pathlib.Path(__file__).resolve().parents[1] / "kr_pipeline"
    writers = []
    for p in root.rglob("*.py"):
        txt = p.read_text(encoding="utf-8")
        if re.search(r"SET\s+[^;]*minervini_pass\s*=", txt) or re.search(r'"minervini_pass":\s*\(?\s*(None|all\()', txt):
            writers.append(str(p.relative_to(root)))
    assert sorted(writers) == ["indicators/delisted.py", "indicators/store.py"], writers
