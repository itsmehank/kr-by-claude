"""(#194) B6 prompt_version 배선 — claude_cli 가 meta_out 에 채운 값을 호출처가 llm_meta 로 옮기는지.

절단 지점(2026-09-17 확정, 09-19 추가 1곳): 호출처가 llm_io → llm_meta 재조립 시 키를 누락 — store 경로
6곳(weekend·daily_delta·evaluate_pivot·llm_runner/backfill·backtest/backfill·backtest/recall_backfill).
이 테스트는 'store 로 가는 LLM 메타 dict 는 전부 prompt_version 을 전달한다'를 정적으로 강제한다 —
새 호출처가 같은 실수를 반복하면 여기서 잡힌다(값 자체의 검증은 test_p02_plumbing B6).
범위 밖: backtest/recall_phase2.py·trigger_audit.py 는 JSON 파일에 "llm_model" 로 기록(DB 컬럼 없음).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CALL_SITES = [
    "kr_pipeline/llm_runner/weekend.py",
    "kr_pipeline/llm_runner/daily_delta.py",
    "kr_pipeline/llm_runner/evaluate_pivot.py",
    "kr_pipeline/llm_runner/backfill.py",
    "kr_pipeline/backtest/backfill.py",
    "kr_pipeline/backtest/recall_backfill.py",
]
_STORE_META_RE = re.compile(r'"model":\s*llm_io\.get\("model"\)')


def test_every_llm_meta_dict_forwards_prompt_version():
    for rel in CALL_SITES:
        src = (ROOT / rel).read_text(encoding="utf-8")
        n_model = len(re.findall(r'"model":\s*llm_io\.get\("model"\)', src))
        n_pv = len(re.findall(r'"prompt_version":\s*llm_io\.get\("prompt_version"\)', src))
        assert n_model >= 1, rel
        assert n_pv == n_model, f"{rel}: LLM 메타 dict {n_model}개 중 prompt_version 전달 {n_pv}개"


def test_no_other_llm_meta_builder_without_prompt_version():
    """kr_pipeline 전체에서 store 규약("model": llm_io.get("model"))으로 메타를 조립하는 파일은 목록 밖에 없어야 한다."""
    found = set()
    for p in (ROOT / "kr_pipeline").rglob("*.py"):
        if _STORE_META_RE.search(p.read_text(encoding="utf-8")):
            found.add(str(p.relative_to(ROOT)))
    assert found == set(CALL_SITES), found ^ set(CALL_SITES)
