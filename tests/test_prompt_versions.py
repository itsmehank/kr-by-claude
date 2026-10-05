"""#197 — prompts/VERSIONS.md 가 현재 모든 프롬프트 파일의 해시를 담는다(회신 23 Q-E: 프롬프트 변경과 같은 커밋에 행 추가)."""
from datetime import date
from pathlib import Path

from kr_pipeline.llm_runner.llm.claude_cli import PROMPTS_DIR, prompt_version_of

VERSIONS = PROMPTS_DIR / "VERSIONS.md"


def _sections() -> dict[str, str]:
    out, name = {}, None
    for line in VERSIONS.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            name = line[4:].strip()
            out[name] = ""
        elif name is not None:
            out[name] += line + "\n"
    return out


def test_every_prompt_hash_is_registered_in_its_section():
    sections = _sections()
    missing = []
    for p in sorted(PROMPTS_DIR.glob("*.md")):
        if p.name == VERSIONS.name:
            continue
        v = prompt_version_of(p.read_text(encoding="utf-8"))
        if f"`{v}`" not in sections.get(p.name, ""):
            missing.append(f"### {p.name} 절에 추가: | `{v}` | {date.today().isoformat()} | — | <변경 요지> |")
    assert not missing, "prompts/VERSIONS.md 미등록(프롬프트 변경과 같은 커밋에 행 추가):\n" + "\n".join(missing)


def test_versions_header_keeps_cutover_warning():
    text = VERSIONS.read_text(encoding="utf-8")
    assert "129건+" in text and "백필 금지(#194)" in text


def test_versions_file_is_not_loaded_as_a_prompt():
    """VERSIONS.md 는 프롬프트가 아니다 — call_claude 호출처가 이 이름을 쓰지 않는다."""
    root = Path(__file__).parent.parent
    hits = [p for p in (root / "kr_pipeline").rglob("*.py") if "VERSIONS.md" in p.read_text(encoding="utf-8")]
    assert hits == []
