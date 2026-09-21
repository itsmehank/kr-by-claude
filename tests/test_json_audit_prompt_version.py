"""(#198) LLM 감사 JSON 산출물(trigger_audit·recall_phase2)의 프롬프트 버전 귀속.

전문가 판정 회신 9 Q-3 #198 A: prompt_version 키 없으면 실행 차단, 해시 산출은 PR #196 과 동일 함수(SSOT),
기존 JSON 은 소급 추정 금지(null 유지).
"""
import json
import pathlib
from datetime import date

import pytest

from kr_pipeline.llm_runner.llm import claude_cli


def test_prompt_version_of_is_the_single_hash_function():
    import hashlib
    text = "## Pre-Check\nfoo\n"
    assert claude_cli.prompt_version_of(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    assert len(claude_cli.prompt_version_of(text)) == 12


def _arm_trigger_audit(monkeypatch, tmp_path, fill_meta: bool):
    import kr_pipeline.backtest.trigger_audit as ta
    trade = {"ticker": "000001", "entry_date": date(2026, 7, 1), "phase": "breakout",
             "pivot_sat": date(2026, 6, 27), "watch_reason": "base_forming"}
    monkeypatch.setattr(ta, "collect_down_trades", lambda conn, tickers=None, max_chase_pct=None: [trade])
    monkeypatch.setattr(ta, "prior_row_for", lambda conn, t, d: {"classified_at": None})
    monkeypatch.setattr(ta, "build_for_5b", lambda *a, **k: {"symbol": "000001"})

    def fake_call(prompt_file, attachments, payload_inline, dry_run, meta_out):
        meta_out["model"] = "m"; meta_out["input_tokens"] = 1; meta_out["output_tokens"] = 1
        if fill_meta:
            meta_out["prompt_version"] = claude_cli.prompt_version_of("PROMPT")
        return {"decision": "wait", "confidence": 0.5, "reasoning": "r", "abort_reason": None}

    monkeypatch.setattr(ta, "call_claude", fake_call)
    return ta, tmp_path / "audit.json"


def test_trigger_audit_records_prompt_version(db, tmp_path, monkeypatch):
    ta, p = _arm_trigger_audit(monkeypatch, tmp_path, fill_meta=True)
    agg = ta.run_audit(db, dry_run=False, path=p)
    assert agg["processed"] == 1
    rec = json.loads(p.read_text(encoding="utf-8"))["results"][0]
    assert rec["prompt_version"] == claude_cli.prompt_version_of("PROMPT")
    assert rec["llm_model"] == "m"


def test_trigger_audit_blocks_when_prompt_version_missing(db, tmp_path, monkeypatch):
    """키 부재 = 실행 차단. 산출물 파일은 생성/변경되지 않는다."""
    ta, p = _arm_trigger_audit(monkeypatch, tmp_path, fill_meta=False)
    with pytest.raises(RuntimeError, match="prompt_version"):
        ta.run_audit(db, dry_run=False, path=p)
    assert not p.exists()


def test_recall_phase2_records_and_guards_prompt_version_statically():
    """recall_phase2 는 main 안의 루프라 동작 테스트 대신 정적 확인 — 기록 키 + 차단 가드가 같은 블록에 있다."""
    src = (pathlib.Path(__file__).resolve().parents[1] / "kr_pipeline/backtest/recall_phase2.py").read_text(encoding="utf-8")
    assert '"prompt_version": llm_io["prompt_version"]' in src
    assert 'if "prompt_version" not in llm_io:' in src
    assert src.index('if "prompt_version" not in llm_io:') < src.index('"prompt_version": llm_io["prompt_version"]')


def test_existing_audit_json_not_backfilled():
    """기존 산출물은 소급 추정 금지 — 레코드에 prompt_version 키가 없거나 null 이어야 한다(값이 채워져 있으면 백필 위반)."""
    root = pathlib.Path(__file__).resolve().parents[1] / "data" / "backtest"
    for name in ("recall_trigger_audit_20260702.json", "trigger_audit_20260702.json", "trigger_audit_sample_b_20260721.json"):
        f = root / name
        if not f.exists():
            continue
        for rec in json.loads(f.read_text(encoding="utf-8")).get("results", []):
            assert rec.get("prompt_version") is None, name
