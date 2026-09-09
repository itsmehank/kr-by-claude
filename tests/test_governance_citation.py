"""(#155 B9c, 2026-09-09) governance 미인용 규범 문장 감지 — **경고 모드**(실패시키지 않음).

대상: docs/superpowers/plans/*.md, docs/superpowers/specs/*.md, (존재 시) CC 메모리 *.md.
면제: 상단 "[기록 문서]" 배너가 있는 파일(기존 413건 규범 문장은 작성 시점 기록 — governance 4-5).
감지 규칙: 한 줄에 규범 어휘가 있고, 같은 줄 또는 직전 2줄에 governance 절 ID / checklist 절 /
프롬프트 § / trading-rules § 인용이 없으면 flag. 코드 펜스 안·표 헤더·인용 부호 안은 제외.
실패 모드 전환은 오탐률 실측 후 별도 판정(threshold-change-checklist (f)).
"""
from __future__ import annotations

import os
import re
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC_DIRS = [ROOT / "docs" / "superpowers" / "plans", ROOT / "docs" / "superpowers" / "specs"]
MEMORY_DIR = Path(os.environ.get(
    "KR_CC_MEMORY_DIR",
    Path.home() / ".claude" / "projects" / "-Users-hank-es-git-personal-kr-by-claude" / "memory"))

BANNER = "[기록 문서]"
NORMATIVE = re.compile(r"금지|필수|반드시|불변|하지 않는다|로만 |우선한다|LOCKED|사전등록")
CITATION = re.compile(
    r"governance\s*(원칙\s*)?\d-\d|\[G\d-\d\]|checklist\s*\([a-f]\)|threshold-change-checklist"
    r"|prompt[s]?\s*§|analyze_chart_v3(\.md)?\s*§|evaluate_pivot\S*\s*§|trading-rules\S*\s*§"
)
QUOTED = re.compile(r"[\"“”'‘’「『][^\"“”'‘’」』]*(금지|필수|반드시|불변|하지 않는다)[^\"“”'‘’」』]*[\"“”'‘’」』]")


def scan_file(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    head = "\n".join(lines[:5])
    if BANNER in head:
        return []
    flagged, in_fence = [], False
    for i, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or ln.startswith("|---") or ln.startswith("#"):
            continue
        if not NORMATIVE.search(ln):
            continue
        if QUOTED.search(ln) and not NORMATIVE.search(QUOTED.sub("", ln)):
            continue  # 인용 부호 안에만 있는 규범 어휘(책 인용 등)
        ctx = "\n".join(lines[max(0, i - 2): i + 1])
        if CITATION.search(ctx):
            continue
        flagged.append((i + 1, ln.strip()[:120]))
    return flagged


def collect() -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    targets = [p for d in DOC_DIRS if d.exists() for p in sorted(d.glob("*.md"))]
    if MEMORY_DIR.exists():
        targets += sorted(MEMORY_DIR.glob("*.md"))
    for p in targets:
        hits = scan_file(p)
        if hits:
            out[str(p.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else f"memory/{p.name}"] = hits
    return out


def test_uncited_normative_sentences_warning_mode():
    """경고 모드: 미인용 규범 줄을 출력만 한다(governance 4-5 / checklist (f)). 실패 없음."""
    found = collect()
    total = sum(len(v) for v in found.values())
    if total:
        report = "\n".join(f"{f}:{ln}: {txt}" for f, hits in found.items() for ln, txt in hits)
        warnings.warn(
            f"[governance-citation] 미인용 규범 줄 {total}건 / {len(found)}파일 (경고 모드)\n{report}",
            stacklevel=1,
        )
    # 실패 모드 전환 전까지 항상 통과 — 결과는 warning 으로 노출
    assert True
