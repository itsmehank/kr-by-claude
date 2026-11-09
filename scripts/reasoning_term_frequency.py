"""Reasoning 용어 빈도 — 화면용 용어 사전(web/src/data/reasoningGlossary.ts) 후보 수집.

읽기 전용(READ ONLY 트랜잭션). 결과는 stdout 에만 출력하고 파일로 저장하지 않는다.
대상 = 화면에 보이는 reasoning: weekly_classification, trigger_evaluation_log.
spec: docs/superpowers/specs/2026-11-09-reasoning-glossary-design.md D2

사용: uv run python scripts/reasoning_term_frequency.py [--top 60] [--missing]
  --missing : 사전(reasoningGlossary.ts)의 alias 로 덮이지 않는 후보만 출력
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from kr_pipeline.db.connection import connect

TABLES = ("weekly_classification", "trigger_evaluation_log")

PATTERNS: dict[str, re.Pattern[str]] = {
    "snake_case 플래그": re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"),
    "key=value": re.compile(r"\b[a-z_][a-z0-9_.]*=[A-Za-z0-9_.]+"),
    "절 번호(§)": re.compile(r"§\s?\d+(?:\.\d+)*"),
    "게이트·조건 번호": re.compile(r"\b(?:Gate\s?\d|G\d|c\d(?:\s?[·,~]\s?c\d)*)\b"),
    "책·저자": re.compile(r"\b(?:HMMS|TLSMW|TTLC|O'Neil|Minervini|Weinstein|CAN SLIM)\b"),
    "영문 구(소문자)": re.compile(r"\b[a-z]+(?:[- ][a-z]+){1,3}\b"),
    "영문 단어(대문자 포함)": re.compile(r"\b[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,2}\b"),
}

GLOSSARY_TS = Path(__file__).resolve().parent.parent / "web/src/data/reasoningGlossary.ts"


def glossary_aliases() -> set[str]:
    if not GLOSSARY_TS.exists():
        return set()
    text = GLOSSARY_TS.read_text(encoding="utf-8")
    out: set[str] = set()
    for block in re.findall(r"aliases:\s*\[(.*?)\]", text, flags=re.S):
        out.update(a.lower() for a in re.findall(r'"((?:[^"\\]|\\.)*)"', block))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--missing", action="store_true")
    args = ap.parse_args()

    texts: list[str] = []
    with connect() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        for t in TABLES:
            rows = conn.execute(f"SELECT reasoning FROM {t} WHERE reasoning IS NOT NULL").fetchall()
            texts.extend(r[0] for r in rows)
    print(f"reasoning {len(texts)}건 ({', '.join(TABLES)})\n")

    known = glossary_aliases() if args.missing else set()
    for name, pat in PATTERNS.items():
        # 한 reasoning 안 반복은 1회로(문서 빈도)
        c: Counter[str] = Counter()
        for tx in texts:
            c.update({m.group(0) for m in pat.finditer(tx)})
        items = [(k, v) for k, v in c.most_common() if k.lower() not in known]
        print(f"## {name}")
        for k, v in items[: args.top]:
            print(f"{v:6d}  {k}")
        print()


if __name__ == "__main__":
    main()
