"""변경 감지 해시 — 제목·본문·코멘트 본문·참조 이슈 상태만 입력(라벨·updatedAt·코멘트
시각은 제외: 요약 내용에 영향 없는 메타 변경으로 Claude 를 다시 부르지 않기 위해)."""
from __future__ import annotations

import hashlib
import re

from .github import IssueRaw, RefState

# "#123" — 앞이 단어문자가 아니고 뒤가 숫자 아닌 곳에서 끝나는 것만. "#fff"·"#12abc" 제외.
_REF_RE = re.compile(r"(?<![\w&])#(\d{1,6})(?![\w])")


def extract_refs(raw: IssueRaw) -> set[int]:
    text = "\n".join([raw.body, *(c.body for c in raw.comments)])
    refs = {int(m) for m in _REF_RE.findall(text)}
    refs.discard(raw.number)
    return refs


def content_hash(raw: IssueRaw, refs: list[RefState]) -> str:
    h = hashlib.sha256()
    h.update(raw.title.encode("utf-8")); h.update(b"\x00")
    h.update(raw.body.encode("utf-8")); h.update(b"\x00")
    for c in raw.comments:
        h.update(c.body.encode("utf-8")); h.update(b"\x01")
    h.update(b"\x00")
    for r in sorted(refs, key=lambda r: r.number):
        h.update(f"{r.number}:{r.state}".encode("utf-8")); h.update(b"\x02")
    return h.hexdigest()
